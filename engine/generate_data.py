"""Generate synthetic P&C claims with planted fraud patterns for the phase 1 prototype.

Everything here is invented. The planted patterns mirror the PRD rules (FR-02 to FR-06)
so the back-test can show which signals find which kind of fraud.

Usage: python3 generate_data.py [n_claims] [seed]
Writes claims.json next to this script.
"""
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 7
rng = random.Random(SEED)

TODAY = date(2026, 10, 1)
REGIONS = ["North", "South", "East", "West", "Central"]
FIRST = ["Ade", "Bola", "Chidi", "Dami", "Efe", "Funmi", "Gbenga", "Halima", "Ife", "Jide",
         "Kemi", "Lola", "Musa", "Ngozi", "Obi", "Pelumi", "Rotimi", "Sade", "Tunde", "Uche",
         "Anna", "Ben", "Carla", "David", "Emma", "Femi", "Grace", "Hassan", "Irene", "John"]
LAST = ["Adeyemi", "Bello", "Chukwu", "Danjuma", "Eze", "Fashola", "Garba", "Ibrahim", "Johnson",
        "Kalu", "Lawal", "Mohammed", "Nwosu", "Okafor", "Oyelaran", "Peters", "Sani", "Smith",
        "Taiwo", "Usman", "Williams", "Yusuf"]

LINES = {
    # line: list of (peril, median amount, spread)
    "Motor": [("Collision", 2400, 0.6), ("Theft", 9000, 0.5), ("Windscreen", 350, 0.3), ("Third-party injury", 6000, 0.8)],
    "Property": [("Water damage", 3800, 0.7), ("Fire", 18000, 0.9), ("Burglary", 4200, 0.6), ("Storm", 5200, 0.7)],
}
REPAIRERS = {
    "Motor": [f"R-M{i:02d}" for i in range(1, 26)],
    "Property": [f"R-P{i:02d}" for i in range(1, 21)],
}
RING_REPAIRERS = {"Motor": "R-M07", "Property": "R-P13"}


def name():
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def phone():
    return "080" + "".join(rng.choice("0123456789") for _ in range(8))


def account():
    return "".join(rng.choice("0123456789") for _ in range(10))


def address():
    return f"{rng.randint(1, 240)} {rng.choice(['Allen', 'Broad', 'Church', 'Market', 'Station', 'Park', 'River', 'Hill'])} {rng.choice(['Road', 'Street', 'Avenue', 'Close'])}"


def lognormal(median, spread):
    return median * rng.lognormvariate(0, spread)


claims = []
policies = {}
claim_no = 100000
invoice_no = 50000


def new_policy(line, region):
    pid = f"P{len(policies) + 1:06d}"
    inception = TODAY - timedelta(days=rng.randint(40, 1400))
    policies[pid] = {"policy_id": pid, "line": line, "region": region, "inception": inception}
    return pid


def make_claim(fraud_type=None, **override):
    global claim_no, invoice_no
    claim_no += 1
    invoice_no += rng.randint(1, 4)
    line = override.get("line") or rng.choice(["Motor", "Motor", "Property"])
    region = override.get("region") or rng.choice(REGIONS)
    pid = override.get("policy_id") or new_policy(line, region)
    pol = policies[pid]
    peril, med, spread = rng.choice(LINES[line])
    if "peril" in override:
        peril, med, spread = next(p for p in LINES[line] if p[0] == override["peril"])
    # loss date: anywhere after inception, within the last 2 years
    earliest = max(pol["inception"] + timedelta(days=1), TODAY - timedelta(days=720))
    loss = earliest + timedelta(days=rng.randint(0, max(1, (TODAY - earliest).days - 10)))
    report_lag = min(int(rng.expovariate(1 / 4)), 45)
    amount = round(lognormal(med, spread), 2)
    c = {
        "claim_id": f"C{claim_no}",
        "policy_id": pid,
        "line": line,
        "peril": peril,
        "region": region,
        "claimant": override.get("claimant") or name(),
        "phone": override.get("phone") or phone(),
        "address": override.get("address") or address(),
        "bank_account": override.get("bank_account") or account(),
        "repairer": override.get("repairer") or rng.choice(REPAIRERS[line]),
        "policy_inception": pol["inception"].isoformat(),
        "loss_date": loss.isoformat(),
        "reported_date": (loss + timedelta(days=report_lag)).isoformat(),
        "amount_claimed": amount,
        "invoice_no": f"INV-{invoice_no}",
        "payee_account_changed_days_before_payment": None,
        "police_report": rng.random() < (0.85 if peril in ("Theft", "Burglary") else 0.2),
        "prior_claims_24m": rng.choices([0, 1, 2, 3], weights=[70, 20, 7, 3])[0],
        "photo_reused": False,
        "pdf_edited": rng.random() < 0.01,  # legit noise: scanners and phone apps re-save PDFs
        "truth_fraud": fraud_type is not None,
        "truth_type": fraud_type,
    }
    if rng.random() < 0.02:  # legit noise: genuine account changes happen
        c["payee_account_changed_days_before_payment"] = rng.randint(1, 30)
    return c


