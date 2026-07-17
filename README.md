# Product Scout

**Platform for Business Decision-Making Using Public Sentiment Data**

MSc(CompSc) Capstone Project (COMP7705), School of Computing and Data Science,
The University of Hong Kong.

## 1. Overview

Product Scout is a market-intelligence platform for cross-border cosmetics and
skincare sellers. It fuses four independent public-data signals, namely consumer
sentiment (Reddit), search-interest momentum (Google Trends), consumer reviews
(Amazon), and global trade flows (UN Comtrade), into a single instrument that
identifies product opportunities that no individual signal exposes on its own.
A tool-using large-language-model agent (Anthropic Claude) sits on top of the
data layer and answers cross-domain questions by querying the live database
rather than recalling figures from memory.

The central hypothesis (the "dual-signal thesis") is that joining unstructured
demand-side sentiment with structured supply-side trade data reveals categories
with rising consumer discussion but thin or slow-growing market supply, and that
this gap is a defensible entry point. The two datasets are joined through brand
country-of-origin: social posts name brands, each brand maps to a producing
country, and that country joins to its HS 3304 trade record.

This repository contains a proof-of-concept build validated end-to-end on a
single anchor vertical (skincare, HS 3304).

## 2. Features

The web client exposes five views:

- **Home.** A landing dashboard presenting two live, auto-refreshing lists,
  "Trending Blue Ocean" (sub-categories with rising cross-market search interest)
  and "Consumer Pain Points" (the most-complained review aspects, filtered to a
  minimum negativity and ranked by volume), a fastest-growing-import-markets
  strip, and a generated "AI Morning Brief". Endpoint: `/api/home`.
- **Trade Intelligence.** Global HS 3304 import and export analytics from UN
  Comtrade, with a D3/TopoJSON world choropleth, directional flow arcs, a
  bilateral trade matrix, ranked corridors, and data-driven opportunity cards.
- **Social Discovery.** A free-text query (for example, "oily skin remover")
  resolves to a product category and returns ranked Reddit posts with post- and
  discussion-level VADER sentiment, the products and ingredients mentioned, and
  launch-opportunity cards. Category detail pages combine Amazon Reviews
  Intelligence, a Google Trends momentum panel, and the matched Reddit thread.
- **Source-to-Sell.** The fusion view. Brand-origin joins between social demand
  and country trade flows yield per-category "where to source" and "where to
  sell" recommendations, ranked by multi-signal corroboration.
- **AI Analyst.** An embedded conversational agent, available on every view,
  backed by a 13-tool Claude tool-use loop over all four data layers.

## 3. Data sources

| Source | Access | Contents | Approximate scale |
|---|---|---|---|
| UN Comtrade (HS 3304) | Public REST API (no credentials) | Country export/import totals, bilateral flows; annual 2018–2025 plus a rolling monthly series into 2026 | ~22.3K bilateral rows; ~1.1K country-year rows |
| Reddit | Cookie-authenticated collector (`curl_cffi`) | Posts and comments from three skincare communities, with entity extraction and sentence-level sentiment | ~7.0K posts; ~72.5K comments; ~47.8K entity links |
| Amazon reviews | Apify managed actor | Per-product ratings and pre-computed aspect-level sentiment across three anchor categories | 3 categories |
| Google Trends | `pytrends` wrapper | Weekly relative search interest (0–100) across 13 markets, with category and brand momentum | ~34K time-series rows |

The newest Comtrade periods are only partially reported, so headline figures
default to the last fully reported year (currently 2024); partial years remain
available but are labelled as such.

## 4. System architecture

The platform uses a three-tier design in which the tiers communicate only
through a shared PostgreSQL database (the single source of truth):

