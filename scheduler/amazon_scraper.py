# scheduler/amazon_scraper.py
import logging
import json
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

    def scrape_reviews(self, actor_id: str, run_input: dict, product_category_map: dict = None):
        """
        Triggers the remote Apify Actor, downloads dataset results, 
        maps categories dynamically, and performs a bulk PostgreSQL UPSERT.
        """
        logger.info(f"Launching remote Apify Amazon Review Actor: {actor_id}...")

        # FALLBACK: If scheduler doesn't pass a map, use this default skincare mapping
        if product_category_map is None:
            product_category_map = {
                "B0BVV8BNYJ": "Cleanser & Oil Control",    # Anua Heartleaf Cleansing Foam
                "B0BN2PX8V3": "Cleanser & Oil Control",    # Anua Heartleaf Cleansing Oil
                "B07RJ18VMF": "Moisturizer & Hydration",   # COSRX Snail Mucin Essence
                "B08CQ9T6KN": "Sunscreen / SPF",           # Beauty of Joseon Sunscreen
                "B09Y4HHY1P": "Sunscreen / SPF"            # Round Lab Sunscreen
            }

        try:
            # 1. Call the remote Apify Actor
            run = self.client.actor(actor_id).call(run_input=run_input)
            dataset_id = run.get("defaultDatasetId")
            logger.info(f"Actor execution completed successfully. Fetching items from Dataset ID: {dataset_id}")

            # 2. Extract scraped reviews
            dataset_items = self.client.dataset(dataset_id).list_items().items
            logger.info(f"Successfully downloaded {len(dataset_items)} reviews from Apify.")

            if not dataset_items:
                logger.warning("No reviews returned in dataset.")
                return True

            # 3. Parse records and structure database row values
            insert_rows = []
            for item in dataset_items:
                asin = item.get("productAsin")
                
                # Resolve the skincare category using the mapping
                category = product_category_map.get(asin, "General Skincare")
                
                # Serialize the nested aspects array into a raw JSON string for PostgreSQL JSONB
                aspects_json = json.dumps(item.get("aspects", []))
                
                row = (
                    item.get("reviewId"),
                    asin,
                    category,
                    item.get("rating"),
                    bool(item.get("verifiedPurchase", False)),
                    item.get("reviewTitle"),
                    item.get("reviewDate"),
                    item.get("reviewText"),
                    item.get("helpfulVoteCount", 0),
                    aspects_json,
                    item.get("productTitle"),
                    item.get("productUrl")
                )
                insert_rows.append(row)

            # 4. Define the SQL statement utilizing ON CONFLICT (UPSERT)
            upsert_query = """
                INSERT INTO amazon_reviews (
                    review_id, asin, category, rating, verified_purchase, 
                    review_title, review_date, review_text, helpful_vote_count, 
                    aspects, product_title, product_url
                ) VALUES %s
                ON CONFLICT (review_id) DO UPDATE SET
                    rating = EXCLUDED.rating,
                    verified_purchase = EXCLUDED.verified_purchase,
                    review_title = EXCLUDED.review_title,
                    review_date = EXCLUDED.review_date,
                    review_text = EXCLUDED.review_text,
                    helpful_vote_count = EXCLUDED.helpful_vote_count,
                    aspects = EXCLUDED.aspects,
                    product_title = EXCLUDED.product_title,
                    product_url = EXCLUDED.product_url,
                    scraped_at = CURRENT_TIMESTAMP;
            """

            # 5. Execute using your existing connection manager
            with self._get_db_connection() as conn:
                with conn.cursor() as cur:
                    execute_values(cur, upsert_query, insert_rows)
                    conn.commit()
            
            logger.info(f"Successfully upserted {len(insert_rows)} reviews into the database.")
            return True

        except Exception as e:
            logger.error(f"Error executing Amazon scraper pipeline: {e}", exc_info=True)
            return False