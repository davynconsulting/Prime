"""Generate one month of synthetic bank statement lines and ledger open items for the phase 3 prototype.

Policies and claimants come from ../claims.json so all three phases share one book of business.
Each bank line carries the true matching items (truth_items, truth_kind) for the back-test only.

Usage: python3 generate_bank.py [seed]
Writes open_items.json and bank_lines.json next to this script.
"""
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 11)
MONTH_START = date(2026, 9, 1)
BROKERS = ["Harbor Brokers Ltd", "Crestline Insurance Brokers", "Unity Risk Partners", "Delta Cover Agency", "Northgate Brokers"]
BANKS = ["Main Collections A/C", "Claims Payments A/C"]

claims = json.loads((HERE.parent / "claims.json").read_text())
policies = {}
for c in claims:
    policies.setdefault(c["policy_id"], {"policy_id": c["policy_id"], "holder": c["claimant"], "line": c["line"]})
policy_list = list(policies.values())
for p in policy_list:
    p["broker"] = rng.choice(BROKERS) if rng.random() < 0.3 else None
    base = 85 if p["line"] == "Motor" else 140
    p["premium"] = round(base * rng.lognormvariate(0, 0.35), 2)


def day(offset_max=29):
    return (MONTH_START + timedelta(days=rng.randint(0, offset_max))).isoformat()


open_items, lines = [], []
item_no, line_no = 0, 0


def item(kind, ref, party, amount, due, **extra):
    global item_no
    item_no += 1
    it = {"item_id": f"OI{item_no:05d}", "kind": kind, "ref": ref, "party": party, "amount": round(amount, 2), "due": due, **extra}
    open_items.append(it)
    return it


def line(account, d, amount, payer, narrative, truth_items, truth_kind, **extra):
    global line_no
    line_no += 1
    ln = {"line_id": f"BL{line_no:05d}", "account": account, "date": d, "amount": round(amount, 2),
          "counterparty": payer, "narrative": narrative, "truth_items": truth_items, "truth_kind": truth_kind, **extra}
    lines.append(ln)
    return ln


def messy_ref(pid):
    digits = pid.lstrip("P").lstrip("0")
    return rng.choice([f"POL {digits} PREMIUM", f"PREM {pid.lower()}", f"policy no {digits}", f"{digits} MONTHLY", f"INSURANCE {digits}"])


# Premiums due this month: a monthly instalment on every policy
for p in policy_list:
    p["item"] = item("premium", p["policy_id"], p["holder"], p["premium"], day(27), broker=p["broker"])

direct = [p for p in policy_list if not p["broker"]]
brokered = [p for p in policy_list if p["broker"]]
rng.shuffle(direct)

# Direct payers: most pay cleanly, some messily, some partly, some not at all
for p in direct:
    it = p["item"]
    r = rng.random()
    d = (date.fromisoformat(it["due"]) + timedelta(days=rng.randint(-3, 4))).isoformat()
    if r < 0.58:
        line(BANKS[0], d, it["amount"], p["holder"].upper(), f"{p['policy_id']} PREMIUM", [it["item_id"]], "exact")
    elif r < 0.78:
        line(BANKS[0], d, it["amount"], p["holder"].upper(), messy_ref(p["policy_id"]), [it["item_id"]], "messy reference")
    elif r < 0.86:
        line(BANKS[0], d, it["amount"], p["holder"].upper(), rng.choice(["TRANSFER", "PAYMENT", "INSURANCE", "MOBILE TRF"]),
             [it["item_id"]], "name only")
    elif r < 0.90:
        line(BANKS[0], d, round(it["amount"] * rng.choice([0.5, 0.6, 0.75]), 2), p["holder"].upper(),
             f"{p['policy_id']} PART PAYMENT", [it["item_id"]], "partial")
    elif r < 0.93:
        fee = rng.choice([1.5, 2.0, 2.5, 3.0])
        line(BANKS[0], d, it["amount"] - fee, p["holder"].upper(), f"{p['policy_id']}", [it["item_id"]], "net of bank fee", fee=fee)
    # else unpaid this month: no line

