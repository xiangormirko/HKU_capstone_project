# CosmoTrade Intelligence — HS 3304

Global cosmetics (beauty & make-up preparations, **HS 3304**) trade analytics
dashboard with a **real, geographic world map**, fully **real data**, and a
**real Claude AI analyst** that can query the dataset and reason about it.

## What's real (no mock data)

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
**tool-use loop** — Claude calls tools like `top_countries`, `country_trend`,
`trade_corridors`, `region_breakdown` against the real pandas dataset, then
composes the answer. It never invents numbers.

## Run it

```bash
pip install -r requirements.txt

python fetch_data.py                 # ~2 min: pulls real data into data/
export ANTHROPIC_API_KEY=sk-ant-...  # enables the AI analyst (see .env.example)
python server.py                     # → http://localhost:8600
```

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
