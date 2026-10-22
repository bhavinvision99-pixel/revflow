"""Cash forecast. Pure arithmetic over numbers pulled from the Seapoint MCP; no AI.

Follows Seapoint's published methodology (seapoint://finance/methodology/runway and burn-rate):
  current cash = BANKING cash_position + INVESTMENT total, in GBP
  runway       = current cash / |net burn|, net burn = debits - revenue credits (basis: last full month
                 or mean of the last three full months), cash-zero date = today + fractional months.

Known approximations (also printed in the UI): refunds and the Capital Investments carve-out are not
applied (the monthly aggregates did not split credits by type), only BOOKED rows were counted, and USD
has no rate in the MCP data so a fixed assumption is used.
"""
from datetime import date, timedelta
from statistics import mean

ASSUMED_FX_TO_GBP = {"GBP": 1.0, "EUR": 0.842524, "USD": 0.76}   # EUR rate from the MCP, USD is an assumption
DAYS_PER_MONTH = 30.44


def _d(s):
    return date.fromisoformat(s[:10])


def to_gbp(amount, ccy):
    return amount * ASSUMED_FX_TO_GBP.get(ccy, 1.0)


def build_forecast(ctx, items, horizon_weeks=13, income=None):
    cf = ctx.get("cashflow")
    if not cf:
        return None
    as_of = _d(ctx["as_of"])
    this_month = as_of.strftime("%Y-%m")
    full = [m for m in cf if m["month"] < this_month]
    net = lambda m: m["debits"] - m["credits"]
    last, last3 = full[-1], full[-3:]

    accounts = ctx["accounts"]
    cash = sum(a.get("gbp_balance", to_gbp(a["balance"], a["currency"])) for a in accounts)
    bank_cash = sum(a.get("gbp_balance", to_gbp(a["balance"], a["currency"])) for a in accounts
                    if a.get("type", "BANKING") == "BANKING")

    burn_last, burn_avg = net(last), mean(net(m) for m in last3)

    def runway(b):
        return None if b <= 0.01 else cash / b

    rw_last, rw_avg = runway(burn_last), runway(burn_avg)
    zero = lambda r: None if r is None else (as_of + timedelta(days=r * DAYS_PER_MONTH)).strftime("%b %Y")

    # --- this payment run ---------------------------------------------------------------
    pay_from = ctx.get("pay_from", {})
    pays, holds = [], []
    for i in items:
        row = {"id": i["id"], "payee": i["payee"], "reference": i["reference"], "amount": i["amount"],
               "currency": i["currency"], "gbp": round(to_gbp(i["amount"], i["currency"]), 2),
               "date": max(_d(i["due_date"]), as_of).isoformat(), "due": i["due_date"],
               "overdue": _d(i["due_date"]) < as_of, "account": i.get("pay_from") or pay_from.get(i["currency"])}
        if i["action"] == "pay":
            pays.append(row)
        elif i["action"] in ("hold", "needs_info"):
            holds.append(row)
    pays.sort(key=lambda r: r["date"])
    queued = [dict(p, gbp=round(to_gbp(p["amount"], p["currency"]), 2), account=None) for p in ctx.get("pending_payments", [])
              if not any(h["reference"] == p.get("reference") for h in holds)]   # held Clearview is already in holds

    by_acct = {}
    for a in accounts:
        by_acct[a["name"]] = {"account": a["name"], "currency": a["currency"], "opening": a["balance"],
                              "payments": 0.0, "n": 0, "lowest": a["balance"], "lowest_date": ctx["as_of"]}
    for r in pays:
        a = by_acct.get(r["account"])
        if not a:
            continue
        # express the payment in the paying account's own currency (e.g. a USD invoice paid from a GBP account)
        amt = r["amount"] if r["currency"] == a["currency"] else r["gbp"] / ASSUMED_FX_TO_GBP.get(a["currency"], 1.0)
        a["payments"] = round(a["payments"] + amt, 2)
        a["n"] += 1
        a["_run"] = a.get("_run", a["opening"]) - amt
        if a["_run"] < a["lowest"]:
            a["lowest"], a["lowest_date"] = round(a["_run"], 2), r["date"]
    for a in by_acct.values():
        a.pop("_run", None)
        a["after"] = round(a["opening"] - a["payments"], 2)
        a["overdrawn"] = a["lowest"] < 0
    accounts_out = [a for a in by_acct.values() if a["n"]] or list(by_acct.values())[:0]

    pay_total = round(sum(r["gbp"] for r in pays), 2)
    hold_total = round(sum(r["gbp"] for r in holds), 2)
    queued_total = round(sum(r["gbp"] for r in queued), 2)

    # --- timeline -----------------------------------------------------------------------
    # Spend = average monthly debits over the same months as the burn basis. Income = expected receipts from
    # regular customers (receivables.analyse). Both are on top of today's cash.
    avg_debits = mean(m["debits"] for m in last3)
    daily_spend = avg_debits / DAYS_PER_MONTH
    exp = (income or {}).get("expected", [])
    timeline = []
    for w in range(horizon_weeks + 1):
        day = as_of + timedelta(days=7 * w)
        spend_only = cash - daily_spend * 7 * w
        inc = sum(e["amount"] for e in exp if _d(e["date"]) <= day)
        extra = sum(r["gbp"] for r in holds if _d(r["date"]) <= day)     # stress: held invoices paid on top
        timeline.append({"date": day.isoformat(), "no_income": round(spend_only, 2),
                         "projected": round(spend_only + inc, 2), "stress": round(spend_only + inc - extra, 2)})
    recurring = (income or {}).get("summary", {}).get("recurring_monthly", 0.0)
    net_recurring = avg_debits - recurring
    rw_recurring = None if net_recurring <= 0.01 else round(cash / net_recurring, 1)

    big = max(cf[-6:-1], key=net) if len(cf) > 6 else last
    notes = [
        "The chart models spend as the 3-month average of monthly debits and income as the expected payments of regular "
        "customers only. Seapoint's runway figure nets off ALL income, including one-off receipts, so the two differ.",
        "Burn is net burn (debits minus all credits) from BOOKED transactions, in GBP; refunds and the Capital "
        "Investments carve-out are not split out, so treat the figures as indicative, not dashboard-exact.",
        f"The 'stress' line assumes every held invoice (£{hold_total:,.0f}) is also paid, on top of average spend. "
        "Both are subsets of normal spend, so this is deliberately conservative.",
        "USD is converted at an assumed 0.76 (the MCP supplied no USD rate); EUR uses the MCP rate 0.842524.",
        f"{last['month']} was unusually large: spend £{last['debits']:,.0f} against a normal £120k to £140k, with "
        f"income of £{last['credits']:,.0f}. Runway on the last-month basis is sensitive to that.",
    ]
    return {
        "currency": "GBP", "as_of": ctx["as_of"],
        "cash": round(cash, 2), "bank_cash": round(bank_cash, 2), "treasury": round(cash - bank_cash, 2),
        "burn": {"last_month": {"month": last["month"], "net": round(burn_last, 2),
                                "debits": last["debits"], "credits": last["credits"]},
                 "avg3": {"months": [m["month"] for m in last3], "net": round(burn_avg, 2)}},
        "runway": {"last_month": None if rw_last is None else round(rw_last, 1), "last_month_zero": zero(rw_last),
                   "avg3": None if rw_avg is None else round(rw_avg, 1), "avg3_zero": zero(rw_avg)},
        "run": {"pay_total": pay_total, "n_pay": len(pays), "hold_total": hold_total, "n_hold": len(holds),
                "queued_total": queued_total, "pct_of_bank_cash": round(100 * pay_total / bank_cash, 2) if bank_cash else None,
                "payments": pays, "queued": queued, "accounts": accounts_out,
                "months_of_burn": round(pay_total / burn_avg, 2) if burn_avg > 0 else None},
        "income": None if not income else {**income["summary"], "avg_monthly_debits": round(avg_debits, 2),
                                           "runway_recurring_only": rw_recurring},
        "timeline": timeline, "history": [{"month": m["month"], "net": round(net(m), 2)} for m in full],
        "notes": notes,
    }
