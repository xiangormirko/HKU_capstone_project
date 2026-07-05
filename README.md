# Product Scout

A data-driven, agentic tool for cosmetics e-commerce intelligence. It fuses four
real data layers — social sentiment (Reddit), search-trend momentum (Google
Trends), consumer reviews (Amazon), and global trade flows (UN Comtrade) — to
surface emerging product opportunities, and lets you interrogate all of it in
plain English via an embedded Claude agent.

Views are switchable from the top menu bar:

0. **🏠 Home** — the landing dashboard. Two live, auto-refreshing lists:
   **Trending Blue Ocean** (sub-categories rising across multiple markets, from
   Google Trends) and **Consumer Pain Points** (the most-complained review
   aspects, filtered to genuine negativity and ranked by volume), plus a **Where
   Global Demand Is Growing** trade strip (fastest-growing import markets) and a
   data-driven **AI Morning Brief**. Every list recomputes on each data ingest.
   An **embedded AI chat** sits at the bottom, and each item has an "Ask AI"
   handoff. Backend: `home.py` + `/api/home`.
1. **🌐 Trade Intelligence** — global cosmetics (HS 3304) import/export analytics
   with a real geographic world map, real UN Comtrade data, and a real Claude AI
   analyst that queries the dataset.
2. **💬 Social Discovery** — product & sentiment discovery from social posts.
   Query a need like *"oily skin remover"* and get the most relevant posts, the
   products/ingredients people mention, and how they feel about them
   (VADER sentiment). Reddit today; **Google Trends / other platforms slot in
   later** via the same source-agnostic schema.
   - The landing shows **product categories first**, then data-driven launch
     opportunities. **Clicking a category opens a detail page** with three
     modules: **Amazon Reviews Intelligence** (per-product ratings, aspect-level
     negative rates = sourcing opportunities, best-in-class benchmark,
     voice-of-customer quotes — compiled in `amazon.py` from the review export
     in `data/amazon/`), a **Google Trends** module (real — `trends.py` over `data/trends/metrics.csv`
     + `timeseries.csv`: weekly search interest 0–100 for HK & JP, 2023–2025,
     with a country toggle, a category + brand momentum line chart, rising
     sub-categories, and brand momentum), and the **Reddit conversation** for
     that category. Endpoint: `/api/social/category?name=`. Built for an
     e-commerce **sourcer** persona. The Claude agent also has `amazon_reviews`
     and `google_trends` tools, so it can reason over reviews and demand momentum
     alongside trade and social sentiment.
3. **🎯 Source-to-Sell** — the fusion of the two: links social brand demand to
   country trade flows via **brand origin**. Shows **where to source** (origin
   countries whose brands shoppers love, scored vs their cosmetics export
   strength — e.g. K-beauty/Korea) and **where to sell** (net-importer countries
   with unmet demand — e.g. China), plus per-category source→sell routes.
   Backend: `fusion.py` + `/api/fusion`; the AI agent also has a `source_to_sell`
   tool. *Honest scope: HS 3304 trade is one code (category-agnostic); the social
   side supplies product-type & sentiment granularity; brand origin bridges them.*

---

## Social Discovery pipeline

```
data/skincare_multi_sub_data.json   (Reddit dump: posts + comments)
        │  python social_ingest.py
        ▼
social_taxonomy.py   categories / brands / ingredients dictionaries (extensible)
social_ingest.py     entity extraction + VADER sentiment per post & comment
        ▼ produces in data/
  social_relationships.csv  ← the RELATIONSHIP TABLE (post ↔ product/category links)
  social_posts.json         ← processed posts w/ sentiment + matched entities
  social_entities.json      ← per-brand/ingredient/category rollups (mentions, sentiment)
  social_categories.json    ← per-category rollups
social.py            query layer: resolves a phrase → category/brand/ingredient,
                     ranks relevant posts, aggregates products + sentiment
```

API: `GET /api/social/overview`, `GET /api/social/search?q=oily+skin+remover`.

A query resolves to product categories/brands/ingredients, returns ranked posts
(each with post sentiment, discussion sentiment from its comments, mentioned
products, and the top community comment), plus an aggregate of the most-mentioned
products/ingredients with their sentiment.

**Add a new source** (e.g. Google Trends): emit records carrying a `source` field
and the same post shape, reuse `social_taxonomy.py`, and append to the processed
files — the query layer and UI need no changes.

---

## Trade Intelligence — what's real (no mock data)

| Piece | Source |
|---|---|
| KPIs, top exporters/importers, trends, volumes, regions | **UN Comtrade** official customs statistics (HS 3304, annual 2018–2025) |
| Rolling recency | **Monthly** HS 3304 world totals (`data/monthly_trade.csv`) give a "latest month" figure and trend well past the annual snapshot. The newest annual/monthly periods are only partially reported, so the app defaults headline KPIs to the last *complete* year (`latest_complete`), trims charts to complete periods, and marks partial years "(partial)" in the selector |
| Bilateral matrix & trade corridors | UN Comtrade bilateral export flows |
| World map | D3 + Natural Earth TopoJSON, choropleth joined to Comtrade by ISO numeric code, with flow arcs between real country centroids |
| Market opportunities | Computed from the real data (fastest-growing import markets, net-import gaps, emerging corridors) |
| **Trade Analyst AI** | A real **Claude** agent (`/api/chat`) with tool access to the live dataset — it calls tools to fetch real numbers, then writes generative analysis |

