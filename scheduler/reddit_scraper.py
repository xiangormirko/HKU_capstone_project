# reddit_scraper.py
import os
import time
import random
import logging
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import execute_values
from curl_cffi import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RedditIndustrialScraper:
    def __init__(self, db_config: dict):
        """
        :param db_config: Dictionary containing PostgreSQL connection parameters
        """
        self.db_config = db_config
        # Leverage curl_cffi's built-in impersonation for enhanced stealth and performance
        self.session = requests.Session(impersonate="chrome")
        
        # Load sensitive authentication cookie securely from environment variables
        reddit_cookie = os.getenv("REDDIT_COOKIE", "")
        
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cookie": reddit_cookie
        }
        
        if not reddit_cookie:
            logger.warning("REDDIT_COOKIE environment variable is missing. Request blocks might occur.")

    def _get_db_connection(self):
        """Creates and returns a new PostgreSQL connection context."""
        return psycopg2.connect(**self.db_config)

    def fetch_json(self, url: str) -> dict or None:
        """Fetches JSON data from Reddit with exponential back-off and jitter."""
        if '.json' not in url:
            url = f"{url.rstrip('/')}/.json"
        url = url.replace('www.reddit.com', 'old.reddit.com')
        
        # Human-mimicking defensive delay
        time.sleep(random.uniform(14.0, 27.0))
        
        max_retries = 3
        base_backoff = 180
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, headers=self.headers, timeout=60)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code in [429, 500, 503]:
                    sleep_time = (base_backoff * (2 ** attempt)) + random.randint(30, 90)
                    logger.warning(f"[HTTP {response.status_code}] Rate limited or server error. Retrying in {round(sleep_time/60, 1)}m...")
                    time.sleep(sleep_time)
                    continue
                else:
                    logger.error(f"Request Failed (Status: {response.status_code}): {url}")
                    return None
            except Exception as e:
                logger.error(f"Network Exception (Attempt {attempt + 1}/{max_retries}): {e}")
                time.sleep(10)
                continue
        return None

    def run_scout_mode(self, subreddit_url: str):
        """Scans for new submissions in a Subreddit and stores them to PostgreSQL."""
        logger.info(f"[Scout Mode] Initializing scan for: {subreddit_url}")
        raw_data = self.fetch_json(subreddit_url)
        if not raw_data: 
            return

        posts = raw_data.get('data', {}).get('children', [])
        posts_data = []

        for p in posts:
            if p.get('kind') != 't3': 
                continue
            data = p.get('data', {})
            p_id = data.get('id')
            sub_name = data.get('subreddit', 'unknown')
            
            posts_data.append((
                p_id, sub_name, data.get('title'), data.get('selftext'),
                f"https://www.reddit.com{data.get('permalink')}", 
                int(data.get('created_utc', 0)), False
            ))

        if not posts_data:
            return

        conn = self._get_db_connection()
        try:
            with conn.cursor() as cur:
                query = """
                    INSERT INTO reddit_posts (id, subreddit, title, content, permalink, created_utc, deep_scanned)
                    VALUES %s
                    ON CONFLICT (id) DO NOTHING;
                """
                execute_values(cur, query, posts_data)
                conn.commit()
                logger.info(f"[Scout Mode] Successfully synced {len(posts_data)} posts to PostgreSQL.")
        except Exception as e:
            conn.rollback()
            logger.error(f"Database write error in Scout Mode: {e}")
        finally:
            conn.close()

    def _parse_comments_recursive(self, comment_data, subreddit_name="unknown"):
        """Recursively parses comment trees, filters bot noise, and returns a list of tuples."""
        children = comment_data.get('data', {}).get('children', [])
        extracted_comments = []
        
        bot_blacklist = {'automoderator', 'remindmebot', 'wikitextbot'}
        bot_patterns = ["i am a bot", "performed automatically", "contact the moderators"]
        
        for item in children:
            kind = item.get('kind')
            data = item.get('data', {})
            
            if kind == 'more': 
                continue 
                
            if kind == 't1':
                c_id = data.get('id')
                author = data.get('author', '')
                author_lower = author.lower() if author else ''
                body = data.get('body', '')
                body_clean = body.strip()

                if author_lower in bot_blacklist or author_lower.endswith('bot'): 
                    continue
                if any(pattern in body.lower() for pattern in bot_patterns): 
                    continue
                if not body_clean or body_clean in ['[deleted]', '[removed]']: 
                    continue

                extracted_comments.append((
                    c_id, 
                    data.get('link_id', '').replace('t3_', ''), 
                    data.get('parent_id'), 
                    subreddit_name, 
                    body_clean, 
                    data.get('ups', 0), 
                    author, 
                    datetime.now(timezone.utc).isoformat()
                ))
                
                replies = data.get('replies')
                if replies and isinstance(replies, dict):
                    extracted_comments.extend(self._parse_comments_recursive(replies, subreddit_name))
                    
        return extracted_comments

    def run_deep_dive_mode(self, age_hours=12):
        """Fetches comments for matured, pending posts and writes to PostgreSQL."""
        logger.info(f"[Deep Dive Mode] Scanning for target posts older than {age_hours} hours...")
        
        conn = self._get_db_connection()
        target_posts = []
        
        try:
            with conn.cursor() as cur:
                now_epoch = datetime.now(timezone.utc).timestamp()
                cutoff_epoch = now_epoch - (age_hours * 3600)
                
                cur.execute("""
                    SELECT id, permalink, subreddit, title FROM reddit_posts 
                    WHERE created_utc < %s AND deep_scanned = FALSE;
                """, (cutoff_epoch,))
                target_posts = cur.fetchall()
        except Exception as e:
            logger.error(f"Failed to query target posts: {e}")
            conn.close()
            return

        if not target_posts:
            logger.info("No mature posts found waiting for processing.")
            conn.close()
            return

        random.shuffle(target_posts)
        logger.info(f"[Deep Dive Mode] Found {len(target_posts)} post(s) queued for processing.")

        for p_id, url, sub_name, title in target_posts:
            logger.info(f" -> [{sub_name}] Fetching comments for: {title[:40]}...")
            detail_data = self.fetch_json(url)
            
            if detail_data and isinstance(detail_data, list) and len(detail_data) > 1:
                comments_tuples = self._parse_comments_recursive(detail_data[1], subreddit_name=sub_name)
                
                if comments_tuples:
                    try:
                        with conn.cursor() as cur:
                            comment_query = """
                                INSERT INTO reddit_comments (id, post_id, parent_id, subreddit, body, ups, author, scanned_at)
                                VALUES %s
                                ON CONFLICT (id) DO UPDATE SET ups = EXCLUDED.ups;
                            """
                            execute_values(cur, comment_query, comments_tuples)
                            
                            cur.execute("UPDATE reddit_posts SET deep_scanned = TRUE WHERE id = %s;", (p_id,))
                            conn.commit()
                            logger.info(f"   ↳ Indexed {len(comments_tuples)} text records to DB.")
                    except Exception as e:
                        conn.rollback()
                        logger.error(f"Failed to commit transaction for post {p_id}: {e}")
            
            if random.random() < 0.25:
                rest_time = random.uniform(80, 150)
                logger.info(f"Initiating defensive rest rhythm ({round(rest_time, 1)}s break)...")
                time.sleep(rest_time)

        conn.close()
        logger.info("Deep dive pipeline sequence completed.")