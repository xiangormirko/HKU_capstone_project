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
from social import get_social
from fusion import get_fusion

HERE = Path(__file__).parent
MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")

app = Flask(__name__)

# ───────────────────────── static + data ─────────────────────────
@app.route("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.route("/<path:fname>.js")
def serve_js(fname):
    return send_from_directory(HERE, f"{fname}.js", mimetype="application/javascript")


@app.route("/api/data")
def api_data():
    return jsonify(get_data().build_payload(request.args.get("year")))


# ───────── Social discovery (Reddit + future sources) ─────────
@app.route("/api/social/overview")
def api_social_overview():
    return jsonify(get_social().overview())


@app.route("/api/social/search")
def api_social_search():
    q = request.args.get("q", "")
    limit = int(request.args.get("limit", "25"))
    return jsonify(get_social().search(q, limit))


# ───────── Source-to-Sell fusion (trade x social) ─────────
@app.route("/api/fusion")
def api_fusion():
    return jsonify(get_fusion().payload())


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
    # ---- Social discovery tools (Reddit posts + comments) ----
    {
        "name": "social_search",
        "description": "Search social posts (Reddit skincare communities) for a need or product category like 'oily skin remover' or 'retinol for wrinkles'. Returns the products & ingredients people mention, overall consumer sentiment (VADER), and sample posts. Use this to connect demand/sentiment signals to trade data.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "social_overview",
        "description": "Overview of the social dataset: most-discussed product categories, brands and ingredients, each with consumer sentiment. Good for 'what are people talking about / what brands are buzzing'.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "product_sentiment",
        "description": "Consumer sentiment for a specific brand, ingredient, or category (e.g. 'CeraVe', 'niacinamide', 'sunscreen') from social posts: mention volume, #posts, and average VADER sentiment.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "source_to_sell",
        "description": "The fusion of TRADE + SOCIAL: 'Source-to-Sell' opportunities. Returns where to SOURCE (origin countries whose brands have social love, scored vs their cosmetics export strength), where to SELL (net-importer countries with unmet demand), and per-category source->sell routes. Use for 'where should I source/sell X' or any trade+social strategy question.",
        "input_schema": {"type": "object", "properties": {}},
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
        if name == "social_search":
            return get_social().agent_search(args["query"])
        if name == "social_overview":
            return get_social().agent_overview()
        if name == "product_sentiment":
            return get_social().product_sentiment(args["name"])
        if name == "source_to_sell":
            return get_fusion().payload()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    return {"error": f"unknown tool {name}"}


SYSTEM = """You are the Product Scout AI, an analyst for cosmetics e-commerce that sees TWO real datasets:

1. TRADE — official UN Comtrade customs statistics for HS 3304 (beauty & make-up preparations): country exports/imports, growth, corridors, regions. Tools: top_countries, country_profile, country_trend, trade_corridors, region_breakdown, list_available.
2. SOCIAL — real consumer conversations (Reddit skincare communities): which products/ingredients people discuss and how they FEEL about them (VADER sentiment). Tools: social_search, social_overview, product_sentiment.

You MUST use tools to obtain any figure — never guess or recall numbers from memory. If a tool returns nothing, say so plainly.

Your edge is CONNECTING the two: e.g. a country/category growing in trade AND rising in social sentiment is a strong signal; high demand/sentiment with weak local supply is an export opportunity. When a question spans both, call tools from both domains and synthesize. The `source_to_sell` tool gives a ready-made fusion (where to source by brand-origin export strength, where to sell by net-import demand) — use it for sourcing/selling strategy questions. For purely-trade or purely-social questions, just use the relevant tools.

Audience: e-commerce operators and brands deciding what to sell and where to source/sell. Be sharp and decision-useful; translate numbers into a recommendation.

Formatting: concise HTML fragments (no markdown, no <html> wrapper). Use <strong>, <br>, and <ul><li>. Keep it tight — a short paragraph plus a few bullets. Ground every claim in retrieved numbers. Trade figures are USD; the latest fully-reported trade year may lag the calendar year. Social sentiment ranges -1 (very negative) to +1 (very positive)."""


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
