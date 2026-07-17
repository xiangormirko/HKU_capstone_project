# main_scheduler.py
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv # Run: pip install python-dotenv
from apscheduler.schedulers.blocking import BlockingScheduler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    from fetch_data import main as run_trade_ingest
    from social_ingest import run as run_social_ingest
except ImportError as e:
    logger.error(f"Failed to import scheduler modules: {e}")
    raise

# ── LOAD ENVIRONMENT VARIABLES FROM .ENV FILE ─────────────────────────────
# Automatically looks for a .env file in the current directory execution path
load_dotenv()

# ── ENVIRONMENT VARIABLE EXTRACTION & VALIDATION ──────────────────────────
POSTGRES_CONFIG = {
    "dbname": os.getenv("DB_NAME", "capstone_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432))
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

def task_social_ingest():
    """Triggers Phase 5: Social NLP processing from deep-scanned reddit data."""
    logger.info("Executing Scheduled Job: Social Ingestion / NLP Analytics Sync...")
    try:
        run_social_ingest()
    except Exception as e:
        logger.error(f"Job execution fault during Social Ingestion Sequence: {e}")


def task_google_trends():
    """Triggers Phase 3: Global Time-series Analytics Gathering (Full 5-Year History Backfill)"""
    logger.info("Executing Scheduled Job: Google Trends Sync Loop...")
    
    # Full 13 countries from google_trends_v2.py
    countries = ['HK', 'JP', 'KR', 'TW', 'SG', 'TH', 'PH', 'MY', 'US', 'GB', 'FR', 'DE', 'AU']
    
    # Full query definitions from google_trends_v2.py
    queries = [
        # ── MOISTURIZER & HYDRATION ───────────────────────────────────────────
        {
            'id': 'moisturizer_baseline',
            'category': 'moisturizer_hydration',
            'type': 'baseline',
            'keywords': ['moisturizer'],
        },
        {
            'id': 'moisturizer_subcategories',
            'category': 'moisturizer_hydration',
            'type': 'subcategory',
            'keywords': ['hydrating serum', 'ceramide moisturizer', 'barrier cream', 'skin flooding'],
        },
        # ── SUNSCREEN / SPF ───────────────────────────────────────────────────
        {
            'id': 'sunscreen_baseline',
            'category': 'sunscreen_spf',
            'type': 'baseline',
            'keywords': ['sunscreen'],
        },
        {
            'id': 'sunscreen_subcategories',
            'category': 'sunscreen_spf',
            'type': 'subcategory',
            'keywords': ['mineral sunscreen', 'tinted sunscreen', 'SPF moisturizer', 'reef safe sunscreen'],
        },
        # ── CLEANSER & OIL CONTROL ────────────────────────────────────────────
        {
            'id': 'cleanser_baseline',
            'category': 'cleanser_oil_control',
            'type': 'baseline',
            'keywords': ['face wash'],
        },
        {
            'id': 'cleanser_subcategories',
            'category': 'cleanser_oil_control',
            'type': 'subcategory',
            'keywords': ['double cleansing', 'micellar water', 'oil control cleanser', 'salicylic acid cleanser'],
        },
        # ── BRANDS (cross-category) ───────────────────────────────────────────
        {
            'id': 'brands_tier1',
            'category': 'brands',
            'type': 'brand',
            'keywords': ['CeraVe', 'La Roche-Posay', 'Neutrogena', 'Cetaphil', 'Laneige'],
        },
        {
            'id': 'brands_tier2',
            'category': 'brands',
            'type': 'brand',
            'keywords': ['CeraVe', 'The Ordinary', 'COSRX', 'Anua', 'Torriden'],
        },
    ]

    for country in countries:
        for q_config in queries:
            try:
                # This will pull 5 years of history and batch upsert it into google_trends_data table
                trends_engine.fetch_and_save_query(country, q_config, timeframe='today 5-y')
                
                # Anti-rate-limiting: Google Trends is very sensitive (Too Many Requests 429). 
                # Keep a 10-second window between requests to stay safe.
                time.sleep(10) 
            except Exception as e:
                logger.error(f"Job execution fault during Google Trends loop ({country} - {q_config['id']}): {e}")

def task_amazon_apify():
    """
    Triggers Phase 4: Serverless E-Commerce Consumer Sentiment Crawler.
    Compiles ASINs from target skincare categories, executes the scraper,
    and upserts the output into the PostgreSQL database.
    """
    logger.info("Executing Scheduled Job: Amazon E-Commerce Scraper Node Trigger...")
    
    # 1. Load Actor IDs from .env (fallback to working default if not set)
    actor_ids_str = os.getenv("APIFY_ACTOR_IDS", "gFtgG31RZJYlphznm")
    actor_ids = [aid.strip() for aid in actor_ids_str.split(",")]
    
    # 2. Centralized Product-to-Category mapping
    # Matches exactly the categories expected by your amazon.py frontend service
    PRODUCT_CATEGORY_MAP = {
        "B0BVV8BNYJ": "Cleanser & Oil Control", # Anua Heartleaf Cleansing Foam
        "B0BN2PX8V3": "Cleanser & Oil Control", # Anua Heartleaf Cleansing Oil
        "B07RJ18VMF": "Moisturizer & Hydration", # COSRX Snail Mucin Essence
        "B08CQ9T6KN": "Sunscreen / SPF", # Beauty of Joseon Sunscreen
        "B09Y4HHY1P": "Sunscreen / SPF" # Round Lab Sunscreen
    }
    
    # Extract only the unique list of ASINs to send in a single batch request
    products_list = list(PRODUCT_CATEGORY_MAP.keys())
    # 3. Configure crawler execution parameters

    run_input = {
        "all_stars": False,
        "avp_reviews": True,
        "include_variants": True,
        "limit": 50,
        "personal_data": False,
        "products": products_list,
        "scrape_image_reviews": False,
        "scrape_video_reviews": False,
        "sort": "recent",
        "rating": "all",
        "region": "amazon.com",
        "language": "all",
    }
    
    # 4. Trigger cloud scraper and persist reviews in PostgreSQL
    for actor_id in actor_ids:
        try:
            # We pass the category map down so the scraper knows where to route each review
            success = amazon_engine.scrape_reviews(
                actor_id=actor_id,
                run_input=run_input,
                product_category_map=PRODUCT_CATEGORY_MAP
            )
            if success:
                logger.info(f"E-commerce sentiment metrics updated cleanly for actor: {actor_id}")
            else:
                logger.warning(f"Database sync finished with warnings for actor: {actor_id}")
        except Exception as e:
            logger.error(f"Execution failed on Amazon scraper pipeline for actor {actor_id}: {e}", exc_info=True)

def task_un_comtrade_sync():
    """Triggers Phase 5: UN Comtrade Global Customs Data Ingestion Layer"""
    logger.info("Executing Scheduled Job: UN Comtrade Customs Sync Loop...")
    try:
        # full_history=False tells it to only scan the current and previous year dynamically
        run_trade_ingest(full_history=False)
        logger.info("=== UN Comtrade Customs Sync Scheduled Loop Completed ===")
    except Exception as e:
        logger.error(f"Job execution fault during UN Comtrade Sync Sequence: {e}")

# ── SCHEDULER ENGINE ORCHESTRATION ────────────────────────────────────────
if __name__ == "__main__":
    scheduler = BlockingScheduler()
    logger.info("Initialization complete. Coupling jobs to General Scheduler Core...")

    # Job 1: Reddit Discovery Channel - Fires every 12 hours
    scheduler.add_job(task_reddit_scout, 'interval', hours=12, id='job_reddit_scout', max_instances=1)
    
    # Job 2: Reddit Context Extraction Tree - Fires every 12 hours
    scheduler.add_job(task_reddit_deep_dive, 'interval', hours=12, id='job_reddit_deep_dive', max_instances=1)
    
    # Job 3: Social Ingestion / NLP Sync - Fires every 6 hours after raw reddit data is available
    scheduler.add_job(task_social_ingest, 'interval', hours=6, id='job_social_ingest', max_instances=1)
    
    # Job 4: Google Trends Metrics Engine - Cron style triggering every Monday at Midnight
    scheduler.add_job(task_google_trends, 'cron', day_of_week='mon', hour=0, minute=0, id='job_google_trends')
    
    # Job 5: Apify Amazon Interface - Fires every 24 hours
    scheduler.add_job(task_amazon_apify, 'interval', hours=24, id='job_amazon_apify', max_instances=1)

    # Job 6: UN Comtrade Analytics Engine - Cron style triggering every Sunday at 2 AM Add this
    scheduler.add_job(task_un_comtrade_sync, 'cron', day_of_week='sun', hour=2, minute=0, id='job_un_comtrade_sync')

    try:
        logger.info("Starting Central Engine Loop. Press Ctrl+C to terminate.")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown message captured. Safely releasing execution resources.")