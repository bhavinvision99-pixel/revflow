"""Deterministic invoice checks. No AI here: every flag is testable and explainable.

Severity:
  block  - do not pay as-is (already paid, duplicate, changed bank details)
  review - a human should look before paying
  info   - worth knowing, does not change the action
"""
import re
from datetime import date, timedelta
from statistics import mean

POLICY = {
    "new_payee_review_above": 2000.0,   # first-time payees above this are held for verification
    "already_paid_window_days": 10,     # payment within +/- N days of due date counts as a match
    "amount_tolerance": 0.005,          # 0.5%
    "unallocated_lookback_days": 30,
    "history_min_points": 6,
    "history_high_multiple": 1.25,      # flag if invoice > 1.25x historic max
    "history_low_multiple": 0.5,        # flag if invoice < 0.5x historic min
}

SUFFIXES = {"ltd", "limited", "llp", "pbc", "bv", "inc", "plc", "llc", "gmbh", "the"}
ALIASES = {"aws": "amazon web services"}
SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$"}


def money(amount, ccy="GBP"):
    return f"{SYMBOL.get(ccy, ccy + ' ')}{amount:,.2f}"


def tokens(name):
    n = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    n = ALIASES.get(n.strip(), n)
    return {t for t in n.split() if t not in SUFFIXES}


def same_vendor(a, b):
    """Name variants match when the shorter token set is contained in the longer one,
    so 'Snowflake Computing UK Ltd' matches 'Snowflake', but 'Meridian Insurance
    Brokers' does not match 'Meridian Translations'."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


def d(s):
    return date.fromisoformat(s[:10])


def flag(code, severity, message, **evidence):
    return {"code": code, "severity": severity, "message": message, "evidence": evidence}


def is_internal(sender, ctx):
    return any(sender.lower().endswith("@" + dom) for dom in ctx["internal_domains"])


def vendor_txns(inv, ctx):
    return [t for t in ctx["transactions"] if same_vendor(inv["payee"], t["vendor"])]


def amounts_close(a, b):
    return abs(a - b) <= max(0.01, POLICY["amount_tolerance"] * max(a, b))


# --- individual checks ---------------------------------------------------------------

def check_duplicate_invoice(inv, ctx):
    group = [o for o in ctx["invoices"]
             if o["id"] != inv["id"] and same_vendor(o["payee"], inv["payee"])
             and (o["reference"] == inv["reference"]
                  or (amounts_close(o["amount"], inv["amount"]) and o["due_date"] == inv["due_date"]
                      and o["currency"] == inv["currency"]))]
    if not group:
        return []
    members = group + [inv]
    # primary = a non-internal sender first, then earliest id
    primary = sorted(members, key=lambda o: (is_internal(o["received_from"], ctx), o["id"]))[0]
    if primary["id"] == inv["id"]:
        return [flag("duplicate_source", "info",
                     f"Same invoice also arrived as {', '.join(o['id'] for o in group)}; this is the primary copy.",
                     copies=[o["id"] for o in group])]
    how = "forwarded internally" if is_internal(inv["received_from"], ctx) else "received again"
    return [flag("duplicate_invoice", "block",
                 f"Same vendor and reference ({inv['reference']}) as the copy that came in via {primary['received_from']}; "
                 f"this one was {how} via {inv['received_from']}.", primary=primary["id"])]


def check_already_paid(inv, ctx):
    win = timedelta(days=POLICY["already_paid_window_days"])
    due = d(inv["due_date"])
    hits = []
    for t in vendor_txns(inv, ctx):
        if t["currency"] != inv["currency"] or not amounts_close(t["amount"], inv["amount"]):
            continue
        if t.get("matched_invoice") and t["matched_invoice"] != inv["reference"]:
            continue
        if abs(d(t["date"]) - due) <= win:
            hits.append(t)
    if not hits:
        return []
    t = max(hits, key=lambda x: x["date"])
    src = f" {t['account']}" if t["account"] != "unknown" else ""
    return [flag("already_paid", "block",
                 f"A payment of {money(t['amount'], t['currency'])} to this vendor already left"
                 f"{src} on {t['date']}, within {POLICY['already_paid_window_days']} days of the due date "
                 f"({inv['due_date']}).", transaction=t)]


def check_unallocated_payment(inv, ctx):
    lb = timedelta(days=POLICY["unallocated_lookback_days"])
    due = d(inv["due_date"])
    win = timedelta(days=POLICY["already_paid_window_days"])
    hits = [t for t in vendor_txns(inv, ctx)
            if t["currency"] == inv["currency"] and amounts_close(t["amount"], inv["amount"])
            and not t.get("matched_invoice")
            and timedelta(0) <= due - d(t["date"]) <= lb and abs(d(t["date"]) - due) > win]
    if not hits:
        return []
    t = max(hits, key=lambda x: x["date"])
    return [flag("unallocated_payment", "review",
                 f"An unmatched {money(t['amount'], t['currency'])} payment to this vendor on {t['date']} "
                 f"is not tied to any invoice and may already cover this one (or be a duplicate payment).",
                 transaction=t)]


def check_duplicate_payments(inv, ctx):
    """Two identical payments to the same vendor on the same day (money already out)."""
    seen = {}
    for t in vendor_txns(inv, ctx):
        seen.setdefault((t["date"], round(t["amount"], 2)), []).append(t)
    out = []
    for (day, amt), ts in seen.items():
        if len(ts) > 1 and (date.fromisoformat(ctx["as_of"]) - d(day)).days <= 30:
            out.append(flag("duplicate_payment", "info",
                            f"{len(ts)} identical payments of {money(amt)} went to this vendor on {day}; "
                            f"one may be refundable.", date=day, amount=amt))
    return out


def check_bank_details(inv, ctx):
    bank = inv.get("bank")
    if not bank:
        return []
    for r in ctx["recipients"]:
        if same_vendor(r["name"], inv["payee"]) and r.get("account"):
            if r["account"] != bank["account"] or r["sort_code"] != bank["sort_code"]:
                return [flag("bank_details_changed", "block",
                             f"Invoice bank details ({bank['bank']} {bank['sort_code']} / {bank['account']}) differ from the "
                             f"saved recipient ({r['sort_code']} / {r['account']}). Classic payment-redirection pattern.",
                             invoice_bank=bank, saved_recipient=r)]
            return []
    return []


def check_payee_status(inv, ctx):
    in_recipients = any(same_vendor(r["name"], inv["payee"]) for r in ctx["recipients"])
    has_history = bool(vendor_txns(inv, ctx))
    out = []
    if in_recipients or has_history or not inv["ui_new_payee"]:
        if inv["ui_new_payee"]:
            out.append(flag("name_variant", "info",
                            "Inbox marks this payee as new, but the vendor has payment history or a saved recipient "
                            "under a name variant.", in_recipients=in_recipients, has_history=has_history))
        return out
    if inv["amount"] >= POLICY["new_payee_review_above"]:
        out.append(flag("new_payee_large", "review",
                        f"First-time payee with no history and an invoice of {money(inv['amount'], inv['currency'])} "
                        f"(policy: verify new payees above {money(POLICY['new_payee_review_above'])})."))
    else:
        out.append(flag("new_payee", "info", "First payment to this payee; no history to compare against."))
    return out


def check_amount_vs_history(inv, ctx):
    hist = [t["amount"] for t in vendor_txns(inv, ctx) if t["currency"] == inv["currency"]]
    if len(hist) < POLICY["history_min_points"]:
        return []
    hi, lo = max(hist), min(hist)
    if inv["amount"] > hi * POLICY["history_high_multiple"] or inv["amount"] < lo * POLICY["history_low_multiple"]:
        return [flag("amount_anomaly", "review",
                     f"{money(inv['amount'], inv['currency'])} is outside this vendor's historic range "
                     f"({money(lo)} to {money(hi)}, {len(hist)} payments).", low=lo, high=hi, mean=round(mean(hist), 2))]
    return []


def check_fx(inv, ctx):
    if inv["currency"] != "GBP":
        return [flag("fx", "info", f"{inv['currency']} invoice: confirm the FX rate/fees when paying.",
                     currency=inv["currency"])]
    return []


def check_internal_forward(inv, ctx):
    if is_internal(inv["received_from"], ctx):
        return [flag("internal_forward", "info",
                     f"Arrived via an internal forward from {inv['received_from']}, not directly from the vendor.")]
    return []


def check_payment_queued(inv, ctx):
    """A payment for this invoice already exists in Seapoint but has not been sent (draft / awaiting approval)."""
    for p in ctx.get("pending_payments", []):
        if p.get("reference") == inv["reference"] and same_vendor(p["payee"], inv["payee"]):
            return [flag("payment_queued", "review",
                         f"A {money(p['amount'], p['currency'])} payment for this invoice is already queued in Seapoint "
                         f"(status: {p['status']}). Approve that one instead of creating another.", payment=p)]
    return []


def check_vat_rate(inv, ctx):
    """Stated VAT rate vs what the amounts imply (catches a mistyped or manipulated invoice)."""
    if inv.get("net") is None or not inv["net"] or not inv.get("tax_rate"):
        return []
    implied = inv["tax"] / inv["net"] * 100
    if abs(implied - inv["tax_rate"]) > 1.0:
        return [flag("vat_rate_mismatch", "review",
                     f"VAT of {money(inv['tax'], inv['currency'])} on {money(inv['net'], inv['currency'])} net is "
                     f"{implied:.1f}%, but the invoice states {inv['tax_rate']:.0f}%.", implied=round(implied, 2))]
    return []


def check_vat_country(inv, ctx):
    """VAT-number country prefix differs from the vendor's country."""
    vat = (inv.get("vat_number") or "").strip()
    if len(vat) < 2 or not inv.get("country") or not vat[:2].isalpha():
        return []
    if vat[:2].upper() != inv["country"].upper():
        return [flag("vat_country_mismatch", "review",
                     f"VAT number {vat} is a {vat[:2].upper()} registration but the vendor country is {inv['country']}: "
                     f"check the payee's identity and the VAT treatment.", vat=vat, country=inv["country"])]
    return []


