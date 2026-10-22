# RevFlow

RevFlow is a Seapoint FinOps hackathon prototype for accounts payable, accounts receivable and cash forecasting. For payables it reads the invoice inbox, runs deterministic checks, asks
Claude to review each invoice, and proposes a payment run that a human approves.

```
Seapoint MCP data -> gather -> rule checks (code) -> Claude review -> proposal JSON -> approval gate -> execute -> audit log
```

## Run it

```bash
pip install flask anthropic
export ANTHROPIC_API_KEY=sk-ant-...      # optional: without it the review step is rules-only
python3 app.py                           # http://localhost:5000
python3 test_agent.py                    # 35 checks on the UI fixtures, no API key needed
python3 test_mcp_data.py                 # checks against the Seapoint staging MCP data
python3 test_chat.py                     # chat tests (scripted fake Claude, no key)
python3 from_mcp.py                      # rebuild data/fixtures_mcp.json from data/mcp_raw/
python3 export_static.py                 # rebuilds demo.html (double-click, no server)
```

`AP_MODEL` overrides the model (default `claude-sonnet-5-5`).

## Data

`pipeline.load_context()` uses `data/fixtures_mcp.json` when it exists (override with `AP_DATA=path`), else the
older UI-reconstructed `data/fixtures.json`. The MCP file is built by `from_mcp.py` from read-only query results
saved in `data/mcp_raw/` (invoices, accounts, transactions, queued payments) from org "Hackathon - Cloud Scare".

## Ask Claude (chat)

The "Ask Claude" button opens a chat that answers questions about invoices, payment history, customers and the forecast.
`chat.py` gives Claude six read-only tools over the loaded snapshot (`list_invoices`, `explain_invoice`, `party_payments`,
`customers`, `forecast`, `monthly_cashflow`); it cannot approve, pay, email or change anything. With `ANTHROPIC_API_KEY`
set, Claude answers with those tools; without a key (or if the call fails) a keyword router answers common questions from
the same tools. `demo.html` carries precomputed answers for the suggested questions only. `python3 test_chat.py` runs the
tests with a scripted fake Claude. The Claude path has not been run against the real API.

## Cash forecast

`forecast.py` (no AI, plain arithmetic) follows Seapoint's runway methodology: cash today (banks + treasury), net burn
(last month or 3-month average), runway, cash-zero date, a 13-week projection, a stress line that also pays every held
invoice, and a per-account check that the approved run does not overdraw anything. Monthly spend and income come from
`data/mcp_raw/monthly_cashflow.json`. Approximations: refunds and the Capital Investments carve-out are not split out,
only BOOKED rows are counted, and USD uses an assumed 0.76 rate.

## Money in

`receivables.py` reads the 54 customer receipts in the MCP data, finds each customer's payment cycle, flags a regular
payer that missed its usual date (Cormorant, due 18 Oct, whose payments have also fallen five times in a row), and
produces expected receipts that feed the forecast. The MCP does not expose invoices issued to customers, so there are
no customer invoice due dates or overdue balances.

## What it catches in the MCP data

| Invoice | Finding |
|---|---|
| Snowflake £21,800 (x2) | Already paid 11 Oct; the forwarded copy is a duplicate. Mark paid + reject duplicate. |
| Clearview £3,400 (x2) | Same invoice via scan and upload; a payment for it is already queued in Seapoint. Hold the primary, reject the copy. |
| Lodgewood £6,300, Sentry £2,800, Meridian Insurance £1,240 | Already paid. |
| Connolly £1,800 | Unmatched £1,800 payment on 12 Oct may already cover it. Held. |
| Slack, Northwind x2, Nordhaus | Unmatched earlier payments of the same amount; held for a human to confirm. |
| Remote People £33,600 | VAT is 0.6% of net but the invoice says 20%. Held. |
| Meridian Translations | NL VAT number but vendor country GB. Held. |
| WeWork £2,950 | Above its historic £2,200 to £2,350 range. Held. |
| Halberd £4,250 | First-time payee above the £2,000 policy limit. Held. |

## How the safety works

- Claude only recommends. Nothing is paid until a person approves, and `executor.execute()` re-checks every
  approval server-side: held items cannot be approved by any request.
- Guardrail in `review.py`: Claude may make a decision *stricter* than the rules, never looser
  (a `block` flag can never end as `pay`). Overrides are shown in the UI.
- Invoice emails/descriptions are passed to Claude inside `<invoice_data>` and treated as untrusted data.
- The default executor is a dry run. `AP_LIVE=1` selects `SeapointMCPExecutor`, which is a stub.

## What is NOT done yet (start here)

1. **Live data.** The MCP is attached to a Claude session, not to this Python app, so `data/mcp_raw/` is a
   snapshot (as of 20 Oct 2026). Page 2 of the vendor history was transcribed by hand
   (`tx_vendors_p2_compact.json`). The MCP does not expose sender email, invoice bank details or saved payee
   bank details, so `bank_details_changed` and the sender-based forward check cannot fire on this data.
   Not pulled: 4 oldest transactions of the "other vendors" query.
2. **Real payments.** The MCP has no pay-invoice tool (`query_payments` is read-only; writes are bookkeeping only).
   `SeapointMCPExecutor` is still a stub, so approvals are a dry run plus an audit log.
3. **Claude path is tested with a mock only** (no API key was available while building). Run it once with a
   real key and check a few summaries read well.
4. Policy numbers in `checks.POLICY` (new-payee threshold, 10-day window) are guesses. Your finance
   person should set them.
5. EUR and USD amounts are compared against the £ threshold 1:1 and USD has no FX conversion.

## Files

`checks.py` rules · `review.py` Claude step + guardrails · `pipeline.py` orchestration + cash check ·
`executor.py` approvals, dry run, audit log · `app.py` + `templates/index.html` UI ·
`build_fixtures.py` how the fixtures were made · `test_agent.py` tests