```
Ingestion plane            Persistence plane        Delivery plane
(write-heavy)              (single source of truth) (read-heavy)

Reddit  (curl_cffi)   \                            /  Flask REST API
Amazon  (Apify)        \                          /   Vanilla JS + Chart.js + D3
Google Trends (pytrends)>--->  PostgreSQL  <------<    Claude tool-use agent
UN Comtrade (REST)     /    (raw + analytics       \   (13 tools)
Scheduler (APScheduler)/     tables)                \  Home / Trade / Social /
                                                       Source-to-Sell views
```

Raw collectors write to staging tables. A scheduled transform
(`social_ingest.py`) performs sentence-level VADER sentiment scoring and
regex-based taxonomy extraction on the Reddit stream and writes structured
analytics tables. The Flask application reads only from the analytics tables, so
user requests are never blocked by background ingestion.

Key modules:

| Module | Responsibility |
|---|---|
| `scheduler/make_db.py`, `scheduler/create_tables.py` | Bootstrap the `capstone_db` database and its 13 tables |
| `scheduler/fetch_data.py` | Load UN Comtrade HS 3304 annual, monthly, and bilateral data into PostgreSQL |
| `scheduler/reddit_scraper.py`, `amazon_scraper.py`, `trends_scraper.py` | Live collectors (Reddit via `curl_cffi`; Amazon via Apify; Trends via `pytrends`) |
| `scheduler/main_scheduler.py` | Recurring orchestration daemon (APScheduler) |
| `scheduler_app.py`, `refresh_manager.py` | In-app scheduler and on-demand refresh, freshness, and ETA tracking |
| `social_ingest.py`, `social_taxonomy.py` | Reddit transform: sentiment binding and entity/taxonomy extraction |
| `analytics.py` | Trade analytics, partial-year handling, dashboard payload, agent trade tools |
| `amazon.py` | Review aspect analysis (pain points, benchmark, voice-of-customer) |
| `trends.py`, `skin_types.py` | Search-momentum metrics; skin-type segment sizing |
| `fusion.py`, `home.py` | Source-to-Sell fusion engine and landing-dashboard payload |
| `server.py` | Flask REST API and Claude tool-use agent |
| `index.html`, `app.js`, `social.js`, `fusion.js`, `home.js`, `util.js` | Vanilla-JS client |

The client-facing API exposes `/api/data`, `/api/home`, `/api/fusion`,
`/api/social/*`, `/api/chat`, `/api/freshness`, and `/api/refresh`.

## 5. Requirements

- Python 3.12
- PostgreSQL 14 or later to run the application; PostgreSQL 18 (or a newer
  `pg_restore`) to restore the provided database dump described in Section 6.4
- Python packages in `requirements.txt` (Flask, pandas, SQLAlchemy, psycopg2,
  vaderSentiment, APScheduler, anthropic, pycountry, pytest, and related)
- Live data collection additionally requires `curl_cffi`, `pytrends`, and the
  Apify client, plus the credentials listed below.

## 6. Setup and running

The core application (serving from an already-populated database) can be run in a
few steps. Live data collection is optional and requires third-party
credentials.

### 6.1 Install

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 6.2 Configure

