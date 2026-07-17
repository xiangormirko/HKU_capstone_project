"""
Amazon reviews intelligence for Product Scout category pages.

DATABASE MIGRATION UPDATE: 
Replaced local JSON flat file imports with a direct PostgreSQL connection.
Dynamically reconstructs the original JSON schema to maintain backward-compatibility
with upstream analytics algorithms (_analyze, _voice_of_customer, etc.).
"""

import html
import json
import math
import os
import re
import urllib.parse
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from social_taxonomy import BRANDS

# -------------------------------------------------------------------------
# DATABASE ENGINE SETUP (Matching analytics.py configuration)
# -------------------------------------------------------------------------
load_dotenv()

db_user = os.getenv("DB_USER", "postgres")
db_password = urllib.parse.quote_plus(os.getenv("DB_PASSWORD", ""))
db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "5432")
db_name = os.getenv("DB_NAME", "capstone_db")

DATABASE_URL = os.getenv("DATABASE_URL") or f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
engine = create_engine(DATABASE_URL)

_BRAND_FORMS = sorted(
    ((form, canon) for canon, forms in BRANDS.items() for form in forms),
    key=lambda x: -len(x[0]),
)

# Normalize near-duplicate aspect names for category aggregation
ASPECT_SYNONYMS = {
    "gentle": "Gentleness",
    "gentleness": "Gentleness",
    "fragrance": "Fragrance",
    "fragrance-free": "Fragrance-free",
    "fragrance free": "Fragrance-free",
    "non-greasy": "Greasiness",
    "greasiness": "Greasiness",
    "non greasy": "Greasiness",
    "skin compatibility": "Skin compatibility",
    "skin irritation": "Skin irritation",
    "value for money": "Value for money",
}


def clean(text_str):
    if not text_str:
        return ""
    t = html.unescape(str(text_str))
    # Handle occasional double-concatenation bug in scraping pipeline
    half = len(t) // 2
    if half > 30 and t[:half].strip() and t[:half].strip() == t[half:].strip():
        t = t[:half]
    return re.sub(r"\s+", " ", t).strip()


def brand_of(title):
    low = (title or "").lower()
    for form, canon in _BRAND_FORMS:
        if form in low:
            return canon
    return (title or "").split(",")[0].split()[0] if title else "?"


def norm_aspect(name):
    return ASPECT_SYNONYMS.get(
        (name or "").strip().lower(), (name or "").strip().capitalize()
    )


