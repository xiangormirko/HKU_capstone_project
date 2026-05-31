"""
CosmoTrade Intelligence backend.

Routes
  GET  /            -> the dashboard (index.html)
  GET  /api/data    -> full precomputed dashboard payload (real Comtrade data)
  POST /api/chat    -> Trade Analyst AI: a real Claude agent with TOOLS that
                       query the live trade dataset, then writes generative analysis.

Run:
  export ANTHROPIC_API_KEY=sk-ant-...        # required for the AI panel
  python server.py                            # http://localhost:8600
"""

import os
import json
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory

from analytics import get_data

HERE = Path(__file__).parent
MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")

app = Flask(__name__)

# ───────────────────────── static + data ─────────────────────────
@app.route("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.route("/app.js")
def app_js():
    return send_from_directory(HERE, "app.js", mimetype="application/javascript")


@app.route("/api/data")
def api_data():
    return jsonify(get_data().build_payload(request.args.get("year")))


# ───────────────────────── agent tools ───────────────────────────
# Each tool maps to an analytics function. Claude calls these to get REAL
# numbers; it never invents figures.
TOOLS = [
    {
        "name": "list_available",
        "description": "List the years, regions, and top countries available in the HS 3304 dataset. Call this first if unsure what data exists.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "top_countries",
        "description": "Ranked top exporting or importing countries for a year, with value (USD), global share %, and year-over-year growth %.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flow": {"type": "string", "enum": ["export", "import"]},
                "year": {"type": "integer", "description": "Optional; defaults to latest year."},
                "n": {"type": "integer", "description": "How many to return (default 10)."},
            },
            "required": ["flow"],
        },
    },
    {
        "name": "country_profile",
        "description": "Exports, imports, trade balance, world ranks and YoY growth for one country in a given year.",
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string"},
                "year": {"type": "integer", "description": "Optional; defaults to latest."},
            },
            "required": ["country"],
        },
    },
    {
        "name": "country_trend",
        "description": "Yearly time series (USD billions) and CAGR of a country's exports or imports across all available years.",
        "input_schema": {
            "type": "object",
            "properties": {
                "country": {"type": "string"},
                "flow": {"type": "string", "enum": ["export", "import"]},
            },
            "required": ["country", "flow"],
        },
    },
    {
        "name": "trade_corridors",
        "description": "Top bilateral exporter->importer corridors by value (USD billions). Optionally filter by exporter and/or importer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer"},
                "exporter": {"type": "string"},
                "importer": {"type": "string"},
            },
        },
    },
    {
        "name": "region_breakdown",
        "description": "Cosmetics exports by world region for a year, with each region's multi-year CAGR.",
        "input_schema": {
            "type": "object",
            "properties": {"year": {"type": "integer"}},
        },
    },
]


def run_tool(name, args):
    d = get_data()
    try:
        if name == "list_available":
            return {"years": d.years, "latest_year": d.latest,
                    "regions": [r["region"] for r in d.region_breakdown()],
                    "top_exporters": [r["country"] for r in d.top("export", n=15)],
                    "top_importers": [r["country"] for r in d.top("import", n=15)]}
        if name == "top_countries":
            return d.top(args["flow"], args.get("year"), args.get("n", 10))
        if name == "country_profile":
            return d.country_profile(args["country"], args.get("year"))
        if name == "country_trend":
            return d.trend(args["country"], args["flow"])
        if name == "trade_corridors":
            return d.corridors(args.get("n", 15), args.get("exporter"), args.get("importer"))
        if name == "region_breakdown":
            return d.region_breakdown(args.get("year"))
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    return {"error": f"unknown tool {name}"}


SYSTEM = """You are the Trade Analyst AI for CosmoTrade Intelligence, an analytics platform for HS 3304 (beauty & make-up preparations) global trade.

Your data is REAL official UN Comtrade customs statistics. You MUST use the provided tools to obtain any figure — never guess or recall numbers from memory. If a tool returns no data for a request, say so plainly.

Audience: e-commerce operators and brands deciding where to source and sell cosmetics. Give sharp, decision-useful analysis: who exports/imports most, growth trends, trade gaps, and concrete market opportunities. When relevant, translate figures into a recommendation.

Formatting: reply in concise HTML fragments (no markdown, no <html> wrapper). Use <strong> for emphasis, <br> for line breaks, and <ul><li> for lists. Keep it tight — a short paragraph plus a few bullets. Always ground claims in the specific numbers you retrieved. Note that figures are USD and the most recent fully-reported year may lag the current calendar year."""


@app.route("/api/chat", methods=["POST"])
def api_chat():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({
            "needs_key": True,
            "reply": ("<strong>The AI analyst isn't connected yet.</strong><br>"
                      "Set your Anthropic API key and restart the server:<br>"
                      "<code>export ANTHROPIC_API_KEY=sk-ant-...</code><br><br>"
                      "Everything else on the dashboard is live on real UN Comtrade data.")
        })

    body = request.get_json(force=True)
    history = body.get("messages", [])  # [{role, content}] with plain-text content

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    tool_trace = []

    try:
        for _ in range(6):  # tool-use loop
            resp = client.messages.create(
                model=MODEL, max_tokens=1100, system=SYSTEM,
                tools=TOOLS, messages=messages,
            )
            if resp.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        out = run_tool(block.name, block.input or {})
                        tool_trace.append({"tool": block.name, "input": block.input})
                        results.append({
                            "type": "tool_result", "tool_use_id": block.id,
                            "content": json.dumps(out, default=str),
                        })
                messages.append({"role": "user", "content": results})
                continue
            # final answer
            text = "".join(b.text for b in resp.content if b.type == "text")
            return jsonify({"reply": text.strip(), "tools_used": tool_trace})
        return jsonify({"reply": "I gathered the data but ran out of analysis steps — please ask again more specifically.",
                        "tools_used": tool_trace})
    except anthropic.APIError as e:
        return jsonify({"reply": f"<strong>API error:</strong> {e}", "error": True})
    except Exception as e:  # noqa: BLE001
        return jsonify({"reply": f"<strong>Error:</strong> {e}", "error": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8600"))
    print(f"CosmoTrade running on http://localhost:{port}  (model: {MODEL}, "
          f"AI {'ON' if os.environ.get('ANTHROPIC_API_KEY') else 'OFF — set ANTHROPIC_API_KEY'})")
    app.run(host="0.0.0.0", port=port, debug=False)
