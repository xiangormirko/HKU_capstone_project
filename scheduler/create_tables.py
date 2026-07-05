# create_tables.py
import os
import psycopg2
from dotenv import load_dotenv

def create_system_tables():
    # Load environment variables from .env
    load_dotenv()

    # Extract connection parameters
    db_config = {
        "dbname":   os.getenv("DB_NAME"),
        "user":     os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "host":     os.getenv("DB_HOST"),
        "port":     int(os.getenv("DB_PORT"))
    }

    if not db_config["password"]:
        print("❌ Error: DB_PASSWORD is missing in your .env file!")
        return

    # Define the DDL statements for our 4 tables
    commands = (
        """
        CREATE TABLE IF NOT EXISTS reddit_posts (
            id VARCHAR(50) PRIMARY KEY,
            subreddit VARCHAR(100) NOT NULL,
            title TEXT,
            content TEXT,
            permalink TEXT,
            created_utc BIGINT,
            deep_scanned BOOLEAN DEFAULT FALSE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS reddit_comments (
            id VARCHAR(50) PRIMARY KEY,
            post_id VARCHAR(50) NOT NULL,
            parent_id VARCHAR(50),
            subreddit VARCHAR(100) NOT NULL,
            body TEXT NOT NULL,
            ups INT DEFAULT 0,
            author VARCHAR(100),
            scanned_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS google_trends_data (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            country VARCHAR(10) NOT NULL,
            category VARCHAR(100) NOT NULL,
            type VARCHAR(100),
            query_id VARCHAR(100) NOT NULL,
            keyword VARCHAR(255) NOT NULL,
            score NUMERIC(5, 2),
            CONSTRAINT unique_trend_entry UNIQUE (date, country, keyword)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS amazon_reviews_data (
            review_id VARCHAR(100) PRIMARY KEY,
            asin VARCHAR(50) NOT NULL,
            title VARCHAR(255),
            rating INT,
            review_text TEXT,
            is_verified BOOLEAN DEFAULT FALSE,
            helpful_count INT DEFAULT 0,
            scraped_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    conn = None
    try:
        print(f"Connecting to PostgreSQL database '{db_config['dbname']}'...")
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        
        # Execute DDL commands one by one
        for command in commands:
            cur.execute(command)
        
        # Close communication with the PostgreSQL database server
        cur.close()
        # Commit the changes
        conn.commit()
        print("🚀 Success: All 4 data tables have been verified/created in PostgreSQL!")
        
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"❌ Database Error: {error}")
    finally:
        if conn is not None:
            conn.close()

if __name__ == "__main__":
    create_system_tables()