Copy the example environment file and set the values:

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...          # required for the AI analyst
DB_NAME=capstone_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
# For live collection only:
# APIFY_API_TOKEN=...                 # Amazon reviews
# REDDIT_COOKIE=...                   # Reddit collector
```

### 6.3 Create the database

```bash
python scheduler/make_db.py          # creates the empty capstone_db database
```

### 6.4 Load the data

Choose one of the two options below. Option A is the fastest and needs no
credentials or scraping.

**Option A — Restore the provided database snapshot (recommended).**

`capstone_db_backup.dump` is a complete snapshot of `capstone_db`, containing all
13 tables with their data, so the application runs immediately with no scraping
or API keys. It is a PostgreSQL custom-format archive produced with `pg_dump`
version 18, so it is restored with `pg_restore` using a PostgreSQL 18 client or
newer. Place the file in the project root, then run:

```bash
pg_restore --no-owner --no-privileges -U postgres -d capstone_db capstone_db_backup.dump
```

The `--no-owner --no-privileges` flags let any local role own the restored
objects, and restoring into the pre-created `capstone_db` avoids the archive's
original (Windows) locale settings. `scheduler/create_tables.py` is not needed
when restoring the dump, since the archive already contains the schema.

> The dump (~20 MB) contains scraped Reddit and Amazon content and is therefore
> distributed alongside the submission rather than committed to the repository
> (it is excluded by `.gitignore`).

**Option B — Create the tables and collect the data from source.**

```bash
python scheduler/create_tables.py    # creates all 13 tables
python scheduler/fetch_data.py       # loads UN Comtrade trade (no credentials needed)
python scheduler/main_scheduler.py   # runs the collectors (Reddit/Amazon/Trends)
python social_ingest.py              # transforms raw Reddit into analytics tables
```

UN Comtrade requires no credentials; Reddit, Amazon, and Google Trends require
the credentials in `.env` (`REDDIT_COOKIE`, `APIFY_API_TOKEN`). With the trade
layer alone, the Trade Intelligence, Home, and Source-to-Sell views are already
demonstrable.

### 6.5 Run the application

```bash
python server.py                     # serves http://localhost:8600
```

Without an `ANTHROPIC_API_KEY`, the dashboard runs normally on the database and
the AI panel displays a "connect your key" notice.

### 6.6 Recurring refresh (optional)

To run the scheduler inside the web process:

```bash
PS_ENABLE_SCHEDULER=1 python server.py
```

or run it as a standalone daemon:

```bash
python scheduler_app.py
```

## 7. Testing

```bash
python -m pytest -q
```

The suite in `tests/test_core.py` covers the deterministic analytical logic:
partial-year handling, the pain-point negativity and volume thresholds, fusion
opportunity ranking, monthly-recency filtering, and the refresh-manager status
and ETA contract. `pytest.ini` restricts collection to `tests/`; the scraper
integration script `scheduler/test_run.py` is excluded because it requires live
credentials. The tests query the analytical layer and therefore require a
configured, populated database.

## 8. Selected methods

- **Partial-year handling.** The last fully reported annual year is the most
  recent year whose reporting-country coverage does not fall below 75% of the
  prior year; headline KPIs and charts default to that year (`analytics.py`).
- **Pain-point score.** An Amazon review aspect is treated as a genuine pain
  point only if it has at least 30 mentions and a negative rate of at least 20%;
  points are ranked by negative-mention volume (`amazon.py`, `home.py`).
- **Sentiment.** VADER is applied at sentence level and bound to the entities in
  each sentence, avoiding the score saturation that document-level scoring
  produces on long posts (`social_ingest.py`).
- **Trends momentum.** A keyword is labelled rising or declining when its
  three-month momentum (mean of the last 13 weeks against the prior 13) exceeds
  +/-20% (`trends.py`).
- **Fusion ranking.** Opportunities are ranked by the number of independent
  signals that corroborate them (`fusion.py`).

Full derivations are given in the project report.

## 9. Scope, limitations, and compliance

- This is a proof of concept validated on a single vertical (skincare, HS 3304).
- Social sentiment is drawn from three subreddits and is not representative of
  the whole cosmetics-buying population.
- Lexicon-based sentiment (VADER) does not detect sarcasm or non-literal emoji
  usage, and the sentiment outputs have not been benchmarked against a labelled
  ground truth. They should be read as directionally useful rather than
  independently validated.
- Data collection uses only publicly available data, stays within each
  platform's terms of service and `robots.txt`, and anonymises user-generated
  content before it enters the analytics tables.
- Scraped Reddit and Amazon content is retained only for non-commercial academic
  use and is excluded from public distribution.

## 10. Authors and supervision

Group project, MSc(CompSc), The University of Hong Kong:

- Yixuan Fan (3036199534)
- Poon Pak Kong (3036384323)
- Carrillo Sabrina (3036411944)
- Zhao Xiang (2012974485)

Supervisor: Professor Lequan Yu.