# Brokers: one lump sum per broker per fortnight covering many policies
for b in BROKERS:
    mine = [p for p in brokered if p["broker"] == b]
    rng.shuffle(mine)
    half = len(mine) // 2
    for i, batch in enumerate([mine[:half], mine[half:]]):
        paid = [p for p in batch if rng.random() < 0.92]
        if not paid:
            continue
        total = sum(p["item"]["amount"] for p in paid)
        commission = round(total * 0.1, 2)
        line(BANKS[0], (MONTH_START + timedelta(days=13 + 14 * i)).isoformat(), total - commission, b.upper(),
             f"PREMIUM REMITTANCE {MONTH_START:%b}".upper() + f" BATCH {i + 1}", [p["item"]["item_id"] for p in paid],
             "broker lump sum", commission=commission,
             # most brokers send a remittance advice listing the policies paid; some do not
             remittance_advice=[p["policy_id"] for p in paid] if rng.random() < 0.8 else None)

# Unidentified receipts: no item at all
for _ in range(12):
    line(BANKS[0], day(), round(rng.uniform(40, 400), 2), rng.choice(["J SMITH", "CASH DEPOSIT", "UNKNOWN", "A. OKAFOR"]),
         rng.choice(["DEPOSIT", "TRANSFER", "REF 0091"]), [], "unidentified")

# Claim payments issued this month: debits on the claims account
paid_claims = rng.sample([c for c in claims if not c["truth_fraud"]], 260)
for c in paid_claims:
    net = max(50.0, round(c["amount_claimed"] * rng.uniform(0.75, 1.0) - 250, 2))
    it = item("claim payment", c["claim_id"], c["claimant"], -net, day(25), payee_account=c["bank_account"])
    d = (date.fromisoformat(it["due"]) + timedelta(days=rng.randint(0, 2))).isoformat()
    r = rng.random()
    if r < 0.94:
        line(BANKS[1], d, -net, c["claimant"].upper(), f"CLAIM {c['claim_id']}", [it["item_id"]], "exact",
             beneficiary_account=c["bank_account"])
    elif r < 0.96:
        line(BANKS[1], d, -net, c["claimant"].upper(), f"CLAIM {c['claim_id']}", [it["item_id"]], "exact",
             beneficiary_account=c["bank_account"])
        line(BANKS[1], (date.fromisoformat(d) + timedelta(days=rng.randint(1, 5))).isoformat(), -net, c["claimant"].upper(),
             f"CLAIM {c['claim_id']}", [it["item_id"]], "duplicate payment", beneficiary_account=c["bank_account"])
    elif r < 0.98:
        other = "".join(rng.choice("0123456789") for _ in range(10))
        line(BANKS[1], d, -net, c["claimant"].upper(), f"CLAIM {c['claim_id']}", [it["item_id"]], "paid to unknown account",
             beneficiary_account=other)
    else:
        line(BANKS[1], d, -net, c["claimant"].upper(), f"CLAIM {c['claim_id']}", [it["item_id"]], "exact",
             beneficiary_account=c["bank_account"])
        line(BANKS[1], (date.fromisoformat(d) + timedelta(days=3)).isoformat(), net, "RETURN " + c["claimant"].upper(),
             f"RTN CLAIM {c['claim_id']} ACCOUNT CLOSED", [it["item_id"]], "returned payment")

# Bank charges
for acct in BANKS:
    for wk in range(4):
        line(acct, (MONTH_START + timedelta(days=7 * wk + 6)).isoformat(), -round(rng.uniform(15, 60), 2), "BANK",
             rng.choice(["ACCOUNT MAINTENANCE FEE", "SERVICE CHARGES", "SMS ALERT CHARGES"]), [], "bank fee")

rng.shuffle(lines)
lines.sort(key=lambda l: l["date"])
(HERE / "open_items.json").write_text(json.dumps(open_items, indent=1))
(HERE / "bank_lines.json").write_text(json.dumps(lines, indent=1))
kinds = {}
for l in lines:
    kinds[l["truth_kind"]] = kinds.get(l["truth_kind"], 0) + 1
print(f"{len(open_items)} open items, {len(lines)} bank lines: {kinds}")
