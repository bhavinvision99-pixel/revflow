"""Executes human-approved decisions. Claude never reaches this code: payments only
happen after a person approves in the UI, and the server re-checks every approval
against the proposal (a held or blocked invoice can never be paid)."""
import json
import os
from datetime import datetime, timezone

from checks import money

AUDIT = os.path.join(os.path.dirname(__file__), "data", "audit.jsonl")

# What each proposed action may be approved as. 'hold' items cannot be approved at all.
APPROVABLE = {"pay": "pay", "mark_paid": "mark_paid", "reject_duplicate": "reject"}


class DryRunExecutor:
    """Default. Logs what it *would* do; moves no money."""

    def pay(self, item):
        return f"Would pay {money(item['amount'], item['currency'])} to {item['payee']} (ref {item['reference']}) from {item.get('pay_from')}."

    def mark_paid(self, item):
        return f"Would reject {item['reference']}: already paid, so it is matched to the existing payment and not paid again."

    def reject(self, item):
        return f"Would reject {item['reference']} as a duplicate; the original invoice is kept."


class SeapointMCPExecutor(DryRunExecutor):
    """TODO: call the Seapoint MCP payment tools here once their names/params are known.
    Keep it behind an explicit flag (AP_LIVE=1) and keep approvals server-side."""

    def pay(self, item):
        raise NotImplementedError("Wire this to the Seapoint MCP 'pay invoice' tool.")


def get_executor():
    return SeapointMCPExecutor() if os.environ.get("AP_LIVE") == "1" else DryRunExecutor()


def execute(proposal, approved_ids, approver="demo-user", executor=None, audit_path=AUDIT):
    executor = executor or get_executor()
    by_id = {i["id"]: i for i in proposal["items"]}
    results = []
    for iid in approved_ids:
        item = by_id.get(iid)
        if item is None:
            results.append({"id": iid, "status": "rejected_request", "message": "Unknown invoice."})
            continue
        kind = APPROVABLE.get(item["action"])
        if kind is None:
            results.append({"id": iid, "status": "refused",
                            "message": f"{item['payee']} is on hold; it needs a human to resolve it first."})
            continue
        try:
            msg = getattr(executor, kind)(item)
            status = "dry_run" if isinstance(executor, DryRunExecutor) and not isinstance(executor, SeapointMCPExecutor) else "done"
        except Exception as e:
            msg, status = f"{type(e).__name__}: {e}", "error"
        results.append({"id": iid, "status": status, "action": kind, "message": msg})
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "invoice": iid,
                 "payee": item["payee"], "reference": item["reference"], "amount": item["amount"],
                 "currency": item["currency"], "proposed": item["action"], "approved_as": kind,
                 "approver": approver, "reviewed_by": item["reviewed_by"], "summary": item["summary"],
                 "status": status}
        os.makedirs(os.path.dirname(audit_path), exist_ok=True)
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    return results


def read_audit(path=AUDIT, limit=50):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        rows = [json.loads(l) for l in f if l.strip()]
    return rows[-limit:][::-1]
