"""Builds data/fixtures.json from what was observed in the Seapoint hackathon sandbox UI.

These fixtures stand in for Seapoint MCP calls so the agent can be developed and
tested offline. Swap `FixtureSource` in sources.py for an MCP-backed source once the
real tool names are known.

Caveats (kept honest on purpose):
- Only 20 of the 25 outstanding invoices were visible when this was captured.
- Transaction history is itemised only for vendors we inspected (Snowflake,
  Lodgewood, Fathom, Connolly, plus a few single payments). Older history dates are
  approximate (same day-of-month as the observed pattern).
- Invoice bank details are only known where an invoice PDF was opened.
"""
import json
from datetime import date

TODAY = date(2026, 10, 20)


def monthly(vendor, day, amounts, start=(2025, 8), account="Seapoint (GBP)", ccy="GBP", category=""):
    out, y, m = [], start[0], start[1]
    for amt in amounts:
        out.append({"date": date(y, m, day).isoformat(), "vendor": vendor, "amount": amt,
                    "currency": ccy, "account": account, "category": category, "matched_invoice": None})
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


transactions = []
transactions += monthly("Snowflake", 11, [21800.0] * 15, category="Hosting & Infrastructure")
transactions += monthly("Lodgewood Travel", 9,
                        [6300, 11700, 10800, 9900, 9000, 8100, 7200, 6300, 11700, 10800, 9900, 9000, 8100, 7200, 6300],
                        account="Revolut (GBP)", category="Travel & Entertainment")
transactions += monthly("Fathom Talent Partners", 17,
                        [7400, 9800, 12200, 14600, 8600, 11000, 13400, 7400, 9800, 12200, 14600, 8600, 11000, 13400],
                        category="Payroll & Benefits")
# Connolly: monthly £1,800 on ~12th, with two payments on 12 Oct 2026 (one matched to AUG-001, one not)
connolly = monthly("Connolly Accountants", 12, [1800.0] * 15, account="HSBC UK Business (GBP)",
                   category="Legal & Professional Fees")
transactions += connolly[:-1]  # Aug 2025 .. Sep 2026 (14 payments); Oct 2026 added below as two rows -> 16 total
transactions += [
    {"date": "2026-10-12", "vendor": "Connolly Accountants", "amount": 1800.0, "currency": "GBP",
     "account": "HSBC UK Business (GBP)", "category": "Legal & Professional Fees", "matched_invoice": "AUG-001"},
    {"date": "2026-10-12", "vendor": "Connolly Accountants", "amount": 1800.0, "currency": "GBP",
     "account": "HSBC UK Business (GBP)", "category": "Legal & Professional Fees", "matched_invoice": None},
]
transactions += [
    {"date": "2026-09-23", "vendor": "Meridian Insurance Brokers", "amount": 1240.0, "currency": "GBP",
     "account": "unknown", "category": "Insurance", "matched_invoice": None},
    {"date": "2026-10-05", "vendor": "Slack Technologies", "amount": 486.0, "currency": "GBP",
     "account": "Seapoint (GBP)", "category": "Subscriptions", "matched_invoice": "SLK-6612"},
    {"date": "2026-10-11", "vendor": "Amazon Web Services", "amount": 6850.42, "currency": "GBP",
     "account": "HSBC UK Business (GBP)", "category": "Hosting & Infrastructure", "matched_invoice": "AWS-INV-44821"},
]
transactions.sort(key=lambda t: t["date"])

H = "Seapoint Demo Ltd"
N = "Northstar Labs Ltd"


def inv(i, payee, sender, due, ref, amount, ccy="GBP", new=True, bill_to=None, bank=None,
        desc=None, email=None):
    return {"id": i, "payee": payee, "received_from": sender, "due_date": due, "reference": ref,
            "amount": amount, "currency": ccy, "ui_new_payee": new, "bill_to": bill_to,
            "bank": bank, "description": desc, "email": email}


