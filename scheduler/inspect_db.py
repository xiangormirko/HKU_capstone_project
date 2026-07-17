import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Automatically load environment variables from the .env file
load_dotenv()

def get_db_config():
    """
    Reads database connection credentials from environment variables.
    Provides fallback defaults and ensures type compliance.
    """
    try:
        return {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", 5432)), # psycopg2 requires port to be an integer
            "dbname": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD")
        }
    except ValueError:
        print("Error: DB_PORT in .env must be a valid integer.")
        return None

def inspect_current_database():
    """
    Connects to the PostgreSQL database, lists all active tables, 
    tracks total row counts, and previews data structures.
    """
    db_config = get_db_config()
    if not db_config or not db_config["dbname"]:
        print("Error: Missing required database environment variables. Check your .env file.")
        return

    print("=== Initializing Database Inspection from .env ===")
    conn = None
    try:
        # 1. Establish secure database connection
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 2. Query all user-defined base tables within the public schema
        table_query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE';
        """
        cur.execute(table_query)
        tables = [row['table_name'] for row in cur.fetchall()]
        
        if not tables:
            print("ℹInfo: Connection successful, but the 'public' schema contains no tables.")
            return

        print(f"Connected! Found {len(tables)} active table(s): {', '.join(tables)}\n")
        print("-" * 60)

        # 3. Iterate through discovered tables to analyze data distribution
        for table in tables:
            # Fetch the total record count dynamically
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            total_rows = cur.fetchone()['count']
            print(f"Table: [{table}] | Total Records: {total_rows}")
            
            if total_rows > 0:
                # Fetch a sample slice (Top 5 rows) for structural preview
                print(f"Previewing top 5 records from [{table}]:")
                cur.execute(f"SELECT * FROM {table} LIMIT 5;")
                rows = cur.fetchall()
                
                for idx, row in enumerate(rows, 1):
                    # Printed as standard Python dicts for high readability
                    print(f" Row #{idx}: {dict(row)}")
            else:
                print(f" (Table is currently empty)")
                
            print("-" * 60)

    except Exception as e:
        print(f"Critical: Database connection or query failed: {str(e)}")
        
    finally:
        # 4. Safe cleanup of open system resources
        if conn:
            cur.close()
            conn.close()
            print("=== Database Connection Safely Closed ===")

if __name__ == "__main__":
    inspect_current_database()