n_fraud = int(N * 0.05)
n_legit = N - n_fraud

for _ in range(n_legit):
    claims.append(make_claim())

# 1. Early-loss fraud: loss soon after inception, often high value and no police report
for _ in range(int(n_fraud * 0.2)):
    line = rng.choice(["Motor", "Property"])
    region = rng.choice(REGIONS)
    pid = new_policy(line, region)
    policies[pid]["inception"] = TODAY - timedelta(days=rng.randint(30, 400))
    c = make_claim("Early loss after inception", line=line, region=region, policy_id=pid,
                   peril="Theft" if line == "Motor" else "Fire")
    inc = date.fromisoformat(c["policy_inception"])
    loss = inc + timedelta(days=rng.randint(2, 25))
    c["loss_date"] = loss.isoformat()
    c["reported_date"] = (loss + timedelta(days=rng.randint(0, 5))).isoformat()
    c["police_report"] = rng.random() < 0.4
    claims.append(c)

# 2. Rings: unrelated claimants sharing a bank account or phone, using one repairer
ring_count = 0
target_ring = int(n_fraud * 0.3)
while ring_count < target_ring:
    line = rng.choice(["Motor", "Property"])
    shared_acct, shared_phone = account(), phone()
    size = rng.randint(3, 6)
    for i in range(size):
        c = make_claim("Organised ring", line=line, repairer=RING_REPAIRERS[line],
                       bank_account=shared_acct if rng.random() < 0.7 else None,
                       phone=shared_phone if rng.random() < 0.5 else None)
        c["amount_claimed"] = round(c["amount_claimed"] * rng.uniform(1.2, 1.8), 2)
        claims.append(c)
        ring_count += 1

# 3. Inflated invoices: amount far above peers, round numbers
for _ in range(int(n_fraud * 0.2)):
    c = make_claim("Inflated invoice")
    c["amount_claimed"] = float(round(c["amount_claimed"] * rng.uniform(3, 6), -2))
    claims.append(c)

# 4. Payee hijack: account changed right before payment, often to an account used elsewhere
hijack_accounts = [account() for _ in range(3)]
for _ in range(int(n_fraud * 0.15)):
    c = make_claim("Payee account changed")
    c["payee_account_changed_days_before_payment"] = rng.randint(0, 3)
    c["bank_account"] = rng.choice(hijack_accounts)
    claims.append(c)

# 5. Recycled evidence: reused photos, duplicated invoice numbers, edited PDFs
dup_pool = [c["invoice_no"] for c in rng.sample(claims[:n_legit], 10)]
while len(claims) < N:
    c = make_claim("Recycled evidence")
    roll = rng.random()
    if roll < 0.4:
        c["invoice_no"] = rng.choice(dup_pool)
    elif roll < 0.75:
        c["photo_reused"] = True
    else:
        c["pdf_edited"] = True
    c["reported_date"] = (date.fromisoformat(c["loss_date"]) + timedelta(days=rng.randint(30, 120))).isoformat()
    claims.append(c)

rng.shuffle(claims)

# Historic SIU outcomes: only a small share of past fraud was ever confirmed (assumption A7)
for c in claims:
    c["siu_history"] = None
    if c["truth_fraud"] and rng.random() < 0.12:
        c["siu_history"] = "confirmed"
    elif not c["truth_fraud"] and rng.random() < 0.004:
        c["siu_history"] = "not fraud"

out = Path(__file__).with_name("claims.json")
out.write_text(json.dumps(claims, indent=1))
print(f"wrote {len(claims)} claims, {sum(c['truth_fraud'] for c in claims)} planted fraud, "
      f"{sum(c['siu_history'] == 'confirmed' for c in claims)} historically confirmed -> {out.name}")
