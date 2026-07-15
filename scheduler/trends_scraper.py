# trends_scraper.py
import time
import logging
import pandas as pd
from sqlalchemy import create_engine, text
from pytrends.request import TrendReq

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GoogleTrendsScraper:
    def __init__(self, db_url: str):
        """
        :param db_url: SQLAlchemy connection string loaded via environment variables
        """
        self.engine = create_engine(db_url)
        self.client = TrendReq(
            hl='en-US', tz=0,
            requests_args={'headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            }}
        )

    def fetch_and_save_query(self, country: str, query_config: dict, timeframe='today 5-y'):
        """Fetches time-series trend interest for a single query package and saves to PostgreSQL."""
        query_id = query_config['id']
        keywords = query_config['keywords']
        
        logger.info(f"Fetching Google Trends data for Country: {country} | Query Group: {query_id}")

        for attempt in range(5):
            try:
                self.client.build_payload(keywords, timeframe=timeframe, geo=country)
                df = self.client.interest_over_time()
                
                if df.empty:
                    logger.warning(f"Empty response returned for {country} / {query_id}")
                    return
                
                if 'isPartial' in df.columns:
                    df = df.drop(columns=['isPartial'])
                
                df = df.reset_index()
                
                df_long = df.melt(id_vars='date', var_name='keyword', value_name='score')
                df_long['country'] = country
                df_long['query_id'] = query_id
                df_long['category'] = query_config['category']
                df_long['type'] = query_config['type']
                
                df_db = df_long[['date', 'country', 'category', 'type', 'query_id', 'keyword', 'score']]
                
                insert_stmt = text("""
                            INSERT INTO google_trends_data (date, country, category, type, query_id, keyword, score)
                            VALUES (:date, :country, :category, :type, :query_id, :keyword, :score)
                            ON CONFLICT (date, country, keyword)
                            DO UPDATE SET score = EXCLUDED.score;
                        """)

                # 2. Defensive cleansing: Convert datetimes to strings to eliminate driver friction
                df_db_clean = df_db.copy()
                if pd.api.types.is_datetime64_any_dtype(df_db_clean['date']):
                    df_db_clean['date'] = df_db_clean['date'].dt.strftime('%Y-%m-%d')
                
                # Safe type-casting: Map Pandas NaN elements to native Python None (SQL NULL values)
                records = df_db_clean.where(pd.notnull(df_db_clean), None).to_dict(orient='records')

                # 3. Open a transactional block and dispatch the entire array in 1 network trip
                if records:
                    with self.engine.begin() as connection:
                        # Passing a list of dictionaries automatically triggers SQLAlchemy batch execution
                        connection.execute(insert_stmt, records)
                        
                logger.info(f"Successfully committed trends data for {country} - {query_id} into DB.")
                return
                
            except Exception as e:
                wait_time = (2 ** attempt) + 5
                logger.error(f"Error fetching {country}/{query_id} (Attempt {attempt+1}/5): {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                
        logger.error(f"Failed to fetch trends data for {country} / {query_id} after maximum retries.")