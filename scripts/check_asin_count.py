# check_asin_count.py
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

try:
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME", "capstone_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432"))
    )
    cur = conn.cursor()
    
    cur.execute("""
        SELECT asin, COUNT(*) as empty_aspects_count
        FROM amazon_reviews 
        WHERE jsonb_array_length(aspects) = 0 
        GROUP BY asin 
        ORDER BY empty_aspects_count DESC;
    """)
    rows = cur.fetchall()
    
    print("\n每個 ASIN 在資料庫中的實際評論分佈：")
    print("-" * 40)
    for row in rows:
        print(f"ASIN: {row[0]} | 評論數: {row[1]} 筆")
    print("-" * 40)
    
except Exception as e:
    print(f"查詢失敗: {e}")
finally:
    if 'cur' in locals(): cur.close()
    if 'conn' in locals(): conn.close()