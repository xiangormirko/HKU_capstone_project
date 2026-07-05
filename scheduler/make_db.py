# make_db.py
import os
import psycopg2
from dotenv import load_dotenv

def create_database_itself():
    """
    Connects to the system default 'postgres' database and bootstraps
    the target 'capstone_db' application database cluster.
    """
    # Load environment variables from the local .env file
    load_dotenv()
    
    # Extract structural credentials and configuration tokens
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST", "localhost")
    try:
        port = int(os.getenv("DB_PORT", 5432))
    except ValueError:
        port = 5432
    
    # NOTE: Establish connection to the default system-defined 'postgres' 
    # database first to execute administrative administrative operations.
    conn = psycopg2.connect(
        dbname="postgres", 
        user=user, 
        password=password, 
        host=host, 
        port=port
    )
    
    # CRITICAL: PostgreSQL restricts 'CREATE DATABASE' commands from running 
    # inside a transaction block. Enabling autocommit bypasses transaction wrapping.
    conn.autocommit = True
    cur = conn.cursor()
    
    try:
        print("Creating database 'capstone_db'...")
        cur.execute("CREATE DATABASE capstone_db;")
        print("🚀 Success: 'capstone_db' has been created successfully!")
    except psycopg2.errors.DuplicateDatabase:
        print("💡 Notice: 'capstone_db' already exists.")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        # Resource cleanup: guarantee closure of cursor and connection objects
        cur.close()
        conn.close()

if __name__ == "__main__":
    create_database_itself()