class AmazonData:
    def __init__(self):
        # In-memory cache to prevent redundant database hits on refresh
        self._cache = {}

    def _load_from_db(self, category_name):
        """
        Queries raw Amazon review records from PostgreSQL for a specific category.
        Re-maps column names back to original JSON CamelCase schema to feed downstream parser.
        """
        query = text("""
            SELECT 
                review_id AS "reviewId",
                asin AS "productAsin",
                rating,
                verified_purchase AS "verifiedPurchase",
                review_title AS "reviewTitle",
                review_date::text AS "reviewDate",
                review_text AS "reviewText",
                helpful_vote_count AS "helpfulVoteCount",
                aspects,
                product_title AS "productTitle",
                product_url AS "productUrl"
            FROM amazon_reviews
            WHERE category = :category
        """)

        reviews = []
        try:
            with engine.connect() as conn:
                result = conn.execute(query, {"category": category_name})
                for row in result.mappings():
                    r_dict = dict(row)
                    
                    # Safely deserialize JSONB structure of 'aspects' if retrieved as a string
                    if isinstance(r_dict["aspects"], str):
                        try:
                            r_dict["aspects"] = json.loads(r_dict["aspects"])
                        except Exception:
                            r_dict["aspects"] = []
                    elif r_dict["aspects"] is None:
                        r_dict["aspects"] = []
                        
                    reviews.append(r_dict)
        except Exception as e:
            print(f"Database Query Error (Amazon Reviews): {e}")
            return [] # Return empty list on connection/query failure

        return reviews

    def available_categories(self):
        """
        Fetches categories directly from database to support dynamic front-end menus.
        Falls back to hardcoded project defaults if table is empty.
        """
        default_categories = [
            "Sunscreen / SPF",
            "Moisturizer & Hydration",
            "Cleanser & Oil Control",
        ]
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT DISTINCT category FROM amazon_reviews")
                )
                categories = [row[0] for row in result.fetchall() if row[0]]
                return categories if categories else default_categories
        except Exception:
            return default_categories

    def category(self, name):
        """
        Main entrypoint to fetch analytics payload for a given skincare category.
        """
        if name in self._cache:
            return self._cache[name]

        reviews = self._load_from_db(name)
        if not reviews:
            return {"available": False, "category": name}

        result = self._analyze(name, reviews)
        self._cache[name] = result
        return result

    # -------------------------------------------------------------------------
    # AGENT CORE SUMMARY
    # -------------------------------------------------------------------------
    def agent_summary(self, name):
        d = self.category(name)
        if not d.get("available"):
            return {
                "available": False,
                "note": f"No Amazon reviews found for '{name}'. Active categories: "
                f"{self.available_categories()}",
            }
        sm = d["summary"]
        return {
            "available": True,
            "category": name,
            "source": d["meta"]["source"],
            "avg_rating_weighted": sm["avg_rating_weighted"],
            "n_products": sm["n_products"],
            "total_ratings": sm["total_ratings"],
            "top_painpoint": sm["top_painpoint"],
            "top_strength": sm["top_strength"],
            "best_in_class": sm["best_product"],
            "products": [
                {
                    "brand": p["brand"],
                    "avg_rating": p["avg_rating"],
                    "total_ratings": p["total_ratings"],
                    "aspect_negative_rate": p["overall_neg_rate"],
                    "weakest_aspect": p["dominant_negative"],
                    "ai_summary": (p["ai_summary"] or "")[:300],
                }
                for p in d["products"]
            ],
            "category_pain_points": [
                {
                    "aspect": a["name"],
                    "neg_rate": a["neg_rate"],
                    "mentions": a["mentions"],
                }
                for a in d["category_aspects"]
                if a["neg_rate"] >= 25
            ][:6],
        }

    # -------------------------------------------------------------------------
    # DOWNSTREAM ENGINE (Completely unchanged & 100% preserved)
    # -------------------------------------------------------------------------
    def _analyze(self, name, reviews):
        by_asin = defaultdict(list)
        for r in reviews:
            by_asin[r["productAsin"]].append(r)

        products = []
        cat_aspects = defaultdict(lambda: {"mentions": 0, "pos": 0, "neg": 0})

        for asin, revs in by_asin.items():
            head = revs[0]
            aspects = []
            tot_m = tot_n = 0
            for a in head.get("aspects") or []:
                m = a.get("aspectMention", 0) or 0
                neg = a.get("aspectMentionNegative", 0) or 0
                pos = a.get("aspectMentionPositive", 0) or 0
                if m <= 0:
                    continue
                nr = round(neg / m * 100, 1)
                aspects.append(
                    {
                        "name": a["aspectName"],
                        "mentions": m,
                        "pos": pos,
                        "neg": neg,
                        "neg_rate": nr,
                        "sentiment": a.get("aspectSentiment"),
                        "summary": clean(a.get("aspectSummary")),
                    }
                )
                tot_m += m
                tot_n += neg

                k = norm_aspect(a["aspectName"])
                cat_aspects[k]["mentions"] += m
                cat_aspects[k]["pos"] += pos
                cat_aspects[k]["neg"] += neg

            aspects.sort(key=lambda x: -x["mentions"])
            neg_aspects = [a for a in aspects if a["mentions"] >= 3]
            neg_aspects.sort(key=lambda x: -x["neg_rate"])
            dom_neg = neg_aspects[0]["name"] if neg_aspects else "None"

            valid_ratings = [
                r["rating"]
                for r in revs
                if r.get("rating") is not None and 1 <= r["rating"] <= 5
            ]
            avg_r = (
                round(sum(valid_ratings) / len(valid_ratings), 2)
                if valid_ratings
                else 0.0
            )

            products.append(
                {
                    "asin": asin,
                    "title": head.get("productTitle") or "Unknown Product",
                    "brand": brand_of(head.get("productTitle")),
                    "url": head.get("productUrl") or "#",
                    "avg_rating": avg_r,
                    "total_ratings": len(valid_ratings),
                    "overall_neg_rate": (
                        round(tot_n / tot_m * 100, 1) if tot_m > 0 else 0.0
                    ),
                    "dominant_negative": dom_neg,
                    "aspects": aspects,
                    "ai_summary": head.get("reviewsAISummary") or "",
                }
            )

        products.sort(key=lambda x: -x["total_ratings"])
        return self._summary(name, products, cat_aspects)

    def _summary(self, name, products, cat_aspects):
        flat_aspects = []
        for k, v in cat_aspects.items():
            m = v["mentions"]
            nr = round(v["neg"] / m * 100, 1) if m > 0 else 0.0
            flat_aspects.append(
                {"name": k, "mentions": m, "pos": v["pos"], "neg": v["neg"], "neg_rate": nr}
            )
        flat_aspects.sort(key=lambda x: -x["mentions"])

        p_list = [a["name"] for a in flat_aspects if a["mentions"] >= 5]
        p_list.sort(key=lambda x: -cat_aspects[x]["neg"] / cat_aspects[x]["mentions"])
        top_pain = p_list[0] if p_list else "None"

        s_list = [a["name"] for a in flat_aspects if a["mentions"] >= 5]
        s_list.sort(key=lambda x: -cat_aspects[x]["pos"] / cat_aspects[x]["mentions"])
        top_str = s_list[0] if s_list else "None"

        best_p = products[0]["title"] if products else "None"
        products_by_rating = sorted(products, key=lambda x: -x["avg_rating"])
        if products_by_rating:
            best_p = f"{products_by_rating[0]['brand']} ({products_by_rating[0]['avg_rating']}★)"

        tot_ratings = sum(p["total_ratings"] for p in products)
        weighted_sum = sum(p["avg_rating"] * p["total_ratings"] for p in products)
        weighted_avg = (
            round(weighted_sum / tot_ratings, 2) if tot_ratings > 0 else 0.0
        )

        return {
            "available": True,
            "category": name,
            "meta": {"source": "PostgreSQL Database"},
            "summary": {
                "n_products": len(products),
                "total_ratings": tot_ratings,
                "avg_rating_weighted": weighted_avg,
                "top_painpoint": top_pain,
                "top_strength": top_str,
                "best_product": best_p,
            },
            "products": products,
            "category_aspects": flat_aspects,
        }


# Global Singleton for caching
_amazon = None


def get_amazon():
    global _amazon
    if _amazon is None:
        _amazon = AmazonData()
    return _amazon