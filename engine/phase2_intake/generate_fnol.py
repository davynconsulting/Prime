"""Generate synthetic first-notice-of-loss (FNOL) emails for the phase 2 prototype, plus a rules-only extraction.

Claims, claimants and fraud scores come from ../claims.json and ../scored.json, so phase 2 reuses
the phase 1 score as its straight-through-processing gate (CL-08).
The rules extraction is the fallback the page uses when Claude is not available, and the baseline
the back-test compares against.

Usage: python3 generate_fnol.py [n_messages] [seed]
Writes fnol.json next to this script.
"""
import json
import random
import re
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 5)

claims = json.loads((HERE.parent / "claims.json").read_text())
scores = {c["claim_id"]: c for c in json.loads((HERE.parent / "scored.json").read_text())["claims"]}

# Reserve guidance: peer median and quartiles per line and peril (CL-07)
peers = {}
for c in claims:
    peers.setdefault(f"{c['line']}|{c['peril']}", []).append(c["amount_claimed"])
reserve = {k: {"p25": round(statistics.quantiles(v, n=4)[0]), "median": round(statistics.median(v)),
               "p75": round(statistics.quantiles(v, n=4)[2])} for k, v in peers.items()}

COVER = {
    "Motor comprehensive": ["Collision", "Theft", "Windscreen", "Third-party injury"],
    "Motor third party, fire and theft": ["Theft", "Third-party injury"],
    "Home buildings and contents": ["Water damage", "Fire", "Burglary", "Storm"],
}
REQUIRED_DOCS = {
    "Collision": ["photos of the damage", "repair estimate", "other driver's details"],
    "Theft": ["police report", "both sets of keys"],
    "Windscreen": ["photo of the windscreen"],
    "Third-party injury": ["police report", "other party's details", "medical report"],
    "Water damage": ["photos of the damage", "plumber's report", "repair estimate"],
    "Fire": ["fire service report", "photos of the damage", "list of damaged items"],
    "Burglary": ["police report", "list of stolen items", "proof of ownership"],
    "Storm": ["photos of the damage", "repair estimate"],
}
PLACES = ["Allen Avenue, Ikeja", "Broad Street, Lagos Island", "Ring Road, Ibadan", "Ademola Adetokunbo Crescent, Abuja",
          "Aba Road, Port Harcourt", "Ahmadu Bello Way, Kaduna", "Herbert Macaulay Way, Yaba", "Okota Road, Isolo"]
EVENT = {
    "Collision": ["another car hit the back of my car at a junction", "I hit a pole while reversing", "a bus sideswiped my car in traffic"],
    "Theft": ["my car was stolen from outside my office", "my vehicle was taken from the car park overnight"],
    "Windscreen": ["a stone cracked my windscreen on the expressway", "my windscreen was shattered by falling debris"],
    "Third-party injury": ["a motorcyclist was injured when he collided with my car", "a pedestrian was hurt when I braked late"],
    "Water damage": ["a pipe burst in the kitchen and flooded the ground floor", "water leaked from the upstairs bathroom into the living room"],
    "Fire": ["a fire started in the kitchen and damaged two rooms", "an electrical fault caused a fire in the store room"],
    "Burglary": ["thieves broke in and took electronics and jewellery", "someone forced the back door and stole our laptop and TV"],
    "Storm": ["the storm last night blew off part of the roof", "heavy wind brought a tree down onto the fence and garage"],
}


def fmt_date(d, style):
    return [d.strftime("%d %B %Y").lstrip("0"), d.isoformat(), d.strftime("%d/%m/%Y"), "last " + d.strftime("%A")][style]


def fmt_amt(a, style):
    return [f"{a:,.0f}", f"about {round(a, -2):,.0f}", f"N{a:,.2f}", None][style]


pool = [c for c in claims if scores[c["claim_id"]]["score"] < 30]
risky = [c for c in claims if scores[c["claim_id"]]["referred"]]
small = [c for c in pool if c["amount_claimed"] < 1500]
picked = rng.sample(small, int(N * 0.35)) + rng.sample([c for c in pool if c not in small], int(N * 0.35))
picked += rng.sample(risky, N - len(picked))
rng.shuffle(picked)

