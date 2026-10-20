"""Phase 3 reconciliation engine prototype: rule matching first, fuzzy suggestions for the rest.

Every bank line gets a proposal with a confidence and plain-language reasons (RC-03, RC-04).
Proposals at or above AUTO_CLEAR are cleared automatically (RC-05); the rest go to an analyst.
Duplicate payments, payments to unknown accounts and returned payments become fraud events (RC-08).
Standard library only.

Usage: python3 reconcile.py [auto_clear_threshold]
Reads open_items.json and bank_lines.json, writes recon.json.
"""
import json
import re
import sys
from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).parent
AUTO_CLEAR = float(sys.argv[1]) if len(sys.argv) > 1 else 0.9
FEE_TOLERANCE = 5.0  # a shortfall up to this is treated as a bank fee and journaled (RC-07)
COMMISSION = 0.10    # broker commission netted from remittances

items = json.loads((HERE / "open_items.json").read_text())
lines = json.loads((HERE / "bank_lines.json").read_text())
by_ref = {it["ref"]: it for it in items}
by_id = {it["item_id"]: it for it in items}
consumed = defaultdict(float)  # item_id -> amount already matched


def remaining(it):
    return round(abs(it["amount"]) - consumed[it["item_id"]], 2)


def policy_from_text(text):
    m = re.search(r"\bP(\d{6})\b", text, re.I)
    if m:
        return f"P{m.group(1)}", "exact policy number in the reference"
    for d in re.findall(r"\b(\d{1,6})\b", text):
        pid = f"P{int(d):06d}"
        if pid in by_ref:
            return pid, f"policy number read from free text \"{text}\""
    return None, None