invoices = [
    inv("inv-01", "Harbourline Logistics Ltd", "accounts@harbourline.example", "2026-09-15", "HL-76890", 540.00),
    inv("inv-02", "Meridian Insurance Brokers Ltd", "renewals@meridian-brokers.example", "2026-09-23", "MIB-2026-330", 1240.00),
    inv("inv-03", "Sentry", "billing@sentry.example", "2026-10-05", "SEN-2026-10-4471", 2800.00),
    inv("inv-04", "Northwind Facilities", "accounts@northwind-facilities.example", "2026-10-07", "NW-88431", 975.00,
        new=False, bill_to=H, desc="Office cleaning — August",
        bank={"bank": "NatWest", "sort_code": "60-16-13", "account": "19338204"}),
    inv("inv-05", "Lodgewood Travel Ltd", "accounts@lodgewood.example", "2026-10-09", "LWT-55120", 6300.00),
    inv("inv-06", "Anthropic, PBC", "billing@anthropic.example", "2026-10-10", "ANT-INV-2026-09-0412", 1385.20,
        ccy="USD", new=False),
    inv("inv-07", "Harrison & Webb Solicitors LLP", "accounts@harrisonwebb.example", "2026-10-13", "HW-2026-117", 2750.00),
    inv("inv-08", "Northwind Facilities Ltd", "billing@northwind-facilities.example", "2026-10-14", "NW-88690", 975.00,
        bill_to=N, desc="Office cleaning — September",
        bank={"bank": "Santander", "sort_code": "09-01-28", "account": "36651902"}),
    inv("inv-09", "Snowflake Computing UK Ltd", "priya.chandra@northstarlabs.example", "2026-10-15", "SNF-INV-2026-10", 21800.00,
        bill_to=N, desc="Enterprise capacity commitment — October 2026",
        bank={"bank": "HSBC UK", "sort_code": "40-11-62", "account": "71830462"},
        email={"subject": "Fwd: Invoice SNF-INV-2026-10 from Snowflake", "received": "2026-10-02T09:41",
               "body": "Forwarding this one for payment. ---------- Forwarded message ---------- Your invoice SNF-INV-2026-10 for October is attached."}),
    inv("inv-10", "Snowflake Computing UK Ltd", "billing@snowflake.example", "2026-10-15", "SNF-INV-2026-10", 21800.00,
        bill_to=N, desc="Enterprise capacity commitment — October 2026",
        bank={"bank": "HSBC UK", "sort_code": "40-11-62", "account": "71830462"},
        email={"subject": "Invoice SNF-INV-2026-10 from Snowflake", "received": "2026-10-02T09:41",
               "body": "Hello, Your invoice SNF-INV-2026-10 for October is attached. Snowflake Billing"}),
    inv("inv-11", "Nordhaus Studio BV", "facturen@nordhaus.example", "2026-10-19", "NHS-2026-0142", 9000.00, ccy="EUR"),
    inv("inv-12", "PyCon UK Society", "Manually uploaded", "2026-10-20", "PYC-26-1187", 135.00, new=False),
    inv("inv-13", "Fathom Talent Partners Ltd", "accounts@fathomtalent.example", "2026-10-20", "FTP-0931", 14400.00),
    inv("inv-14", "Slack Technologies", "billing@slack.example", "2026-10-23", "SLK-7188", 486.00, new=False),
    inv("inv-15", "Amazon Web Services", "aws-billing@amazon.example", "2026-10-24", "AWS-INV-45190", 7204.20, new=False),
    inv("inv-16", "Harbourline Logistics Ltd", "invoices@harbourline.example", "2026-10-25", "HL-77120", 612.48),
    inv("inv-17", "Remote People Ltd", "billing@remotepeople.example", "2026-10-25", "RP-2026-10-118", 33600.00),
    inv("inv-18", "Connolly Accountants", "accounts@connolly-accountants.example", "2026-10-26", "CA-2026-0918", 1800.00, new=False),
    inv("inv-19", "Meridian Translations BV", "billing@meridiantranslations.example", "2026-11-01", "MT-2026-0442", 1840.00, ccy="EUR"),
    inv("inv-20", "WeWork UK Ltd", "invoices@wework.example", "2026-11-01", "WW-UK-2026-11-4B", 2950.00),
]

recipients = [
    {"name": "WeWork UK Ltd", "account": "60335512", "sort_code": "20-26-08"},
    {"name": "Amazon Web Services", "account": "61554023", "sort_code": "40-02-50"},
    {"name": "Clearview Media", "account": "62119047", "sort_code": "23-14-70"},
    {"name": "Connolly Accountants", "account": "10428189", "sort_code": "20-26-08"},
    {"name": "HubSpot", "account": "20447719", "sort_code": "30-96-26"},
    {"name": "Jane Doyle (Contractor)", "account": "87654321", "sort_code": "04-00-04"},
    {"name": "Marta Nowak (Freelance)", "iban": "DE75 5121 0800 1245 1261 99"},
    {"name": "Northwind Facilities", "account": "19338204", "sort_code": "60-16-13"},
    {"name": "Slack Technologies", "account": "70336618", "sort_code": "20-00-00"},
]

accounts = [
    {"name": "Seapoint (GBP)", "currency": "GBP", "balance": 565400.20},
    {"name": "Seapoint (EUR)", "currency": "EUR", "balance": 168400.75},
    {"name": "Seapoint Treasury (GBP)", "currency": "GBP", "balance": 1200687.46},
    {"name": "HSBC UK Business (GBP)", "currency": "GBP", "balance": 486320.18},
    {"name": "Revolut (GBP)", "currency": "GBP", "balance": 64820.35},
]

fixtures = {
    "company": "Northstar Labs Ltd (Seapoint hackathon sandbox)",
    "as_of": TODAY.isoformat(),
    "internal_domains": ["northstarlabs.example", "seapoint.co"],
    "accounts": accounts,
    "recipients": recipients,
    "transactions": transactions,
    "invoices": invoices,
}

if __name__ == "__main__":
    with open("data/fixtures.json", "w") as f:
        json.dump(fixtures, f, indent=2)
    print(f"{len(invoices)} invoices, {len(transactions)} transactions, {len(recipients)} recipients")
