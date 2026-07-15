"""
Product Scout backend.

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
from dotenv import load_dotenv

from analytics import get_data
from social import get_social
from fusion import get_fusion
from amazon import get_amazon
from trends import get_trends
import skin_types
import home as home_mod
import refresh_manager

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")

app = Flask(__name__)

# Optionally run the recurring-refresh scheduler inside the app process.
if os.environ.get("PS_ENABLE_SCHEDULER") == "1":
    try:
        import scheduler_app
        scheduler_app.start_in_app()
    except Exception as _e:  # noqa: BLE001
        print("Scheduler not started:", _e)

# ───────────────────────── static + data ─────────────────────────
@app.route("/")
def index():
    return send_from_directory(HERE, "index.html")


@app.route("/<path:fname>.js")
def serve_js(fname):
    return send_from_directory(HERE, f"{fname}.js", mimetype="application/javascript")


@app.route("/<path:fname>.svg")
def serve_svg(fname):
    return send_from_directory(HERE, f"{fname}.svg", mimetype="image/svg+xml")


@app.route("/<path:fname>.png")
def serve_png(fname):
    return send_from_directory(HERE, f"{fname}.png", mimetype="image/png")


@app.route("/api/data")
def api_data():
    return jsonify(get_data().build_payload(request.args.get("year")))


@app.route("/api/home")
def api_home():
    """Landing dashboard: blue-ocean whitespace + consumer pain points, live."""
    return jsonify(home_mod.payload())


# ───────── Social discovery (Reddit + future sources) ─────────
@app.route("/api/social/overview")
def api_social_overview():
    ov = get_social().overview()
    ov["freshness"] = refresh_manager.status_for("social")
    return jsonify(ov)


@app.route("/api/social/search")
def api_social_search():
    q = request.args.get("q", "")
    limit = int(request.args.get("limit", "25"))
    return jsonify(get_social().search(q, limit))


@app.route("/api/social/category")
def api_social_category():
    payload = get_social().category_page(request.args.get("name", ""))
    payload["freshness"] = {
        "trends": refresh_manager.status_for("trends"),
        "amazon": refresh_manager.status_for("amazon"),
        "social": refresh_manager.status_for("social"),
    }
    return jsonify(payload)


# ───────── Data freshness + recurring/triggered refresh ─────────
@app.route("/api/freshness")
def api_freshness():
    return jsonify(refresh_manager.status())


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    body = request.get_json(silent=True) or {}
    source = body.get("source") or request.args.get("source", "")
    return jsonify(refresh_manager.trigger(source, body.get("query")))


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
    {
        "name": "amazon_reviews",
        "description": "Amazon review intelligence for a product category ('Sunscreen / SPF', 'Moisturizer & Hydration', or 'Cleanser & Oil Control'). Returns category avg rating, per-product ratings & aspect-level negative rates, the dominant pain points (sourcing opportunities), best-in-class product, and AI summaries. Use for product/quality/what-to-source questions.",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": ["category"],
        },
    },
    {
        "name": "google_trends",
        "description": "Google Trends search-interest for a product category ('Sunscreen / SPF', 'Moisturizer & Hydration', 'Cleanser & Oil Control') in markets HK and JP. Returns the category's trend (rising/stable/declining), 3-month momentum and YoY growth, rising sub-categories, and brand momentum per market. Use for demand-trend / market-timing / which-market questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "country": {"type": "string", "description": "Optional: 'HK' or 'JP'."},
            },
            "required": ["category"],
        },
    },
    {
        "name": "skin_type_segments",
        "description": "US consumer skin-type distribution for OPPORTUNITY SEGMENTATION (Statista Consumer Insights). For each skin type (Normal, Dry, Sensitive, Oily, Combination, redness/dark-circles/allergy-prone) returns the approx % of US adults claiming it, the male vs female split (gender skew for targeting), and the linked product category. Use to size an addressable segment and decide who to target.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def run_tool(name, args):
    d = get_data()
    try:
        if name == "list_available":
            return {"years": d.years, "latest_year": d.latest,
                    "latest_complete_year": d.latest_complete,
                    "note": (f"{d.latest} is still partially reported; use "
                             f"{d.latest_complete} for complete annual totals."),
                    "regions": [r["region"] for r in d.region_breakdown()],
                    "top_exporters": [r["country"] for r in d.top("export", d.latest_complete, n=15)],
                    "top_importers": [r["country"] for r in d.top("import", d.latest_complete, n=15)]}
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
        if name == "amazon_reviews":
            return get_amazon().agent_summary(args["category"])
        if name == "google_trends":
            return get_trends().agent_summary(args["category"], args.get("country"))
        if name == "skin_type_segments":
            return skin_types.agent_summary()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    return {"error": f"unknown tool {name}"}


SYSTEM = """You are the Product Scout AI, an analyst for cosmetics e-commerce that sees TWO real datasets:

1. TRADE — official UN Comtrade customs statistics for HS 3304 (beauty & make-up preparations): country exports/imports, growth, corridors, regions. Tools: top_countries, country_profile, country_trend, trade_corridors, region_breakdown, list_available.
2. SOCIAL — real consumer conversations (Reddit skincare communities): which products/ingredients people discuss and how they FEEL about them (VADER sentiment). Tools: social_search, social_overview, product_sentiment.
3. AMAZON REVIEWS — for three categories (Sunscreen / SPF, Moisturizer & Hydration, Cleanser & Oil Control): per-product ratings and aspect-level negative rates (pain points = sourcing opportunities), best-in-class, AI summaries. Tool: amazon_reviews.
4. GOOGLE TRENDS — search-interest momentum for those same three categories in Hong Kong (HK) and Japan (JP): category trend, 3-month momentum, YoY growth, rising sub-categories, brand momentum. Tool: google_trends. Note momentum/growth are ratios (0.10 = +10%); markets differ markedly (e.g., a category can be rising in JP while declining in HK).
5. SKIN-TYPE SEGMENTS — US consumer skin-type distribution (Statista) for opportunity sizing: what share of adults claim each skin type, the male/female skew, and the linked product category. Tool: skin_type_segments. Use it to size an addressable segment (e.g. oily ~22% of US adults) and pick a target audience; the related_category links a segment to the trade/social/reviews/trends evidence.

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
    print(f"Product Scout running on http://localhost:{port}  (model: {MODEL}, "
          f"AI {'ON' if os.environ.get('ANTHROPIC_API_KEY') else 'OFF — set ANTHROPIC_API_KEY'})")
    app.run(host="0.0.0.0", port=port, debug=False)
