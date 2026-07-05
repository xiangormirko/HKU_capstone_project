# amazon_scraper.py
import logging
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import execute_values
from apify_client import ApifyClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AmazonApifyScraper:
    def __init__(self, apify_token: str, db_config: dict):
        """
        :param apify_token: API token injected via environment configuration
        :param db_config: PostgreSQL connection parameters
        """
        self.client = ApifyClient(apify_token)
        self.db_config = db_config

    def _get_db_connection(self):
        return psycopg2.connect(**self.db_config)

    def scrape_reviews(self, actor_id: str, run_input: dict):
        """Triggers the remote Apify Actor, downloads dataset results, and updates PostgreSQL."""
        logger.info(f"Launching remote Apify Amazon Review Actor: {actor_id}...")
        
        try:
            run = self.client.actor(actor_id).call(run_input=run_input)
            dataset_id = run.get("defaultDatasetId")
            logger.info(f"Actor execution completed successfully. Fetching items from Dataset: {dataset_id}")
            
            dataset_items = self.client.dataset(dataset_id).list_items().items
            logger.info(f"Downloaded {len(dataset_items)} review records from cloud store.")
            
            reviews_payload = []
            fallback_asin = run_input.get("products", ["Unknown"])[0]

            for item in dataset_items:
                review_id = item.get("reviewId") or item.get("id")
                if not review_id:
                    continue
                
                reviews_payload.append((
                    str(review_id),
                    str(item.get("asin", fallback_asin)),
                    item.get("title", ""),
                    item.get("rating"),
                    item.get("reviewText") or item.get("text", ""),
                    bool(item.get("isVerified", False)),
                    int(item.get("helpfulCount", 0)),
                    datetime.now(timezone.utc).isoformat()
                ))

            if not reviews_payload:
                logger.warning("No valid reviews extracted from payload.")
                return

            conn = self._get_db_connection()
            with conn.cursor() as cur:
                query = """
                    INSERT INTO amazon_reviews_data (review_id, asin, title, rating, review_text, is_verified, helpful_count, scraped_at)
                    VALUES %s
                    ON CONFLICT (review_id) 
                    DO UPDATE SET helpful_count = EXCLUDED.helpful_count;
                """
                execute_values(cur, query, reviews_payload)
                conn.commit()
                logger.info(f"Successfully synchronized {len(reviews_payload)} Amazon reviews to PostgreSQL.")
            conn.close()

            return len(reviews_payload)

        except Exception as e:
            logger.error(f"Critical error occurred inside Apify execution pipeline: {e}")
            return 0