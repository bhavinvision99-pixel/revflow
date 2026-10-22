"""Run with:  python3 test_agent.py   (no API key needed; the Claude path is tested with a mock)."""
import os
import sys
import types
from unittest import mock

from pipeline import build_proposal, load_context, UI_FIXTURES

EXPECTED = {
    "inv-01": "pay", "inv-02": "mark_paid", "inv-03": "hold", "inv-04": "pay", "inv-05": "mark_paid",
    "inv-06": "pay", "inv-07": "hold", "inv-08": "hold", "inv-09": "reject_duplicate", "inv-10": "mark_paid",
    "inv-11": "hold", "inv-12": "pay", "inv-13": "pay", "inv-14": "pay", "inv-15": "pay", "inv-16": "pay",
    "inv-17": "hold", "inv-18": "hold", "inv-19": "pay", "inv-20": "pay",
}
CODES = {  # the planted problems and the flag that must catch them
    "inv-08": "bank_details_changed", "inv-09": "duplicate_invoice", "inv-10": "already_paid",
    "inv-05": "already_paid", "inv-02": "already_paid", "inv-18": "unallocated_payment",
    "inv-17": "new_payee_large",
}

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def by_id(p):
    return {i["id"]: i for i in p["items"]}


# 1. rules-only run produces the expected action for every invoice
os.environ.pop("ANTHROPIC_API_KEY", None)
p = build_proposal(load_context(UI_FIXTURES), use_claude=True)
items = by_id(p)
for k, v in EXPECTED.items():
    check(f"rules: {k} -> {v}", items[k]["action"] == v, f"got {items[k]['action']}")
for k, code in CODES.items():
    check(f"rules: {k} has flag {code}", code in {f['code'] for f in items[k]["flags"]})
check("mode is rules-only without a key", p["mode"] == "rules-only")
check("nothing with a block flag is payable",
      all(i["action"] != "pay" for i in p["items"] if any(f["severity"] == "block" for f in i["flags"])))


# 2. mocked Claude: guardrail stops it loosening a block, accepts a stricter call
def fake_client_factory(decisions):
    class FakeMessages:
        def create(self, **kw):
            body = kw["messages"][0]["content"]
            assert "<invoice_data>" in body and kw["tool_choice"]["name"] == "submit_review"
            for ref, dec in decisions.items():
                if ref in body:
                    if isinstance(dec, Exception):
                        raise dec
                    return types.SimpleNamespace(content=[types.SimpleNamespace(type="tool_use", input=dec)])
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="tool_use", input={
                "action": "pay", "confidence": 0.9, "summary": "ok", "reasons": ["ok"], "next_step": "pay"})])

    class FakeClient:
        messages = FakeMessages()
    return FakeClient


decisions = {
    "NW-88690": {"action": "pay", "confidence": 0.9, "summary": "Looks fine", "reasons": ["x"], "next_step": "pay"},
    "FTP-0931": {"action": "hold", "confidence": 0.6, "summary": "Largest Fathom invoice this year",
                 "reasons": ["x"], "next_step": "Ask Fathom"},
    "AWS-INV-45190": RuntimeError("boom"),
}
os.environ["ANTHROPIC_API_KEY"] = "test"
with mock.patch("anthropic.Anthropic", lambda: fake_client_factory(decisions)):
    p2 = build_proposal(load_context(UI_FIXTURES), use_claude=True)
it = by_id(p2)
check("claude mode detected", p2["mode"] == "claude")
check("guardrail: Claude 'pay' on changed bank details is overridden to hold",
      it["inv-08"]["action"] == "hold" and it["inv-08"]["overridden"] is not None)
check("Claude may tighten pay -> hold", it["inv-13"]["action"] == "hold" and not it["inv-13"]["overridden"])
check("failed Claude call falls back to rules", it["inv-15"]["reviewed_by"].startswith("rules-only")
      and it["inv-15"]["action"] == "pay" and "boom" in it["inv-15"]["error"])
check("untouched invoices carry Claude as reviewer", it["inv-01"]["reviewed_by"].startswith("Claude"))

# 3. cash check holds a payment that would overdraw the paying account
ctx = load_context(UI_FIXTURES)
for a in ctx["accounts"]:
    if a["name"] == "Seapoint (EUR)":
        a["balance"] = 1000.0
os.environ.pop("ANTHROPIC_API_KEY")
p3 = build_proposal(ctx, use_claude=False)
check("insufficient funds -> hold", by_id(p3)["inv-19"]["action"] == "hold"
      and any(f["code"] == "insufficient_funds" for f in by_id(p3)["inv-19"]["flags"]))

print("\nALL PASSED" if not failures else f"\n{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
