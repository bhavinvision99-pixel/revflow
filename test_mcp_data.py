"""Checks the agent against the Seapoint staging MCP data (data/fixtures_mcp.json). No API key needed."""
import os
os.environ.pop("ANTHROPIC_API_KEY", None)
from pipeline import build_proposal, load_context, MCP_FIXTURES

# (vendor substring, reference, source) -> expected action
EXPECT = [
    ("Snowflake", "SNF-INV-2026-10", "EMAIL_SCAN", "mark_paid"),
    ("Snowflake", "SNF-INV-2026-10", "EMAIL_FORWARD", "reject_duplicate"),
    ("Clearview", "CM-2026-114", "UPLOAD", "hold"),             # payment already queued in Seapoint
    ("Clearview", "CM-2026-114", "EMAIL_SCAN", "reject_duplicate"),
    ("Lodgewood", "LWT-55120", None, "mark_paid"),
    ("Sentry", "SEN-2026-10-4471", None, "mark_paid"),
    ("Meridian Insurance", "MIB-2026-330", None, "mark_paid"),
    ("Connolly", "CA-2026-0918", None, "hold"),                 # unmatched 12 Oct payment
    ("Remote People", "RP-2026-10-118", None, "hold"),          # VAT 0.6% not 20%
    ("Meridian Translations", "MT-2026-0442", None, "hold"),    # NL VAT, GB country
    ("WeWork", "WW-UK-2026-11-4B", None, "hold"),               # above historic range
    ("Halberd", "HAL-3310", None, "hold"),                      # new payee > £2,000
    ("Fathom", "FTP-0931", None, "pay"),
    ("HubSpot", "HS-2026-8120", None, "pay"),
]
ctx = load_context(MCP_FIXTURES)
p = build_proposal(ctx, use_claude=False)
bad = 0
src = {i["id"]: i["source"] for i in ctx["invoices"]}
for vendor, ref, source, want in EXPECT:
    hits = [i for i in p["items"] if vendor in i["payee"] and i["reference"] == ref and (source is None or src[i["id"]] == source)]
    got = hits[0]["action"] if hits else "MISSING"
    ok = got == want
    bad += not ok
    print(("PASS " if ok else "FAIL ") + f"{vendor} {ref} {source or ''} -> {want}" + ("" if ok else f" (got {got})"))
assert not any(i["action"] == "pay" for i in p["items"] if any(f["severity"] == "block" for f in i["flags"]))
# forecast arithmetic (independent recomputation from the raw monthly figures)
F = p["forecast"]
def chk(name, ok):
    global bad
    print(("PASS " if ok else "FAIL ") + name); bad += not ok
chk("cash = sum of all five accounts (£2,459,109.84)", abs(F["cash"] - 2459109.84) < 0.01)
chk("3-month net burn = mean(Jul,Aug,Sep net) = £120,925.28", abs(F["burn"]["avg3"]["net"] - 120925.28) < 0.01)
chk("runway = cash / burn", abs(F["runway"]["avg3"] - round(2459109.84 / 120925.28, 1)) < 1e-9)
chk("timeline week 0 equals cash today", abs(F["timeline"][0]["no_income"] - F["cash"]) < 0.01 and abs(F["timeline"][0]["projected"] - F["cash"]) < 0.01)
chk("stress never above projected; projected never below spend-only", all(t["stress"] <= t["projected"] + 1e-6 and t["projected"] >= t["no_income"] - 1e-6 for t in F["timeline"]))
I = p["income"]
byc = {c["customer"]: c for c in I["customers"]}
chk("6 customers, 54 receipts", I["summary"]["n_customers"] == 6 and sum(c["n"] for c in I["customers"]) == 54)
chk("regular income = £8,580 a month (Acme 2,360 + Beta 2,860 + Delta 3,360)", I["summary"]["recurring_monthly"] == 8580)
chk("Cormorant is late (2-monthly payer, 18 Oct missed) and falling", byc["Cormorant Systems"]["status"] == "late" and byc["Cormorant Systems"]["trend"] == "falling")
chk("Acme, Beta, Delta on track", all(byc[n]["status"] == "on_track" for n in ("Acme Corp", "Beta Industries", "Delta Consulting")))
chk("Acme Retail and Globex are one-offs", byc["Acme Retail Group"]["status"] == "one_off" and byc["Globex Corporation"]["status"] == "one_off")
cm = byc["Cormorant Systems"]
chk("history: regular payers have never paid late (14,14,14,6 cycles)", all(c["history"]["late"] == 0 for c in I["customers"] if c["history"]) and
    sorted(c["history"]["cycles"] for c in I["customers"] if c["history"]) == [6, 14, 14, 14])
chk("late customer has a record line and a reminder draft", "first missed payment" in cm["record"] and "£4,400" in cm["reminder"]["body"] and "18 Oct" in cm["reminder"]["subject"])
chk("expected receipts = 9 (3 customers x 3 months) = £25,740", I["summary"]["n_expected"] == 9 and I["summary"]["expected_13w"] == 25740)
chk("late customer's payment is not in expected income", not any(e["customer"] == "Cormorant Systems" for e in I["expected"]))
chk("final projected = no-income + expected receipts", abs(F["timeline"][-1]["projected"] - F["timeline"][-1]["no_income"] - 25740) < 0.01)
chk("run total = sum of payable items in GBP", abs(F["run"]["pay_total"] - sum(x["gbp"] for x in F["run"]["payments"])) < 0.01)
chk("no paying account overdrawn", not any(a["overdrawn"] for a in F["run"]["accounts"]))
print("\nALL PASSED" if not bad else f"\n{bad} FAILED")
raise SystemExit(bad)
