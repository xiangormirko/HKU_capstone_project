# test_run.py
import os
import logging
from dotenv import load_dotenv

# Import our scrapers
from reddit_scraper import RedditIndustrialScraper
from trends_scraper import GoogleTrendsScraper
from amazon_scraper import AmazonApifyScraper

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ManualTester")

# Load environment variables from .env
load_dotenv()

# Configuration mapping
POSTGRES_CONFIG = {
    "dbname": os.getenv("DB_NAME", "capstone_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432))
}
SQLALCHEMY_URL = f"postgresql://{POSTGRES_CONFIG['user']}:{POSTGRES_CONFIG['password']}@{POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['dbname']}"
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

def test_reddit_pipeline():
    logger.info("=== Starting Test: Reddit Scraper ===")
    scraper = RedditIndustrialScraper(db_config=POSTGRES_CONFIG)
    
    # 1. Test Scout Mode (Fetch posts from a single subreddit)
    test_url = "https://www.reddit.com/r/AsianBeauty/new/.json?limit=5"
    logger.info("Testing Reddit Scout Mode...")
    scraper.run_scout_mode(test_url)
    
    # 2. Test Deep Dive Mode (Process mature posts that were just inserted)
    logger.info("Testing Reddit Deep Dive Mode (using 0 hours to force immediate scan)...")
    scraper.run_deep_dive_mode(age_hours=0)

def test_google_trends_pipeline():
    logger.info("=== Starting Test: Google Trends Scraper ===")
    scraper = GoogleTrendsScraper(db_url=SQLALCHEMY_URL)
    
    test_query = {
        'id': 'test_moisturizer',
        'category': 'skincare',
        'type': 'test',
        'keywords': ['hydrating serum'] # Use single keyword to test quickly
    }
    # Test for a single country
    scraper.fetch_and_save_query(country='HK', query_config=test_query)

def test_amazon_apify_pipeline():
    logger.info("=== Starting Test: Amazon Apify Scraper ===")
    scraper = AmazonApifyScraper(apify_token=APIFY_API_TOKEN, db_config=POSTGRES_CONFIG)
    
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
        logger.info(f"[Attempt {idx+1}/{len(actor_ids)}] Launching Actor ID: {actor_id}")
        
        try:
            # Execute the original scraping and database ingestion logic
            # Note: Ensure scrape_reviews() returns the count of fetched records (e.g., return len(reviews))
            records_count = scraper.scrape_reviews(actor_id, run_input=run_input)
            
            # 3. Check if data was successfully fetched and ingested
            if records_count and records_count > 0:
                logger.info(f"Success! Actor {actor_id} fetched and ingested {records_count} records.")
                pipeline_success = True
                break # Exit the loop early upon successful ingestion
            else:
                logger.warning(f"Warning: Actor {actor_id} returned 0 records (likely blocked by anti-bot system).")
                
        except Exception as e:
            logger.error(f"Error: Actor {actor_id} crashed during execution: {str(e)}")
            # Continue to the next fallback actor instead of breaking the pipeline
            continue

    # 4. Final pipeline status reporting
    if not pipeline_success:
        logger.error("CRITICAL: All configured Actor IDs failed to bypass the Amazon firewall. Data pipeline halted.")
    else:
        logger.info("=== Amazon Apify Scraper Integration Test Completed ===")

if __name__ == "__main__":
    logger.info("Starting manual system integration test...")
    
    # UNCOMMENT ONE BY ONE TO TEST EACH SCRAPER
    
    # test_reddit_pipeline()
    # test_google_trends_pipeline()
    test_amazon_apify_pipeline()
    
    logger.info("Manual testing sequence completed.")