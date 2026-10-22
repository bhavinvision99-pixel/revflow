"""Money in: customer payment patterns and expected receipts. Plain arithmetic, no AI.

Only RECEIPTS are visible through the Seapoint MCP. Invoices the company issues to customers are excluded from
query_invoices, so there are no sales invoices, due dates or overdue balances. "Late" here means: a customer that
pays on a regular cycle (every 1 or 2 months) has not paid when the next payment was expected.
"""
from calendar import monthrange
from datetime import date, timedelta
from statistics import median

MONTH = 30.44
GRACE_DAYS = 1          # days after the expected date before a regular payer counts as late
SOON_DAYS = 7


def _d(s):
    return date.fromisoformat(s[:10])


def add_months(d, k):
    y, m = divmod(d.month - 1 + k, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def analyse(ctx, horizon_days=91):
    receipts = ctx.get("receipts")
    if not receipts:
        return None
    as_of = _d(ctx["as_of"])
    horizon = as_of + timedelta(days=horizon_days)
    by = {}
    for r in receipts:
        by.setdefault(r["customer"], []).append(r)

    customers, expected = [], []
    for name, rows in by.items():
        rows.sort(key=lambda r: r["date"])
        dates = [_d(r["date"]) for r in rows]
        amts = [r["amount"] for r in rows]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        k = None
        if len(rows) >= 4:
            m = round(median(gaps) / MONTH)
            if m in (1, 2, 3) and all(abs(g - m * MONTH) <= 5 for g in gaps):
                k = m
        last, last_amt = dates[-1], amts[-1]
        history = None
        if k:
            delays = [(b - add_months(a, k)).days for a, b in zip(dates, dates[1:])]   # days after the expected date
            lates = [x for x in delays if x > GRACE_DAYS]
            history = {"cycles": len(delays), "late": len(lates), "on_time": len(delays) - len(lates),
                       "max_delay": max([0] + lates), "avg_delay": round(sum(lates) / len(lates), 1) if lates else 0}
        c = {"customer": name, "n": len(rows), "total": round(sum(amts), 2), "last_date": last.isoformat(),
             "last_amount": last_amt, "first_date": dates[0].isoformat(), "cadence_months": k,
             "typical": round(median(amts), 2), "reference": rows[-1].get("reference"), "history": history}
        # length of the run of steadily falling (or rising) amounts at the end of the history
        run_dn = run_up = 1
        for i in range(len(amts) - 1, 0, -1):
            if amts[i] < amts[i - 1]: run_dn += 1
            else: break
        for i in range(len(amts) - 1, 0, -1):
            if amts[i] > amts[i - 1]: run_up += 1
            else: break
        c["trend"] = "falling" if run_dn >= 4 else "rising" if run_up >= 4 else None
        c["trend_from"] = amts[-run_dn] if c["trend"] == "falling" else amts[-run_up] if c["trend"] == "rising" else None
        c["trend_n"] = run_dn if c["trend"] == "falling" else run_up
        c["first_amount"] = amts[0]
        if k:
            nxt = add_months(last, k)
            c["next_date"] = nxt.isoformat()
            c["next_amount"] = last_amt
            days_late = (as_of - nxt).days
            if days_late > GRACE_DAYS:
                c.update(status="late", days=days_late,
                         note=f"Usually pays every {k} month{'s' if k > 1 else ''}; the {fmt(nxt)} payment of "
                              f"£{last_amt:,.0f} has not arrived ({days_late} days).")
            elif (nxt - as_of).days <= SOON_DAYS:
                c.update(status="due_soon", days=(nxt - as_of).days, note=f"Next payment expected {fmt(nxt)}.")
            else:
                c.update(status="on_track", days=(nxt - as_of).days, note=f"Next payment expected {fmt(nxt)}.")
            if c["status"] != "late":
                d = nxt
                while d <= horizon:
                    expected.append({"date": d.isoformat(), "customer": name, "amount": last_amt})
                    d = add_months(d, k)
        elif len(rows) <= 2:
            c.update(status="one_off", days=(as_of - last).days, note=f"One-off payment on {fmt(last)}; no regular pattern.")
        else:
            since = (as_of - last).days
            c.update(status="irregular", days=since, note=f"No regular cycle; last paid {since} days ago.")
        if c["status"] == "late":
            h = c["history"]
            c["record"] = (f"Paid on time in all {h['cycles']} earlier cycles, so this is the first missed payment."
                           if h["late"] == 0 else
                           f"Late in {h['late']} of {h['cycles']} earlier cycles (worst {h['max_delay']} days, average {h['avg_delay']}).")
            company = ctx["company"].split(" (")[0]
            c["reminder"] = {
                "subject": f"Payment reminder: expected {fmt(_d(c['next_date']))} (£{c['next_amount']:,.0f})",
                "body": (f"Hi {c['customer']} team,\n\nI hope you are well. Our records show we have not yet received your usual "
                         f"payment of £{c['next_amount']:,.2f}, which we expected around {fmt(_d(c['next_date']))}.\n\n"
                         f"Could you let us know when we can expect it, or whether anything is holding it up? If it has already "
                         f"been sent, please reply with the payment reference so we can match it.\n\nMany thanks,\n{company}")}
        if c["trend"] == "falling":
            c["note"] += f" Payments have fallen {c['trend_n'] - 1} times in a row: £{c['trend_from']:,.0f} to £{last_amt:,.0f}."
        customers.append(c)

    order = {"late": 0, "due_soon": 1, "irregular": 2, "on_track": 3, "one_off": 4}
    customers.sort(key=lambda c: (order[c["status"]], -c["total"]))
    expected.sort(key=lambda e: e["date"])
    recurring = sum(c["last_amount"] / c["cadence_months"] for c in customers if c.get("cadence_months") and c["status"] != "late")
    at_risk = sum(c["last_amount"] for c in customers if c["status"] == "late")
    recv = lambda d0: sum(r["amount"] for r in receipts if d0 <= _d(r["date"]) <= as_of)
    return {
        "customers": customers, "expected": expected,
        "summary": {
            "received_30d": round(recv(as_of - timedelta(days=30)), 2), "received_90d": round(recv(as_of - timedelta(days=90)), 2),
            "recurring_monthly": round(recurring, 2), "n_late": sum(c["status"] == "late" for c in customers),
            "at_risk": round(at_risk, 2), "expected_13w": round(sum(e["amount"] for e in expected), 2),
            "n_expected": len(expected), "n_customers": len(customers)},
        "notes": ["Only incoming payments are visible. Invoices issued to customers are not exposed by the MCP, so there are "
                  "no customer invoice due dates or overdue balances: 'late' means a regular payer missed its usual cycle.",
                  "Expected receipts repeat each regular customer's last payment on its usual cycle. Late customers, "
                  "one-offs and irregular payers are not counted as expected income."],
    }


def fmt(d):
    return f"{d.day} {d.strftime('%b')}"