messages = []
for i, c in enumerate(picked):
    loss = date.fromisoformat(c["loss_date"])
    received = loss + timedelta(days=rng.randint(0, 6))
    product = "Motor comprehensive" if c["line"] == "Motor" else "Home buildings and contents"
    if c["line"] == "Motor" and rng.random() < 0.12:
        product = "Motor third party, fire and theft"  # may not cover the peril claimed
    inception = date.fromisoformat(c["policy_inception"])
    expiry = inception + timedelta(days=365 * ((loss - inception).days // 365 + 1))
    if rng.random() < 0.08:
        expiry = loss - timedelta(days=rng.randint(5, 40))  # lapsed before the loss
    policy = {"policy_id": c["policy_id"], "holder": c["claimant"], "product": product, "inception": inception.isoformat(),
              "expiry": expiry.isoformat(), "perils": COVER[product], "limit": 25000 if c["line"] == "Motor" else 60000,
              "excess": 250 if c["line"] == "Motor" else 500}

    ds, ams, ps = rng.randint(0, 3), rng.randint(0, 3), rng.random()
    pol_text = (c["policy_id"] if ps < 0.6 else f"policy number {int(c['policy_id'][1:])}" if ps < 0.85 else None)
    amt_text = fmt_amt(c["amount_claimed"], ams)
    police = c["peril"] in ("Theft", "Burglary", "Third-party injury") and rng.random() < 0.7
    docs = rng.sample(REQUIRED_DOCS[c["peril"]], rng.randint(0, len(REQUIRED_DOCS[c["peril"]])))
    if police and "police report" not in docs and "police report" in REQUIRED_DOCS[c["peril"]]:
        docs.append("police report")
    place = rng.choice(PLACES)
    first = c["claimant"].split()[0]
    body = [rng.choice(["Good morning,", "Hello,", "Dear Sir/Madam,", "Hi Prime team,"]), ""]
    when = fmt_date(loss, ds)
    on_when = when[0].upper() + when[1:] if ds == 3 else f"On {when}"
    opener = rng.choice([f"I want to report a claim. {on_when} {rng.choice(EVENT[c['peril']])} at {place}.",
                         f"Please note that {rng.choice(EVENT[c['peril']])} {when if ds == 3 else 'on ' + when}. It happened at {place}.",
                         f"This is to notify you of an incident: {rng.choice(EVENT[c['peril']])}. Date: {when}. Location: {place}."])
    body.append(opener)
    if pol_text:
        body.append(rng.choice([f"My policy is {pol_text}.", f"Ref: {pol_text}", f"I am insured with you under {pol_text}."]))
    else:
        body.append("I don't have my policy number with me but the policy is in my name.")
    if amt_text:
        body.append(rng.choice([f"The repair estimate is {amt_text}.", f"The loss comes to {amt_text}.", f"I am claiming {amt_text}."]))
    else:
        body.append("I am still waiting for a quote for the repairs.")
    if police:
        body.append(f"I reported it to the police and have a report, reference {rng.choice(['LAG', 'ABJ', 'IBD'])}/{rng.randint(1000, 9999)}/26.")
    if docs:
        body.append("Attached: " + ", ".join(d for d in docs if d != "police report" or police) + ".")
    body.append(rng.choice(["Please advise on next steps.", "Kindly treat as urgent.", "Thank you.", "Let me know what else you need."]))
    body += ["", rng.choice(["Regards,", "Thanks,", "Yours faithfully,"]), c["claimant"], c["phone"]]
    text = "\n".join(body)

    truth = {"policy_number": c["policy_id"], "claimant_name": c["claimant"], "loss_date": c["loss_date"], "peril": c["peril"],
             "location": place, "amount_claimed": None if amt_text is None else round(c["amount_claimed"], 2),
             "police_report": police, "documents": sorted(set(docs) - ({"police report"} if not police else set()))}

    messages.append({
        "msg_id": f"FNOL-{i + 1:03d}", "received": received.isoformat(), "from": f"{first.lower()}.{c['claimant'].split()[1].lower()}@mail.example",
        "subject": rng.choice(["New claim", f"Claim notification - {c['claimant']}", "Incident report", f"{c['peril']} claim"]),
        "text": text, "claim_id": c["claim_id"], "line": c["line"], "policy": policy, "truth": truth,
        "fraud_score": scores[c["claim_id"]]["score"], "fraud_reasons": [r["reason"] for r in scores[c["claim_id"]]["reasons"][:3]],
        "planted_fraud": c["truth_fraud"],
    })


# ---- Rules-only extraction (fallback and baseline) ----
PERIL_WORDS = {
    "Windscreen": ["windscreen"], "Theft": ["stolen", "taken from"], "Burglary": ["broke in", "forced the back door", "stole"],
    "Fire": ["fire"], "Storm": ["storm", "wind"], "Water damage": ["pipe", "leak", "flood"],
    "Third-party injury": ["injured", "hurt"], "Collision": ["hit", "sideswiped", "collided"],
}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}


def rules_extract(m):
    t = m["text"]
    out = {}
    if (x := re.search(r"\bP\d{6}\b", t)):
        out["policy_number"] = (x.group(0), 0.98)
    elif (x := re.search(r"policy number (\d{1,6})", t, re.I)):
        out["policy_number"] = (f"P{int(x.group(1)):06d}", 0.85)
    else:
        out["policy_number"] = (None, 0.0)
    lines = [l for l in t.splitlines() if l.strip()]
    out["claimant_name"] = (lines[-2], 0.8)
    d = None
    if (x := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)):
        d, conf = date(int(x[1]), int(x[2]), int(x[3])), 0.97
    elif (x := re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", t)):
        d, conf = date(int(x[3]), int(x[2]), int(x[1])), 0.9
    elif (x := re.search(r"\b(\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})", t, re.I)):
        d, conf = date(int(x[3]), MONTHS[x[2].lower()], int(x[1])), 0.95
    out["loss_date"] = (d.isoformat() if d else None, conf if d else 0.0)
    found = [p for p, words in PERIL_WORDS.items() if any(w in t.lower() for w in words)]
    out["peril"] = (found[0] if found else None, 0.9 if len(found) == 1 else 0.5 if found else 0.0)
    x = re.search(r"(?:at|Location:) ([A-Z][^.]*?, [A-Z][a-z]+(?: [A-Z][a-z]+)?)\.", t)
    out["location"] = (x.group(1) if x else None, 0.8 if x else 0.0)
    x = re.search(r"(?:estimate is|comes to|claiming)\s+(about\s+)?N?([\d,]+(?:\.\d+)?)", t)
    out["amount_claimed"] = (float(x.group(2).replace(",", "")) if x else None, (0.6 if x.group(1) else 0.95) if x else 0.0)
    out["police_report"] = ("police" in t.lower(), 0.9)
    x = re.search(r"Attached: (.*)\.", t)
    out["documents"] = (sorted(s.strip() for s in x.group(1).split(",")) if x else [], 0.85)
    return {k: {"value": v, "confidence": c} for k, (v, c) in out.items()}


for m in messages:
    m["rules_extraction"] = rules_extract(m)

(HERE / "fnol.json").write_text(json.dumps({"messages": messages, "reserve": reserve, "required_docs": REQUIRED_DOCS,
                                            "stp": {"max_amount": 1500, "max_fraud_score": 30, "min_confidence": 0.85}}, indent=1))
correct = total = 0
for m in messages:
    for k, v in m["rules_extraction"].items():
        tv = m["truth"][k]
        ok = (v["value"] == tv) if not isinstance(tv, float) else (v["value"] is not None and abs(v["value"] - tv) < 1)
        correct += ok
        total += 1
print(f"wrote {len(messages)} messages; rules extraction field accuracy {correct}/{total} = {correct / total:.0%}")
