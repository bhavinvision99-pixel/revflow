"""Writes demo.html: the approval UI with the proposal baked in, so it opens by double-click
(no server, no API key). Approvals in this version are in-browser dry runs only."""
import json
import os

import chat
from pipeline import build_proposal, load_context

here = os.path.dirname(os.path.abspath(__file__))
html = open(os.path.join(here, "templates", "index.html"), encoding="utf-8").read()
ctx = load_context()
proposal = build_proposal(ctx, use_claude=True)
blob = json.dumps(proposal).replace("</", "<\\/")
canned = json.dumps(chat.canned(ctx, proposal)).replace("</", "<\\/")
out = html.replace("/*__PROPOSAL__*/null", blob).replace("/*__CHAT__*/null", canned)
assert out != html
with open(os.path.join(here, "demo.html"), "w", encoding="utf-8") as f:
    f.write(out)
print("wrote demo.html", f"({proposal['mode']} mode, {len(proposal['items'])} invoices)")
