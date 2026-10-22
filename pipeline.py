"""Gather -> rule checks -> Claude review -> proposal."""
import json
import os
from collections import defaultdict

from checks import run_checks, rule_action, money, flag
from review import review_all
from forecast import build_forecast
from receivables import analyse as analyse_receipts

_D = os.path.join(os.path.dirname(__file__), "data")
UI_FIXTURES = os.path.join(_D, "fixtures.json")          # reconstructed from the sandbox UI (used by tests)
MCP_FIXTURES = os.path.join(_D, "fixtures_mcp.json")     # built from the Seapoint staging MCP by from_mcp.py
DATA = os.environ.get("AP_DATA") or (MCP_FIXTURES if os.path.exists(MCP_FIXTURES) else UI_FIXTURES)

PAY_FROM = {"GBP": "Seapoint (GBP)", "EUR": "Seapoint (EUR)", "USD": "Seapoint (GBP)"}


def load_context(path=DATA):
    """Fixture-backed context. Replace with a Seapoint MCP-backed loader (see README)."""
    with open(path) as f:
        return json.load(f)


def build_proposal(ctx, use_claude=True):
    invoices = ctx["invoices"]
    by_id = {i["id"]: i for i in invoices}

    items = []
    for inv in invoices:
        flags = run_checks(inv, ctx)
        action, why = rule_action(flags, inv)
        items.append({
            "id": inv["id"], "payee": inv["payee"], "reference": inv["reference"],
            "amount": inv["amount"], "currency": inv["currency"], "due_date": inv["due_date"],
            "received_from": inv["received_from"], "description": inv.get("description"),
            "flags": flags, "rule_action": action, "rule_reason": why,
        })

    reviews = review_all(items, by_id, ctx, use_claude=use_claude)
    for item, rv in zip(items, reviews):
        item.update({"action": rv["action"], "confidence": round(float(rv["confidence"]), 2),
                     "summary": rv["summary"], "reasons": rv["reasons"], "next_step": rv["next_step"],
                     "reviewed_by": rv["reviewed_by"], "overridden": rv.get("overridden"),
                     "error": rv.get("error")})

    # Cash check: walk payable items by due date against the paying account's balance
    balances = {a["name"]: a["balance"] for a in ctx["accounts"]}
    for item in sorted((i for i in items if i["action"] == "pay"), key=lambda i: i["due_date"]):
        acct = ctx.get("pay_from", PAY_FROM)[item["currency"]]
        item["pay_from"] = acct
        if balances[acct] >= item["amount"]:
            balances[acct] -= item["amount"]
        else:
            item["action"] = "hold"
            fl = flag("insufficient_funds", "review",
                      f"{acct} has {money(balances[acct])} left in this run, less than {money(item['amount'], item['currency'])}.")
            item["flags"].append(fl)
            item["summary"] = fl["message"]
            item["next_step"] = "Transfer funds into the paying account, then pay."

    income = analyse_receipts(ctx)
    order = {"pay": 0, "hold": 1, "needs_info": 1, "mark_paid": 2, "reject_duplicate": 3}
    items.sort(key=lambda i: (order[i["action"]], i["due_date"]))
    return {"as_of": ctx["as_of"], "company": ctx["company"], "items": items,
            "income": income,
            "forecast": build_forecast(ctx, items, income=income),
            "summary": summarise(items), "balances_after_run": balances,
            "mode": "claude" if any(i["reviewed_by"].startswith("Claude") for i in items) else "rules-only"}


def summarise(items):
    by_action = defaultdict(lambda: defaultdict(float))
    counts = defaultdict(int)
    for i in items:
        by_action[i["action"]][i["currency"]] += i["amount"]
        counts[i["action"]] += 1
    fmt = lambda d: " + ".join(money(v, c) for c, v in sorted(d.items(), key=lambda kv: (kv[0] != "GBP", kv[0]))) or "—"
    return {
        "invoices": len(items),
        "counts": dict(counts),
        "to_pay": fmt(by_action["pay"]),
        "on_hold": fmt({c: v for a in ("hold", "needs_info") for c, v in by_action[a].items()}),
        "already_paid": fmt(by_action["mark_paid"]),
        "duplicates": fmt(by_action["reject_duplicate"]),
    }


if __name__ == "__main__":
    p = build_proposal(load_context(), use_claude=True)
    print(json.dumps(p["summary"], indent=2), "| mode:", p["mode"])
    for i in p["items"]:
        print(f"{i['action']:16} {i['id']} {i['payee'][:30]:30} {money(i['amount'], i['currency']):>12}  {i['summary'][:90]}")
