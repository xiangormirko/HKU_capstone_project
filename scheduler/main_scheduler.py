# main_scheduler.py
import os
import time
import logging
from datetime import datetime
from dotenv import load_dotenv # Run: pip install python-dotenv
from apscheduler.schedulers.blocking import BlockingScheduler

# ── CENTRAL SYSTEM LOGGING CONFIGURATION ──────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("CentralScheduler")

# Import concrete scraper blueprints
try:
    from reddit_scraper import RedditIndustrialScraper
    from trends_scraper import GoogleTrendsScraper
    from amazon_scraper import AmazonApifyScraper
except ImportError as e:
    logger.error(f"Failed to import scraper modules: {e}")
    raise

# ── LOAD ENVIRONMENT VARIABLES FROM .ENV FILE ─────────────────────────────
# Automatically looks for a .env file in the current directory execution path
load_dotenv()

# ── ENVIRONMENT VARIABLE EXTRACTION & VALIDATION ──────────────────────────
POSTGRES_CONFIG = {
    "dbname":   os.getenv("DB_NAME", "capstone_db"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432))
}

SQLALCHEMY_URL = f"postgresql://{POSTGRES_CONFIG['user']}:{POSTGRES_CONFIG['password']}@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['dbname']}"
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

# Fail-safe integrity checks before booting core engines
if not POSTGRES_CONFIG["password"]:
    logger.critical("DB_PASSWORD environment variable is not defined! System aborted.")
    exit(1)
if not APIFY_API_TOKEN:
    logger.critical("APIFY_API_TOKEN environment variable is not defined! System aborted.")
    exit(1)

# ── INSTANTIATE SYSTEM WORKING ENGINES ────────────────────────────────────
# The Reddit Engine internally fetches REDDIT_COOKIE using os.getenv inside its class logic
reddit_engine = RedditIndustrialScraper(db_config=POSTGRES_CONFIG)
trends_engine = GoogleTrendsScraper(db_url=SQLALCHEMY_URL)
amazon_engine = AmazonApifyScraper(apify_token=APIFY_API_TOKEN, db_config=POSTGRES_CONFIG)

# ── JOB DEFINITIONS ───────────────────────────────────────────────────────

def task_reddit_scout():
    """Triggers Phase 1: Subreddit Discovery Channel"""
    logger.info("Executing Scheduled Job: Reddit Scout Channels...")
    target_subreddits = ["SkincareAddiction", "AsianBeauty", "30plusSkincare"]
    
    for sub in target_subreddits:
        target_url = f"https://www.reddit.com/r/{sub}/new/.json?limit=100"
        try:
            reddit_engine.run_scout_mode(target_url)
        except Exception as e:
            logger.error(f"Job execution fault during Reddit Scout sub channel '{sub}': {e}")

def task_reddit_deep_dive():
    """Triggers Phase 2: High Density Text Extraction for Incubated Posts"""
    logger.info("Executing Scheduled Job: Reddit Comment Deep Dive Execution...")
    try:
        reddit_engine.run_deep_dive_mode(age_hours=48)
    except Exception as e:
        logger.error(f"Job execution fault during Reddit Deep Dive Sequence: {e}")

def task_google_trends():
    """Triggers Phase 3: Global Time-series Analytics Gathering"""
    logger.info("Executing Scheduled Job: Google Trends Sync Loop...")
    
    countries = ['HK', 'JP', 'KR', 'TW', 'US']
    queries = [
        {
            'id': 'moisturizer_subcategories',
            'category': 'moisturizer_hydration',
            'type': 'subcategory',
            'keywords': ['hydrating serum', 'ceramide moisturizer', 'barrier cream']
        }
    ]

    for country in countries:
        for q_config in queries:
            try:
                trends_engine.fetch_and_save_query(country, q_config)
                time.sleep(5)
            except Exception as e:
                logger.error(f"Job execution fault during Google Trends loop ({country} - {q_config['id']}): {e}")

def task_amazon_apify():
    """Triggers Phase 4: Serverless E-Commerce Consumer Sentiment Crawler"""
    logger.info("Executing Scheduled Job: Amazon E-Commerce Scraper Node Trigger...")
    
    # 1. Load Actor IDs from .env, fallback to the default ID if not configured
    actor_ids_str = os.getenv("APIFY_ACTOR_IDS", "gFtgG31RZJYlphznm")
    actor_ids = [aid.strip() for aid in actor_ids_str.split(",")]
    
    run_input = {
        "personal_data": False,
        "products": [
            "B08C1N59X6"
        ],
        "limit": 3,
        "sort": "helpful",
        "all_stars": False,
        "rating": "all",
        "avp_reviews": False,
        "include_variants": True,
        "scrape_image_reviews": False,
        "scrape_video_reviews": False,
        "region": "amazon.ca",
        "language": "all"
    }
    
    # 2. Automated rotation and failover mechanism
    pipeline_success = False
    
    for idx, actor_id in enumerate(actor_ids):
        logger.info(f"➔ [Attempt {idx+1}/{len(actor_ids)}] Launching Actor ID: {actor_id}")
        
        try:
            # Reused the global 'amazon_engine' instance directly
            records_count = amazon_engine.scrape_reviews(actor_id, run_input=run_input)
            
            # 3. Check if data was successfully fetched and ingested
            if records_count and records_count > 0:
                logger.info(f"🟢 Success! Actor {actor_id} fetched and ingested {records_count} records.")
                pipeline_success = True
                break  # Exit the loop early upon successful ingestion
            else:
                logger.warning(f"⚠️ Warning: Actor {actor_id} returned 0 records (likely blocked or empty payload).")
                
        except Exception as e:
            logger.error(f"❌ Error: Actor {actor_id} crashed during execution: {str(e)}")
            # Continue to the next fallback actor instead of breaking the pipeline
            continue

    # 4. Final pipeline status reporting
    if not pipeline_success:
        logger.error("🚨 CRITICAL: All configured Actor IDs failed to bypass the Amazon firewall. Data pipeline halted.")
    else:
        logger.info("=== Amazon Apify Scraper Scheduled Loop Completed ===")


# ── SCHEDULER ENGINE ORCHESTRATION ────────────────────────────────────────
if __name__ == "__main__":
    scheduler = BlockingScheduler()
    logger.info("Initialization complete. Coupling jobs to General Scheduler Core...")

    # Job 1: Reddit Discovery Channel - Fires every 12 hours
    scheduler.add_job(task_reddit_scout, 'interval', hours=12, id='job_reddit_scout', max_instances=1)
    
    # Job 2: Reddit Context Extraction Tree - Fires every 12 hours
    scheduler.add_job(task_reddit_deep_dive, 'interval', hours=12, id='job_reddit_deep_dive', max_instances=1)
    
    # Job 3: Google Trends Metrics Engine - Cron style triggering every Monday at Midnight
    scheduler.add_job(task_google_trends, 'cron', day_of_week='mon', hour=0, minute=0, id='job_google_trends')
    
    # Job 4: Apify Amazon Interface - Fires every 24 hours
    scheduler.add_job(task_amazon_apify, 'interval', hours=24, id='job_amazon_apify', max_instances=1)

    try:
        logger.info("Starting Central Engine Loop. Press Ctrl+C to terminate.")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown message captured. Safely releasing execution resources.")