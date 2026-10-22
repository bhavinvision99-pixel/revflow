"""RevFlow: approval UI.  Run:  python3 app.py   then open http://localhost:5000
Set ANTHROPIC_API_KEY to use Claude for the review step (otherwise rules-only)."""
import os

from flask import Flask, jsonify, request, send_from_directory

import chat
from executor import execute, read_audit
from pipeline import build_proposal, load_context

app = Flask(__name__)
_cache = {}


def proposal(refresh=False):
    if refresh or "p" not in _cache:
        _cache["ctx"] = load_context()
        _cache["p"] = build_proposal(_cache["ctx"], use_claude=True)
    return _cache["p"]


@app.get("/")
def index():
    html = open(os.path.join(app.root_path, "templates", "index.html"), encoding="utf-8").read()
    return html.replace("/*__PROPOSAL__*/null", "null").replace("/*__CHAT__*/null", "null")


@app.get("/api/proposal")
def api_proposal():
    return jsonify(proposal(refresh=request.args.get("refresh") == "1"))


@app.post("/api/execute")
def api_execute():
    ids = (request.get_json(silent=True) or {}).get("approved", [])
    if not isinstance(ids, list):
        return jsonify({"error": "approved must be a list"}), 400
    return jsonify({"results": execute(proposal(), [str(i) for i in ids])})


@app.post("/api/chat")
def api_chat():
    body = request.get_json(silent=True) or {}
    q = body.get("question", "")
    hist = [m for m in body.get("history", []) if isinstance(m, dict) and isinstance(m.get("content"), str)]
    p = proposal()
    return jsonify(chat.answer(_cache["ctx"], p, q, hist))


@app.get("/api/audit")
def api_audit():
    return jsonify(read_audit())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
