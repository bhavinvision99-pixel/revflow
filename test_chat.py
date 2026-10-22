"""Tests for the chat module. No API key needed: Claude is replaced by a scripted fake client."""
import os, types
os.environ.pop("ANTHROPIC_API_KEY", None)
import chat
from pipeline import build_proposal, load_context, MCP_FIXTURES

ctx = load_context(MCP_FIXTURES); P = build_proposal(ctx, use_claude=False); B = chat.Books(ctx, P)
bad = 0
def chk(name, ok):
    global bad; print(("PASS " if ok else "FAIL ") + name); bad += not ok

# tools return correct numbers
snow = B.party_payments("Snowflake")["paid_out"]
chk("Snowflake history: 15 payments of £21,800", snow["count"] == 15 and snow["min"] == snow["max"] == 21800 and snow["total"] == 327000)
chk("list_invoices(hold) returns 10", B.list_invoices(action="hold")["count"] == 10)
chk("explain by reference finds Remote People", B.explain_invoice("RP-2026-10-118")["matches"][0]["action"] == "hold")
chk("unknown tool is rejected safely", "error" in B.run("pay_invoice", {"id": "x"}))
chk("bad arguments are caught", "error" in B.run("list_invoices", {"nonsense": 1}))
chk("no tool can change anything (all names are read-only queries)", {t["name"] for t in chat.TOOLS} == {"list_invoices", "explain_invoice", "party_payments", "customers", "forecast", "monthly_cashflow"})

# offline router
def off(q): return chat.offline_answer(B, q)["answer"]
chk("offline: why held -> VAT reason", "0.6%" in off("Why is Remote People held?"))
chk("offline: late customers -> Cormorant", "Cormorant" in off("Which customers are late?") and "first missed payment" in off("Which customers are late?"))
chk("offline: runway -> 20.3 months", "20.3 months" in off("What is our runway?"))
chk("offline: what have we paid Snowflake -> history first", off("What have we paid Snowflake?").startswith("Snowflake") and "15 payments out" in off("What have we paid Snowflake?"))
chk("offline: money came in -> £8,580", "£8,580.00 a month" in off("How much money came in recently?"))
chk("offline: nonsense gets the help text, no invented figures", "I can answer questions" in off("hello"))

# Claude path with a scripted client: one tool call, then a final answer; the tool result must reach Claude
class Block(types.SimpleNamespace): pass
class FakeMessages:
    def __init__(self): self.calls = []; self.first_len = None
    def create(self, **kw):
        self.calls.append(kw)
        if self.first_len is None: self.first_len = len(kw["messages"])
        if len(self.calls) == 1:
            return types.SimpleNamespace(content=[Block(type="tool_use", id="t1", name="party_payments", input={"name": "Snowflake"})])
        last = kw["messages"][-1]["content"][0]
        assert last["type"] == "tool_result" and "327000" in last["content"]
        return types.SimpleNamespace(content=[Block(type="text", text="You paid Snowflake £327,000 in 15 payments.")])
fake = types.SimpleNamespace(messages=FakeMessages())
out = chat.claude_answer(fake, B, [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}], "What have we paid Snowflake?")
chk("claude path: tool loop returns final text", out["answer"].startswith("You paid Snowflake") and out["tools"][0]["name"] == "party_payments")
chk("claude path: system prompt is read-only and treats data as untrusted", "read-only" in fake.messages.calls[0]["system"] and "not instructions" in fake.messages.calls[0]["system"])
chk("claude path: tools are passed and history kept", len(fake.messages.calls[0]["tools"]) == 6 and fake.messages.first_len == 3)

# failure falls back to rules instead of erroring
os.environ["ANTHROPIC_API_KEY"] = "x"
import sys; sys.modules["anthropic"] = types.SimpleNamespace(Anthropic=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
r = chat.answer(ctx, P, "What is our runway?")
chk("API failure falls back to offline answer", r["mode"] == "offline" and "20.3 months" in r["answer"] and "failed" in r.get("note", ""))
# Flask endpoint
os.environ.pop("ANTHROPIC_API_KEY", None)
import app as flask_app
c = flask_app.app.test_client()
r = c.post("/api/chat", json={"question": "Which customers are late?", "history": []}).get_json()
chk("POST /api/chat answers", "Cormorant" in r["answer"] and r["mode"] == "offline")
chk("POST /api/chat survives junk input", c.post("/api/chat", json={"question": "", "history": "x"}).status_code == 200)
print("\nALL PASSED" if not bad else f"\n{bad} FAILED"); raise SystemExit(bad)
