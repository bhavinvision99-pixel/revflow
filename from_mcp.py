"""Builds data/fixtures_mcp.json from raw Seapoint staging MCP query results saved in data/mcp_raw/.

Raw files are the (read-only) results of query_invoices, query_accounts, query_transactions and
query_payments, saved as returned by the MCP. Re-pull them (ask Claude to "refresh the MCP data")
and run:  python3 from_mcp.py

What the MCP does NOT expose, so it is left empty here: sender email address, invoice bank
details, saved payee bank details. The checks that need them (bank_details_changed,
internal_forward by address) therefore cannot fire on this data.
"""
import json
import os

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RAW = os.path.join(HERE, "mcp_raw")
AS_OF = "2026-10-20"

SOURCE_LABEL = {
    "EMAIL_SCAN": "invoice inbox (email scan)",
    "EMAIL_FORWARD": "forwarded@northstarlabs.example",   # internal forward; matches internal_domains
    "UPLOAD": "manual upload",
    "EMPLOYEE_BOOKKEEPING_UPLOAD": "employee expense upload",
}


def load(name):
    with open(os.path.join(RAW, name)) as f:
        return json.load(f)


def transactions():
    out, seen = [], set()
    for fn in ("tx_vendors_p1.json", "tx_other_p1.json", "tx_oct_all.json"):
        for t in load(fn)["data"]:
            if t["id"] in seen or t["direction"] != "debit" or t["status"] != "BOOKED":
                continue
            seen.add(t["id"])
            name = (t.get("participant") or {}).get("name")
            if not name:
                continue
            out.append({
                "date": t["date"][:10], "vendor": name, "amount": t["amount"], "currency": t["currency"],
                "account": t["account"]["name"],
                "category": (t.get("category") or {}).get("name", "").split("›")[-1].strip(),
                "matched_invoice": t.get("reference") or None,
                "has_evidence": t["has_evidence"], "type": t["type"], "id": t["id"],
            })
    for t in load("tx_vendors_p2_compact.json"):          # page 2, transcribed (older history)
        out.append({"date": t["date"], "vendor": t["vendor"], "amount": t["amount"], "currency": t["currency"],
                    "account": t["account"], "category": "", "matched_invoice": None,
                    "has_evidence": False, "type": "history", "id": None})
    # The same bank transaction can be in several raw files: de-duplicate on id. The transcribed page-2 rows
    # have no id, so they are only kept if no id-bearing row already matches them. Genuine repeat payments
    # (two identical £1,800 payments on one day) have different ids and are all kept.
    with_id = [t for t in out if t["id"]]
    keys = {(t["date"], t["vendor"], t["amount"], t["account"]) for t in with_id}
    uniq = [t for t in out if t["id"]] + [t for t in out if not t["id"] and (t["date"], t["vendor"], t["amount"], t["account"]) not in keys]
    uniq.sort(key=lambda x: x["date"], reverse=True)
    return uniq


def receipts():
    out = []
    for t in load("tx_credits.json")["data"]:
        if t["direction"] == "credit" and t["status"] == "BOOKED":
            out.append({"date": t["date"][:10], "customer": (t.get("participant") or {}).get("name") or "Unknown",
                        "amount": t["amount"], "currency": t["currency"], "reference": t.get("reference") or None,
                        "account": t["account"]["name"]})
    return sorted(out, key=lambda r: r["date"])


def invoices():
    out = []
    for i, r in enumerate(load("invoices.json"), 1):
        out.append({
            "id": r["id"], "payee": r["vendor"], "received_from": SOURCE_LABEL.get(r["source"], r["source"]),
            "due_date": r["due_date"], "reference": r["reference"], "amount": r["total"],
            "currency": r["currency"], "ui_new_payee": True, "bill_to": None, "bank": None,
            "description": r.get("note") or None, "email": None,
            "source": r["source"], "invoice_date": r["invoice_date"], "net": r["net"], "tax": r["tax"],
            "tax_rate": r["rate"], "country": r["country"], "vat_number": r["vat"] or None,
        })
    return out


def main():
    tx = transactions()
    inv = invoices()
    for i in inv:                                        # "new payee" = no payment history under this name
        from checks import same_vendor
        i["ui_new_payee"] = not any(same_vendor(i["payee"], t["vendor"]) for t in tx)
    ctx = {
        "company": "Northstar Labs Ltd (Seapoint staging: Hackathon - Cloud Scare)",
        "as_of": AS_OF,
        "internal_domains": ["northstarlabs.example", "seapoint.co"],
        "accounts": load("accounts.json"),
        "recipients": [],
        "transactions": tx,
        "invoices": inv,
        "pending_payments": load("payments_pending.json"),
        "receipts": receipts(),
        "cashflow": load("monthly_cashflow.json"),
        "pay_from": {"GBP": "HSBC Business Current", "EUR": "Northstar Modulr EUR", "USD": "HSBC Business Current"},
        "source": "seapoint-staging-mcp",
    }
    path = os.path.join(HERE, "fixtures_mcp.json")
    with open(path, "w") as f:
        json.dump(ctx, f, indent=1)
    print(f"wrote {path}: {len(inv)} invoices, {len(tx)} debit transactions, {len(ctx['receipts'])} receipts")


if __name__ == "__main__":
    main()
