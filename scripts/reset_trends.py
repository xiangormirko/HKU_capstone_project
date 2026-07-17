import os
import urllib.parse
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# 1. Load database connection configurations from environment variables
load_dotenv()
db_user = os.getenv("DB_USER", "postgres")
db_password = urllib.parse.quote_plus(os.getenv("DB_PASSWORD", ""))
db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "5432")
db_name = os.getenv("DB_NAME", "capstone_db")
DATABASE_URL = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
engine = create_engine(DATABASE_URL)

# 2. Execute a highly efficient TRUNCATE command to wipe out test data
print("Truncating google_trends_data table to wipe out test entries...")
try:
    with engine.begin() as conn:
        # TRUNCATE is significantly faster than DELETE and instantly releases disk storage space
        conn.execute(text("TRUNCATE TABLE google_trends_data;")) 
    print("Success! google_trends_data is now an empty, clean table.")
except Exception as e:
    print(f"Truncation failed. Please check the table name or connection status: {e}")