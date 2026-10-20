"""Phase 1 fraud scoring engine prototype: rules + peer-group anomalies + network links.

Needs no labelled fraud history (SRD stages 1 to 3). Uses only the Python standard library.

Usage: python3 score_claims.py [capacity_share]
Reads claims.json, writes scored.json (claims with score and reasons, plus back-test metrics).
"""
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
CAPACITY_SHARE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.05  # SIU can review 5% of claims
SCALE = 45  # points to score: score = 100 * (1 - exp(-points / SCALE))

# Rule set v1: editable by the SIU lead in the real system (SR-F03). weight, family, on/off.
RULES = {
    "early_loss":       {"weight": 30, "family": "Rule", "on": True},
    "late_report":      {"weight": 15, "family": "Rule", "on": True},
    "no_police_report": {"weight": 12, "family": "Rule", "on": True},
    "round_amount":     {"weight": 8,  "family": "Rule", "on": True},
    "frequent_claimant": {"weight": 8, "family": "Rule", "on": True},
    "payee_changed":    {"weight": 30, "family": "Payment", "on": True},
    "photo_reused":     {"weight": 30, "family": "Document", "on": True},
    "pdf_edited":       {"weight": 15, "family": "Document", "on": True},
    "duplicate_invoice": {"weight": 30, "family": "Document", "on": True},
}


def days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def robust_z(values):
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values) or 1e-9
    return med, mad * 1.4826


def main():
    claims = json.loads((HERE / "claims.json").read_text())

    # Peer groups for amount anomalies (SR-F04): line + peril, on log amount
    peers = defaultdict(list)
    for c in claims:
        peers[(c["line"], c["peril"])].append(math.log(c["amount_claimed"]))
    peer_stats = {k: robust_z(v) for k, v in peers.items()}

    # Repairer behaviour: median of each repairer's amount relative to its peer group
    rep_ratios = defaultdict(list)
    for c in claims:
        med, _ = peer_stats[(c["line"], c["peril"])]
        rep_ratios[c["repairer"]].append(math.log(c["amount_claimed"]) - med)
    rep_level = {r: statistics.median(v) for r, v in rep_ratios.items() if len(v) >= 8}
    rep_med, rep_sd = robust_z(list(rep_level.values()))

    # Duplicate invoice numbers across claims
    inv_count = defaultdict(int)
    for c in claims:
        inv_count[c["invoice_no"]] += 1

    # Entity graph (SR-F05): link claims sharing a bank account or phone, union-find
    parent = {c["claim_id"]: c["claim_id"] for c in claims}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    by_key = defaultdict(list)
    for c in claims:
        by_key[("acct", c["bank_account"])].append(c)
        by_key[("phone", c["phone"])].append(c)
    shared_with = defaultdict(set)  # claim -> kinds of shared identifiers with other claimants
    for (kind, _), group in by_key.items():
        names = {g["claimant"] for g in group}
        if len(group) > 1 and len(names) > 1:
            for g in group[1:]:
                union(group[0]["claim_id"], g["claim_id"])
            for g in group:
                shared_with[g["claim_id"]].add("bank account" if kind == "acct" else "phone number")
    components = defaultdict(list)
    for c in claims:
        components[find(c["claim_id"])].append(c)
    confirmed_components = {find(c["claim_id"]) for c in claims if c["siu_history"] == "confirmed"}

    scored = []
    for c in claims:
        signals = []  # (key, family, points, reason)

        def add(key, family, pts, reason):
            signals.append({"key": key, "family": family, "points": round(pts, 1), "reason": reason})

        def rule(key, reason):
            r = RULES[key]
            if r["on"]:
                add(key, r["family"], r["weight"], reason)

        since_inception = days(c["policy_inception"], c["loss_date"])
        if since_inception <= 30:
            rule("early_loss", f"Loss {since_inception} days after the policy started")
        lag = days(c["loss_date"], c["reported_date"])
        if lag > 30:
            rule("late_report", f"Reported {lag} days after the loss")
        if c["peril"] in ("Theft", "Burglary") and not c["police_report"]:
            rule("no_police_report", f"{c['peril']} claim with no police report")
        if c["amount_claimed"] >= 1000 and c["amount_claimed"] % 100 == 0:
            rule("round_amount", f"Round-number amount ({c['amount_claimed']:,.0f})")
        if c["prior_claims_24m"] >= 2:
            rule("frequent_claimant", f"{c['prior_claims_24m']} prior claims in 24 months")
        chg = c["payee_account_changed_days_before_payment"]
        if chg is not None and chg <= 7:
            rule("payee_changed", f"Payee bank account changed {chg} days before payment")
        if c["photo_reused"]:
            rule("photo_reused", "Photo also appears on another claim")
        if c["pdf_edited"]:
            rule("pdf_edited", "Invoice PDF shows signs of editing")
        if inv_count[c["invoice_no"]] > 1:
            rule("duplicate_invoice", f"Invoice number {c['invoice_no']} used on {inv_count[c['invoice_no']]} claims")

        med, sd = peer_stats[(c["line"], c["peril"])]
        z = (math.log(c["amount_claimed"]) - med) / sd
        if z > 2.0:
            times = c["amount_claimed"] / math.exp(med)
            add("amount_anomaly", "Anomaly", min(30, 12 * (z - 2) + 8),
                f"Amount is {times:.1f}x the typical {c['peril'].lower()} claim")
        if c["repairer"] in rep_level:
            rz = (rep_level[c["repairer"]] - rep_med) / (rep_sd or 1e-9)
            if rz > 2.5:
                add("repairer_anomaly", "Anomaly", 10, f"Repairer {c['repairer']} bills well above its peers")

        comp = components[find(c["claim_id"])]
        n_people = len({g["claimant"] for g in comp})
        if n_people >= 2:
            kinds = " and ".join(sorted(shared_with[c["claim_id"]])) or "contact details"
            pts = 25 if n_people >= 3 else 15
            add("network", "Network", pts, f"Shares a {kinds} with {n_people - 1} other claimant{'s' if n_people > 2 else ''}")
            if find(c["claim_id"]) in confirmed_components and c["siu_history"] != "confirmed":
                add("linked_confirmed", "Network", 20, "Linked to a previously confirmed fraud case")

        points = sum(s["points"] for s in signals)
        score = round(100 * (1 - math.exp(-points / SCALE)))
        signals.sort(key=lambda s: -s["points"])
        scored.append({
            **{k: c[k] for k in ("claim_id", "policy_id", "line", "peril", "region", "claimant", "phone",
                                 "bank_account", "repairer", "policy_inception", "loss_date",
                                 "reported_date", "amount_claimed", "invoice_no", "siu_history")},
            "network_id": find(c["claim_id"]) if n_people >= 2 else None,
            "score": score,
            "points": round(points, 1),
            "reasons": signals[:5],
            "truth_fraud": c["truth_fraud"],  # synthetic ground truth, for the back-test only
            "truth_type": c["truth_type"],
        })

    scored.sort(key=lambda s: -s["score"])
    capacity = round(len(scored) * CAPACITY_SHARE)
    threshold = scored[capacity - 1]["score"]
    for i, s in enumerate(scored):
        s["referred"] = i < capacity

    metrics = backtest(scored, capacity, threshold)
    out = {"generated": date.today().isoformat(), "rules": RULES, "metrics": metrics, "claims": scored}
    (HERE / "scored.json").write_text(json.dumps(out))
    print(json.dumps(metrics, indent=1))


