========================================================================
Capstone Multi-Source Data Ingestion Pipeline & Scheduler
========================================================================

This repository contains the complete, enterprise-grade data ingestion pipeline
engineered to scratch, clean, and sync trend data from Amazon (E-Commerce), 
Reddit (Social Sentiment), and Google Trends (Search Metrics) into a centralized 
PostgreSQL database cluster.

The core architecture features highly-defensive scraping (anti-bot bypass via 
curl_cffi), automatic DB schema migrations, dynamic multi-actor failover, 
and an enterprise interval scheduler (APScheduler).

------------------------------------------------------------------------
1. Project Directory Layout & File Roles
------------------------------------------------------------------------
capstone
├── .env                  # Infrastructure credentials
│
├── make_db.py            # Phase 1 DB Bootstrapper Provisions 'capstone_db'
├── create_tables.py      # Phase 2 Schema Migrator Builds the 4 structural data tables
│
├── amazon_scraper.py     # Component Serverless cloud client for Amazon reviews
├── reddit_scraper.py     # Component Industrial stealth scrapper (Scout + Deep Dive)
├── trends_scraper.py     # Component Time-series interest analytics engine
│
├── test_run.py           # Manual Sandboxed Integration Tester (Unit tests)
├── main_scheduler.py     # Production Orchestrator Central timed cron system
├── inspect_db.py         # Utility Instant CLI database row counting & live preview
└── README.txt            # Operational Documentation (This file)

------------------------------------------------------------------------
2. Prerequisites & Environment Initialization
------------------------------------------------------------------------
All engines require Python 3.8+. Run the following command in your terminal 
to initialize all mandatory dependencies (including advanced database connectors, 
stealth HTTP impersonation, and task orchestration engines)

$ pip install psycopg2 python-dotenv apify-client pytrends sqlalchemy curl_cffi apscheduler

------------------------------------------------------------------------
3. Local Environment Setup (.env Configuration)
------------------------------------------------------------------------
Create a file exactly named `.env` in the root folder. Copy the template below 
and supply your personal development or production tokens.

--- .env Template CopyPaste ---
# PostgreSQL Infrastructure Settings
DB_HOST=localhost
DB_PORT=5432
DB_NAME=capstone_db
DB_USER=postgres
DB_PASSWORD=your_secure_postgres_password

# Apify Engine Access Token & Fallback Failover Array
APIFY_API_TOKEN=apify_api_your_token_here
# Comma-separated Actor rotation array for defensive bypass
APIFY_ACTOR_IDS=gFtgG31RZJYlphznm

# Reddit High-Stealth Session Authentication Cookie
# (Inspect web browser storage - www.reddit.com - 'cookie' value string)
REDDIT_COOKIE=your_reddit_cookie_string_here
--- End of Template ---

------------------------------------------------------------------------
4. Step-by-Step System Bootstrapping Guide
------------------------------------------------------------------------
Follow this sequential boot sequence to provision your environment from scratch

Step [1] Create the Logical Database Instance
          $ python make_db.py
          (Creates 'capstone_db' via the default server transaction layer)

Step [2] Execute Core Schema Migrations
          $ python create_tables.py
          (Generates the required data tables reddit_posts, reddit_comments, 
           google_trends_data, and amazon_reviews_data with custom constraints)

Step [3] Run Data Inspection to Confirm Empty Readiness
          $ python inspect_db.py
          (Should confirm database connection is active with 0 current records)

------------------------------------------------------------------------
5. Execution Modes Sandbox Testing vs Production Scheduler
------------------------------------------------------------------------

A. Sandbox Testing Mode (Manual Verification)
   File `test_run.py`
   Uncomment specific functions inside the main block to dry-run independent modules 
   without waiting for scheduled intervals. 
   $ python test_run.py

B. Production Automation Mode (Continuous Pipeline)
   File `main_scheduler.py`
   Launches the blocking multi-threaded daemon coordinator. It anchors and executes
   - Reddit Scout (Subreddit Discovery) Runs every 12 Hours
   - Reddit Deep Dive (Contextual Threads Processing) Runs every 12 Hours
   - Amazon Apify Node (E-Commerce Sentiment Loop) Runs every 24 Hours
   - Google Trends Loop (Global Metric Tracking) Runs Cron-style every Mon 0000
   $ python main_scheduler.py
========================================================================