def similar(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def propose(ln):
    """Return a proposal dict for one bank line."""
    text, amt = ln["narrative"], ln["amount"]
    p = {"items": [], "kind": "unmatched", "confidence": 0.0, "reasons": [], "journal": None, "event": None}

    if ln["counterparty"] == "BANK" and re.search(r"FEE|CHARGE", text):
        p.update(kind="bank fee", confidence=0.97, reasons=["Bank's own charge, identified from the narrative"],
                 journal={"account": "Bank charges", "amount": -amt})
        return p

    claim = re.search(r"\b(C\d{6})\b", text)
    if claim and claim.group(1) in by_ref:
        it = by_ref[claim.group(1)]
        if "RTN" in text and amt > 0:
            p.update(items=[it["item_id"]], kind="returned payment", confidence=0.95,
                     reasons=[f"Return of the payment on claim {it['ref']}", "Claim payment must be reissued to a valid account"],
                     event={"type": "Returned claim payment", "claim": it["ref"]})
            return p
        if abs(amt - it["amount"]) < 0.01:
            if consumed[it["item_id"]] >= abs(it["amount"]) - 0.01:
                p.update(items=[it["item_id"]], kind="duplicate payment", confidence=0.95,
                         reasons=[f"Claim {it['ref']} was already paid this amount", "Recover the second payment"],
                         event={"type": "Duplicate claim payment", "claim": it["ref"]})
                return p
            if ln.get("beneficiary_account") and ln["beneficiary_account"] != it.get("payee_account"):
                p.update(items=[it["item_id"]], kind="paid to unknown account", confidence=0.6,
                         reasons=[f"Amount and claim {it['ref']} match", f"Paid to account {ln['beneficiary_account']}, not the payee on file"],
                         event={"type": "Claim paid to an account not on file", "claim": it["ref"]})
                return p
            p.update(items=[it["item_id"]], kind="exact", confidence=1.0,
                     reasons=[f"Claim number {it['ref']} and amount match", "Paid to the payee account on file"])
            return p

    if ln.get("remittance_advice"):
        its = [by_ref[pid] for pid in ln["remittance_advice"] if pid in by_ref]
        gross = sum(i["amount"] for i in its)
        net = round(gross * (1 - COMMISSION), 2)
        ok = abs(net - amt) <= 0.05 * len(its) + 0.05
        p.update(items=[i["item_id"] for i in its], kind="broker lump sum", confidence=0.96 if ok else 0.7,
                 reasons=[f"Broker remittance advice lists {len(its)} policies",
                          f"Premiums {gross:,.2f} less {COMMISSION:.0%} commission = {net:,.2f}" + ("" if ok else f", but {amt:,.2f} was received")],
                 journal={"account": "Broker commission", "amount": round(gross - amt, 2)})
        return p
    if amt > 1000 and any(similar(ln["counterparty"], b) > 0.8 for b in BROKER_NAMES):
        p.update(kind="broker lump sum", confidence=0.3,
                 reasons=["Lump sum from a broker with no remittance advice", "Request the broker's statement to allocate it"])
        return p

    if amt > 0:
        pid, why = policy_from_text(text)
        if pid and pid in by_ref:
            it = by_ref[pid]
            due = remaining(it)
            short = round(due - amt, 2)
            name_ok = similar(ln["counterparty"], it["party"]) > 0.7
            name_note = "payer name matches the policyholder" if name_ok else "payer name differs from the policyholder"
            if abs(short) < 0.01:
                conf = 1.0 if "exact" in why else (0.95 if name_ok else 0.85)
                p.update(items=[it["item_id"]], kind="premium", confidence=conf, reasons=[why.capitalize(), "Amount equals the premium due", name_note.capitalize()])
            elif 0 < short <= FEE_TOLERANCE:
                p.update(items=[it["item_id"]], kind="net of bank fee", confidence=0.92 if name_ok else 0.8,
                         reasons=[why.capitalize(), f"Short by {short:.2f}, within the bank fee tolerance", name_note.capitalize()],
                         journal={"account": "Bank charges", "amount": short})
            elif 0 < amt < due:
                p.update(items=[it["item_id"]], kind="partial", confidence=0.75,
                         reasons=[why.capitalize(), f"Pays {amt:,.2f} of {due:,.2f} due", f"Leaves {due - amt:,.2f} outstanding on {pid}"])
            if p["items"]:
                return p

        # Name only: same amount, closest policyholder name among unpaid premiums
        cands = [it for it in items if it["kind"] == "premium" and abs(remaining(it) - amt) < 0.01]
        scored = sorted(((similar(ln["counterparty"], it["party"]), it) for it in cands), key=lambda t: -t[0])
        if scored and scored[0][0] >= 0.8:
            s, it = scored[0]
            unique = len(scored) == 1 or scored[1][0] < s - 0.15
            p.update(items=[it["item_id"]], kind="name and amount", confidence=round(0.55 + 0.3 * s if unique else 0.5, 2),
                     reasons=[f"No reference; payer \"{ln['counterparty']}\" resembles policyholder {it['party']} ({s:.0%})",
                              f"Amount equals the premium due on {it['ref']}",
                              "Only candidate with this amount and name" if unique else f"{len(scored)} policies have this amount"])
            return p

    p["reasons"] = ["No reference, amount or name matched an open item", "Hold in suspense and investigate"]
    return p


# Broker master data (the real system reads this from the policy admin system)
BROKER_NAMES = ["HARBOR BROKERS LTD", "CRESTLINE INSURANCE BROKERS", "UNITY RISK PARTNERS", "DELTA COVER AGENCY", "NORTHGATE BROKERS"]

out_lines = []
# Two passes: claim debits and exact references first, so duplicates and suggestions see what is already taken
order = sorted(lines, key=lambda l: (0 if re.search(r"\b[CP]\d{6}\b", l["narrative"]) else 1, l["date"]))
for ln in order:
    p = propose(ln)
    # Anything raising a fraud event always goes to a person, whatever its confidence
    p["status"] = "auto" if p["confidence"] >= AUTO_CLEAR and not p["event"] else "exception"
    # Treat every proposal as a tentative allocation, so no item is offered to two lines
    if p["items"] and p["kind"] not in ("duplicate payment", "returned payment"):
        for iid in p["items"]:
            consumed[iid] += abs(ln["amount"]) if len(p["items"]) == 1 else abs(by_id[iid]["amount"])
    truth = set(ln["truth_items"])
    correct = set(p["items"]) == truth and (truth or p["kind"] in ("bank fee", "unmatched", "broker lump sum"))
    out_lines.append({**{k: ln.get(k) for k in ("line_id", "account", "date", "amount", "counterparty", "narrative", "beneficiary_account")},
                      **p, "correct": bool(correct), "truth_kind": ln["truth_kind"]})

out_lines.sort(key=lambda l: (l["status"] != "exception", l["confidence"], l["date"]))
n = len(out_lines)
auto = [l for l in out_lines if l["status"] == "auto"]
exc = [l for l in out_lines if l["status"] == "exception"]
with_sugg = [l for l in exc if l["items"]]
unpaid = [it for it in items if it["kind"] == "premium" and remaining(it) > 0.01]
today = date(2026, 9, 30)
metrics = {
    "lines": n,
    "auto_cleared": len(auto),
    "auto_rate": round(len(auto) / n, 3),
    "wrong_auto": sum(not l["correct"] for l in auto),
    "exceptions": len(exc),
    "suggestions_right": sum(l["correct"] for l in with_sugg),
    "suggestions": len(with_sugg),
    "fraud_events": sum(1 for l in out_lines if l["event"]),
    "unpaid_premiums": len(unpaid),
    "unpaid_value": round(sum(remaining(it) for it in unpaid), 2),
    "threshold": AUTO_CLEAR,
    "by_kind": {},
}
for l in out_lines:
    k = metrics["by_kind"].setdefault(l["truth_kind"], {"lines": 0, "auto": 0, "right": 0})
    k["lines"] += 1
    k["auto"] += l["status"] == "auto"
    k["right"] += l["correct"]
ageing = defaultdict(lambda: {"count": 0, "value": 0.0})
for it in unpaid:
    days_over = (today - date.fromisoformat(it["due"])).days
    bucket = "Not yet due" if days_over < 0 else "0 to 7 days" if days_over <= 7 else "8 to 30 days"
    ageing[bucket]["count"] += 1
    ageing[bucket]["value"] = round(ageing[bucket]["value"] + remaining(it), 2)
metrics["ageing"] = dict(ageing)

item_view = {it["item_id"]: {"ref": it["ref"], "party": it["party"], "amount": it["amount"], "kind": it["kind"], "due": it["due"]} for it in items}
(HERE / "recon.json").write_text(json.dumps({"metrics": metrics, "lines": out_lines, "items": item_view}, separators=(",", ":")))
print(json.dumps({k: v for k, v in metrics.items() if k != "by_kind"}, indent=1))
for k, v in sorted(metrics["by_kind"].items(), key=lambda t: -t[1]["lines"]):
    print(f"  {k:26} lines {v['lines']:5}  auto {v['auto']:5}  right {v['right']:5}")