The shipment data that commercial aggregators (e.g. Volza) sell is just this
customs data with company names attached; here we use the free official source.

## Architecture

Four ingest pipelines feed flat files in `data/`; an analytics/fusion layer turns
those into API payloads; Flask serves the views and the Claude agent.

```
INGEST (scheduled or on-demand)          ANALYTICS / FUSION            SERVE
─────────────────────────────           ──────────────────           ─────────────
fetch_data.py   → data/*.csv ─┐         analytics.py  (trade)   ┐
social_ingest.py→ social_*    ├──────►  social.py     (reddit)  ├─► server.py (Flask)
scheduler/ (Apify/pytrends) ──┤         amazon.py     (reviews) │     /api/home   home.py
  → data/amazon,trends,monthly│         trends.py     (trends)  │     /api/data   analytics
                              │         skin_types.py (statista)│     /api/social/*  social
refresh_manager.py  ─────────┘         fusion.py  (5-signal    │     /api/fusion  fusion
  freshness + ETA + trigger             opportunity engine)  ───┘     /api/chat   agent loop
  scheduler_app.py (recurring)                                        /api/freshness · /api/refresh
                                                                            │
                                              index.html + util.js, app.js, social.js,
                                              category.js, fusion.js, home.js, freshness.js
```

Key modules:

| Module | Responsibility |
|---|---|
| `fetch_data.py` | Pull HS 3304 annual (2018–2025) + rolling monthly world totals + bilateral flows from UN Comtrade → `data/*.csv` |
| `analytics.py` | Trade analytics; `latest_complete` partial-year guard; monthly recency; dashboard payload + agent trade tools |
| `social.py` / `social_ingest.py` / `social_taxonomy.py` | Reddit entity extraction + VADER sentiment; query layer |
| `amazon.py` | Review aspect analysis (pain points, best-in-class, voice-of-customer) |
| `trends.py` | Google Trends momentum + rising sub-categories per market |
| `skin_types.py` | Statista skin-type segment sizing |
| `fusion.py` | Source-to-Sell engine — fuses all five signals into ranked opportunities + emerging-format whitespace |
| `home.py` | Landing dashboard: blue-ocean + pain points + trade + brief |
| `refresh_manager.py` / `scheduler_app.py` | Data freshness, ETA estimation, on-demand + recurring refresh |
| `util.js` | Shared frontend helpers (`esc`, `sb`, `sentClass`, `postChat`, …) loaded before all views |

The AI panel needs a backend because an API key must never live in the browser.
The chat posts the conversation to `/api/chat`; the server runs a Claude
**tool-use loop**. **Product Scout AI is cross-domain** — it has 13 tools across
all four datasets and can connect them in one answer:

* Trade: `top_countries`, `country_profile`, `country_trend`, `trade_corridors`,
  `region_breakdown`, `list_available`
* Social: `social_search`, `social_overview`, `product_sentiment`
* Reviews / demand / segments: `amazon_reviews`, `google_trends`,
  `skin_type_segments`, `source_to_sell`

So it can answer e.g. *"Does K-beauty social buzz match Korea's export growth?"*
by calling a trade tool and a social tool, then synthesizing. It never invents
numbers — every figure comes from a tool.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python fetch_data.py                 # ~3 min: pulls annual 2018–2025 + monthly trade into data/
python social_ingest.py              # processes the Reddit dump (entities + sentiment)
export ANTHROPIC_API_KEY=sk-ant-...  # enables Product Scout AI (see .env.example)
python server.py                     # → http://localhost:8600
```

`social_ingest.py` looks for `data/skincare_multi_sub_data.json` (auto-copied
from `~/Downloads` on first run) or takes a path argument. Data already ships in
`data/`, so the app runs out of the box without re-fetching.

Without an API key, the whole app still runs on real data — only the AI chat
shows a "connect your key" notice.

**Recurring refresh:** `PS_ENABLE_SCHEDULER=1 python server.py` runs the refresh
scheduler in-process, or run `python scheduler_app.py` standalone. Live pulls need
credentials in `scheduler/.env` (`APIFY_API_TOKEN`, `REDDIT_COOKIE`); without them
the scheduler re-processes the bundled corpora.

## Tests

```bash
python -m pytest -q          # core-logic tests (no network / no API key)
```

`tests/test_core.py` locks in the load-bearing analytics: partial-year handling
(`latest_complete`, chart trimming), the pain-point negativity floor, opportunity
corroboration/ranking in the fusion engine, monthly recency coverage filtering,
and the refresh-manager status/ETA contract.

## Notes & next steps

- The free Comtrade preview endpoint caps results at 500 rows/call and is
  rate-limited; the fetch script pages around this (one call per period, with
  429 back-off) to pull annual 2018–2025 **and** the last ~15 months. For higher
  throughput/depth, add a free Comtrade API key and switch to `/data/v1/get`.
- The newest Comtrade periods are only partially reported. This is handled
  explicitly (`latest_complete`, coverage-filtered monthly, "(partial)" labels)
  rather than hidden — headline totals use the last complete year.
- Bilateral flows are sourced from the world's major cosmetics exporters
  (France, Korea, USA, China, Japan, …), which dominate HS 3304 trade.
- Company/supplier-level ("who exactly shipped to whom") is the proprietary
  layer aggregators sell; official stats are country-to-country.
- Streaming responses and per-message tool-call display could be added to the
  AI panel for a richer agent UX.