def precision_recall(selected, all_claims):
    fraud_total = sum(c["truth_fraud"] for c in all_claims)
    hits = sum(c["truth_fraud"] for c in selected)
    return {"referred": len(selected), "fraud_caught": hits,
            "precision": round(hits / max(1, len(selected)), 3),
            "recall": round(hits / max(1, fraud_total), 3)}


def backtest(scored, capacity, threshold):
    """Compare the engine against a checklist baseline at the same SIU capacity (SR-M01)."""
    # Baseline: today's manual red-flag checklist (assumed): early loss, late report, no police report
    baseline_keys = {"early_loss", "late_report", "no_police_report"}
    base = sorted(scored, key=lambda s: -sum(r["points"] for r in s["reasons"] if r["key"] in baseline_keys))
    base_sel = [s for s in base[:capacity] if any(r["key"] in baseline_keys for r in s["reasons"])]

    engine = precision_recall(scored[:capacity], scored)
    baseline = precision_recall(base_sel, scored)

    by_type = defaultdict(lambda: {"total": 0, "caught": 0})
    for s in scored:
        if s["truth_fraud"]:
            by_type[s["truth_type"]]["total"] += 1
            by_type[s["truth_type"]]["caught"] += s["referred"]

    by_region = defaultdict(lambda: {"claims": 0, "referred": 0})
    for s in scored:
        by_region[s["region"]]["claims"] += 1
        by_region[s["region"]]["referred"] += s["referred"]
    for v in by_region.values():
        v["referral_rate"] = round(v["referred"] / v["claims"], 3)

    return {
        "claims": len(scored),
        "planted_fraud": sum(s["truth_fraud"] for s in scored),
        "historic_confirmed": sum(s["siu_history"] == "confirmed" for s in scored),
        "capacity": capacity,
        "threshold": threshold,
        "engine": engine,
        "baseline_checklist": baseline,
        "by_type": dict(by_type),
        "by_region": dict(by_region),
    }


if __name__ == "__main__":
    main()
