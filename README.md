# Product Scout

Two core features for cosmetics e-commerce intelligence, switchable from the top
menu bar:

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
| KPIs, top exporters/importers, trends, volumes, regions | **UN Comtrade** official customs statistics (HS 3304, 2018–2024) |
| Bilateral matrix & trade corridors | UN Comtrade bilateral export flows |
| World map | D3 + Natural Earth TopoJSON, choropleth joined to Comtrade by ISO numeric code, with flow arcs between real country centroids |
| Market opportunities | Computed from the real data (fastest-growing import markets, net-import gaps, emerging corridors) |
| **Trade Analyst AI** | A real **Claude** agent (`/api/chat`) with tool access to the live dataset — it calls tools to fetch real numbers, then writes generative analysis |

The shipment data that commercial aggregators (e.g. Volza) sell is just this
customs data with company names attached; here we use the free official source.

## Architecture

```
fetch_data.py   → pulls HS 3304 data from UN Comtrade → data/*.csv
analytics.py    → loads CSVs; builds the dashboard payload + the agent's tools
server.py       → Flask: serves the page, /api/data, and /api/chat (Claude agent)
index.html      → the dashboard shell (design)
app.js          → fetches real data, renders charts + D3 map, drives the chat
```

The AI panel needs a backend because an API key must never live in the browser.
The chat posts the conversation to `/api/chat`; the server runs a Claude
**tool-use loop**. **Product Scout AI is cross-domain** — it has tools over both
datasets and can connect them in one answer:

* Trade: `top_countries`, `country_profile`, `country_trend`, `trade_corridors`,
  `region_breakdown`
* Social: `social_search`, `social_overview`, `product_sentiment`

So it can answer e.g. *"Does K-beauty social buzz match Korea's export growth?"*
by calling a trade tool and a social tool, then synthesizing. It never invents
numbers — every figure comes from a tool.

## Run it

```bash
pip install -r requirements.txt

python fetch_data.py                 # ~2 min: pulls real trade data into data/
python social_ingest.py              # processes the Reddit dump (entities + sentiment)
export ANTHROPIC_API_KEY=sk-ant-...  # enables the Trade AI analyst (see .env.example)
python server.py                     # → http://localhost:8600
```

`social_ingest.py` looks for `data/skincare_multi_sub_data.json` (auto-copied
from `~/Downloads` on first run) or takes a path argument.

Without an API key, the whole dashboard still runs on real data — only the AI
panel shows a "connect your key" notice.

## Notes & next steps

- The free Comtrade preview endpoint caps results at 500 rows/call; the fetch
  script pages around this. For full monthly / all-country depth, add a free
  Comtrade API key and switch to the `/data/v1/get` endpoint.
- Bilateral flows are sourced from the world's major cosmetics exporters
  (France, Korea, USA, China, Japan, …), which dominate HS 3304 trade.
- Company/supplier-level ("who exactly shipped to whom") is the proprietary
  layer aggregators sell; official stats are country-to-country.
- Streaming responses and per-message tool-call display could be added to the
  AI panel for a richer agent UX.