CHECKS = [check_duplicate_invoice, check_already_paid, check_unallocated_payment, check_duplicate_payments,
          check_bank_details, check_payment_queued, check_vat_rate, check_vat_country, check_payee_status, check_amount_vs_history, check_fx, check_internal_forward]


def run_checks(inv, ctx):
    flags = []
    for fn in CHECKS:
        flags.extend(fn(inv, ctx))
    return flags


def rule_action(flags, inv):
    """Map flags to a recommended action. Returns (action, short_reason)."""
    codes = {f["code"] for f in flags}
    if "duplicate_invoice" in codes:
        return "reject_duplicate", "Duplicate copy of another invoice."
    if "bank_details_changed" in codes:
        return "hold", "Bank details changed: verify with the vendor on a known number before paying."
    if "already_paid" in codes:
        return "mark_paid", "Already paid: reconcile instead of paying again."
    if "unallocated_payment" in codes:
        return "hold", "A matching unallocated payment exists: confirm before paying."
    if "payment_queued" in codes:
        return "hold", "Already queued in Seapoint: approve the existing payment, do not create another."
    if codes & {"new_payee_large", "amount_anomaly", "vat_rate_mismatch", "vat_country_mismatch"}:
        return "hold", "Needs verification before payment."
    return "pay", "No blocking or review flags."
