# create_tables.py
import os
from pathlib import Path
import psycopg2
from dotenv import load_dotenv


def create_system_tables():
    # Load environment variables from the project .env
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    # Extract connection parameters
    db_config = {
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432"))
    }

    if not db_config["password"]:
        print("Error: DB_PASSWORD is missing in your .env file!")
        return

    # Define the DDL statements for the raw ingest tables and the social analytics tables
    commands = (
        "TRUNCATE TABLE social_entities;",
        "TRUNCATE TABLE social_categories;",
        "TRUNCATE TABLE social_meta;",
        "TRUNCATE TABLE social_relationships;"
        "UPDATE reddit_posts SET pipeline_processed = FALSE;"
        """
        CREATE TABLE IF NOT EXISTS world_exports (
            year INT NOT NULL,
            code INT,
            trade_value_usd NUMERIC(20, 2) NOT NULL,
            net_weight_kg NUMERIC(20, 2),
            country VARCHAR(150),
            iso3 VARCHAR(10) NOT NULL,
            iso_numeric INT,
            region VARCHAR(100),
            PRIMARY KEY (year, iso3)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS world_imports (
            year INT NOT NULL,
            code INT,
            trade_value_usd NUMERIC(20, 2) NOT NULL,
            net_weight_kg NUMERIC(20, 2),
            country VARCHAR(150),
            iso3 VARCHAR(10) NOT NULL,
            iso_numeric INT,
            region VARCHAR(100),
            PRIMARY KEY (year, iso3)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS bilateral (
            year INT NOT NULL,
            exporter VARCHAR(150),
            exporter_iso3 VARCHAR(10) NOT NULL,
            importer VARCHAR(150),
            importer_iso3 VARCHAR(10) NOT NULL,
            trade_value_usd NUMERIC(20, 2) NOT NULL,
            PRIMARY KEY (year, exporter_iso3, importer_iso3)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS monthly_trade (
            period VARCHAR(10) NOT NULL,
            year INT NOT NULL,
            month INT NOT NULL,
            flow VARCHAR(20) NOT NULL,
            trade_value_usd NUMERIC(20, 2) NOT NULL,
            country VARCHAR(150),
            iso3 VARCHAR(10) NOT NULL,
            PRIMARY KEY (period, iso3, flow)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS reddit_posts (
            id VARCHAR(50) PRIMARY KEY,
            subreddit VARCHAR(100) NOT NULL,
            title TEXT,
            content TEXT,
            permalink TEXT,
            created_utc BIGINT,
            deep_scanned BOOLEAN DEFAULT FALSE,
            pipeline_processed BOOLEAN DEFAULT FALSE
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
        CREATE TABLE IF NOT EXISTS amazon_reviews (
            review_id VARCHAR(100) PRIMARY KEY,
            asin VARCHAR(50) NOT NULL,
            category VARCHAR(100) NOT NULL,
            rating INT,
            verified_purchase BOOLEAN DEFAULT FALSE,
            review_title TEXT,
            review_date DATE,
            review_text TEXT,
            helpful_vote_count INT DEFAULT 0,
            aspects JSONB,     
            product_title TEXT,
            product_url TEXT,
            scraped_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS social_posts (
            id VARCHAR(50) PRIMARY KEY,
            source VARCHAR(50),
            subreddit VARCHAR(100),
            title TEXT,
            content TEXT,
            permalink TEXT,
            created_utc BIGINT,
            post_sentiment NUMERIC(6, 4),
            discussion_sentiment NUMERIC(6, 4),
            n_comments INT,
            categories JSONB DEFAULT '[]'::jsonb,
            brands JSONB DEFAULT '[]'::jsonb,
            ingredients JSONB DEFAULT '[]'::jsonb,
            entities JSONB DEFAULT '{}'::jsonb,
            top_comments JSONB DEFAULT '[]'::jsonb,
            search_blob TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS social_relationships (
            id SERIAL PRIMARY KEY,
            post_id VARCHAR(50) NOT NULL,
            subreddit VARCHAR(100),
            entity_type VARCHAR(50),
            entity TEXT,
            "where" VARCHAR(20),
            mentions INT DEFAULT 1
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS social_entities (
            id SERIAL PRIMARY KEY,
            entity_type VARCHAR(50) NOT NULL,
            entity TEXT NOT NULL,
            mentions INT DEFAULT 0,
            n_posts INT DEFAULT 0,
            avg_sentiment NUMERIC(6, 4) DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS social_categories (
            id SERIAL PRIMARY KEY,
            category VARCHAR(255) NOT NULL,
            n_posts INT DEFAULT 0,
            avg_sentiment NUMERIC(6, 4) DEFAULT 0,
            top_products JSONB DEFAULT '[]'::jsonb,
            top_ingredients JSONB DEFAULT '[]'::jsonb
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS social_meta (
            id SERIAL PRIMARY KEY,
            sources JSONB,
            subreddits JSONB,
            n_posts INT DEFAULT 0,
            n_comments INT DEFAULT 0,
            n_relationships INT DEFAULT 0,
            n_entities INT DEFAULT 0,
            generated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            avg_post_sentiment NUMERIC(6, 4) DEFAULT 0
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
        print("Success: All ingest and social analytics tables have been verified/created in PostgreSQL!")
        
    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Database Error: {error}")
    finally:
        if conn is not None:
            conn.close()

if __name__ == "__main__":
    create_system_tables()