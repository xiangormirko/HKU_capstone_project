"""
Social discovery query layer for Product Scout.

Loads the processed Reddit data from PostgreSQL and answers
e-commerce-style queries like "oily skin remover" — resolving them to product
categories / brands / ingredients, then returning the most relevant posts with
sentiment scoring and the products mentioned in them.
"""

import os
import json
import re
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

from social_ingest import build_matchers, extract

# -------------------------------------------------------------------------
# DATABASE CONNECTION SETUP (Safely handles special characters)
# -------------------------------------------------------------------------
load_dotenv()

db_user = os.getenv("DB_USER", "postgres")
db_password = urllib.parse.quote_plus(os.getenv("DB_PASSWORD", ""))
db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "5432")
db_name = os.getenv("DB_NAME", "capstone_db")

DATABASE_URL = os.getenv("DATABASE_URL") or f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
engine = create_engine(DATABASE_URL)

STOPWORDS = {
    "the", "a", "an", "to", "for", "of", "and", "or", "my", "me", "i", "is", "in",
    "on", "with", "best", "good", "any", "what", "which", "how", "do", "does",
    "remover", "remove", "removal", "product", "products", "recommend",
    "recommendation", "recommendations", "help", "need", "want", "looking", "find",
    "skin", "skincare", "face", "routine", "use", "using", "get", "rid",
}


def _label(v):
    if v is None:
        return "n/a"
    if v >= 0.4:
        return "very positive"
    if v >= 0.1:
        return "positive"
    if v > -0.1:
        return "neutral"
    if v > -0.4:
        return "negative"
    return "very negative"


class SocialData:
    def __init__(self):
        """
        DATABASE MIGRATION: Replaced original flat JSON file loads with direct PostgreSQL queries.
        Casts database numeric types to primitive floats/ints to avoid Decimal type collisions downstream.
        """
        print("📥 Initializing SocialData: Fetching analytical layers from PostgreSQL...")

        with engine.connect() as conn:
            # 1. Load posts from social_posts table
            post_rows = conn.execute(text("SELECT * FROM social_posts")).mappings().all()
            self.posts = []
            for r in post_rows:
                p = dict(r)
                if isinstance(p.get("categories"), str): p["categories"] = json.loads(p["categories"])
                if isinstance(p.get("brands"), str): p["brands"] = json.loads(p["brands"])
                if isinstance(p.get("ingredients"), str): p["ingredients"] = json.loads(p["ingredients"])
                if isinstance(p.get("entities"), str): p["entities"] = json.loads(p["entities"])
                if isinstance(p.get("top_comments"), str): p["top_comments"] = json.loads(p["top_comments"])
                
                # Safe Type Casting
                p["post_sentiment"] = float(p["post_sentiment"]) if p["post_sentiment"] is not None else 0.0
                p["discussion_sentiment"] = float(p["discussion_sentiment"]) if p["discussion_sentiment"] is not None else 0.0
                p["n_comments"] = int(p["n_comments"]) if p["n_comments"] is not None else 0
                self.posts.append(p)

            # 2. Load global entities rollup summary
            entity_rows = conn.execute(text("SELECT * FROM social_entities")).mappings().all()
            self.entities = []
            for r in entity_rows:
                e = dict(r)
                e["mentions"] = int(e["mentions"]) if e["mentions"] is not None else 0
                e["n_posts"] = int(e["n_posts"]) if e["n_posts"] is not None else 0
                e["avg_sentiment"] = float(e["avg_sentiment"]) if e["avg_sentiment"] is not None else 0.0
                self.entities.append(e)

            # 3. Load global categories rollup summary
            cat_rows = conn.execute(text("SELECT * FROM social_categories")).mappings().all()
            self.categories = []
            for r in cat_rows:
                c = dict(r)
                if isinstance(c.get("top_products"), str): c["top_products"] = json.loads(c["top_products"])
                if isinstance(c.get("top_ingredients"), str): c["top_ingredients"] = json.loads(c["top_ingredients"])
                
                c["n_posts"] = int(c["n_posts"]) if c["n_posts"] is not None else 0
                c["avg_sentiment"] = float(c["avg_sentiment"]) if c["avg_sentiment"] is not None else 0.0
                self.categories.append(c)

            # 4. Load metadata snapshot
            meta_row = conn.execute(text("SELECT * FROM social_meta LIMIT 1")).mappings().first()
            if meta_row:
                m = dict(meta_row)
                if isinstance(m.get("sources"), str): m["sources"] = json.loads(m["sources"])
                if isinstance(m.get("subreddits"), str): m["subreddits"] = json.loads(m["subreddits"])
                
                m["n_posts"] = int(m["n_posts"]) if m["n_posts"] is not None else 0
                m["n_comments"] = int(m["n_comments"]) if m["n_comments"] is not None else 0
                m["avg_post_sentiment"] = float(m["avg_post_sentiment"]) if m["avg_post_sentiment"] is not None else 0.0
                self.meta = m
            else:
                self.meta = {"sources": ["reddit"], "subreddits": [], "n_posts": 0, "n_comments": 0}

        # PERFECT MATCH: Retaining original underscore naming contracts used by downstream methods
        self.matchers = build_matchers()
        self._by_id = {p["id"]: p for p in self.posts}
        self._ent_sent = {(e["entity_type"], e["entity"]): e for e in self.entities}

        print(f"✅ Successfully cached {len(self.posts)} processed posts from database into memory.")

    # ---------- overview for the discovery landing ----------
    def overview(self):
        def by_type(t, n):
            return [e for e in self.entities if e["entity_type"] == t][:n]
        return {
            "meta": self.meta,
            "insights": self.launch_insights(),
            "categories": self.categories,
            "top_brands": by_type("brand", 12),
            "top_ingredients": by_type("ingredient", 12),
            "example_queries": [
                "oily skin remover", "dark spots and hyperpigmentation",
                "gentle cleanser for sensitive skin", "retinol for wrinkles",
                "korean sunscreen", "fungal acne safe moisturizer",
            ],
        }

    # ---------- launch-opportunity insights ----------
    def launch_insights(self, n=4):
        """Trending categories + a product-launch opportunity read.

        Signal = demand (conversation volume) blended with an unmet-need bonus
        (lower consumer sentiment in a high-volume category = white space).
        Timestamps span only ~2 weeks, so we deliberately rank by demand, not a
        fabricated time-trend.
        """
        cats = self.categories
        if not cats:
            return {"headline": {}, "opportunities": []}
        max_posts = max(c["n_posts"] for c in cats) or 1

        scored = []
        for c in cats:
            s = c["avg_sentiment"] or 0.0
            demand = c["n_posts"] / max_posts
            unmet = max(0.0, 0.25 - s)            # bonus when satisfaction is low
            scored.append((demand * (1 + unmet * 2.5), c))
        scored.sort(key=lambda x: x[0], reverse=True)

        opps = []
        for score, c in scored[:n]:
            s = c["avg_sentiment"] or 0.0
            if s >= 0.25:
                angle = "Validated demand"
                why = "shoppers are enthusiastic — a proven market to enter with a strong product"
            elif s >= 0.1:
                angle = "Room to differentiate"
                why = "high interest but only mild satisfaction — a better formulation can stand out"
            else:
                angle = "Unmet need"
                why = "lots of discussion but low satisfaction — clear white space for a product that delivers"
            opps.append({
                "category": c["category"],
                "n_posts": c["n_posts"],
                "avg_sentiment": c["avg_sentiment"],
                "sentiment_label": _label(c["avg_sentiment"]),
                "angle": angle,
                "rationale": f"{c['n_posts']} conversations — {why}.",
                "incumbents": c["top_products"][:3],
                "opportunity_score": round(score, 3),
            })

        m = self.meta
        return {
            "headline": {
                "n_posts": m.get("n_posts"),
                "n_comments": m.get("n_comments"),
                "n_categories": len(cats),
                "overall_sentiment": m.get("avg_post_sentiment"),
                "overall_label": _label(m.get("avg_post_sentiment")),
                "top_category": cats[0]["category"] if cats else None,
            },
            "opportunities": opps,
        }

    # ---------- search ----------
    def search(self, query, limit=25):
        q = (query or "").strip()
        if not q:
            return {"query": q, "resolved": {}, "summary": {}, "results": []}

        targets = extract(q, self.matchers)            # {etype: Counter}
        target_set = {(et, name) for et, c in targets.items() for name in c}
        tokens = [t for t in re.findall(r"[a-z0-9]+", q.lower())
                  if t not in STOPWORDS and len(t) > 2]

        scored = []
        for p in self.posts:
            score = 0.0
            # entity overlap (strong signal)
            for et, ents in p["entities"].items():
                for e in ents:
                    if (et, e["name"]) in target_set:
                        w = 5 if et != "category" else 4
                        score += w + min(e["mentions"], 4) * 0.5
            # free-text relevance
            title_low = p["title"].lower()
            blob = p["search_blob"]
            for t in tokens:
                if t in title_low:
                    score += 3
                hits = blob.count(t)
                if hits:
                    score += min(hits, 5) * 0.6
            if score > 0:
                scored.append((score, p))

        scored.sort(key=lambda x: (x[0], x[1]["n_comments"]), reverse=True)
        top = scored[:limit]

        # aggregate "potential products" across the matched posts
        brand_ct, ing_ct = Counter(), Counter()
        sent_vals = []
        for _, p in top:
            brand_ct.update(p["brands"])
            ing_ct.update(p["ingredients"])
            sent_vals.append(p["post_sentiment"])

        def products(counter, etype):
            out = []
            for name, n in counter.most_common(8):
                es = self._ent_sent.get((etype, name), {})
                out.append({"name": name, "mentions_in_results": n,
                            "avg_sentiment": es.get("avg_sentiment"),
                            "sentiment_label": _label(es.get("avg_sentiment"))})
            return out

        avg_sent = round(sum(sent_vals) / len(sent_vals), 4) if sent_vals else None

        return {
            "query": q,
            "resolved": {et: list(c.keys()) for et, c in targets.items()},
            "summary": {
                "n_results": len(top),
                "avg_sentiment": avg_sent,
                "sentiment_label": _label(avg_sent),
                "top_products": products(brand_ct, "brand"),
                "top_ingredients": products(ing_ct, "ingredient"),
            },
            "results": [self._result_card(p, score) for score, p in top],
        }

    # ---------- compact helpers for the Claude agent ----------
    def agent_search(self, query, limit=8):
        """Trimmed search result suitable for an LLM tool response."""
        r = self.search(query, limit=limit)
        s = r["summary"]
        return {
            "query": r["query"],
            "resolved_to": r["resolved"],
            "n_matching_posts": s.get("n_results", 0),
            "overall_sentiment": s.get("avg_sentiment"),
            "overall_sentiment_label": s.get("sentiment_label"),
            "top_products": [{"name": p["name"], "mentions": p["mentions_in_results"],
                              "sentiment": p["avg_sentiment"], "label": p["sentiment_label"]}
                             for p in s.get("top_products", [])],
            "top_ingredients": [{"name": p["name"], "mentions": p["mentions_in_results"],
                                 "sentiment": p["avg_sentiment"], "label": p["sentiment_label"]}
                                for p in s.get("top_ingredients", [])],
            "sample_posts": [{"title": c["title"], "subreddit": c["subreddit"],
                              "post_sentiment": c["post_sentiment"],
                              "discussion_sentiment": c["discussion_sentiment"],
                              "brands": c["brands"][:4], "n_comments": c["n_comments"]}
                             for c in r["results"][:6]],
        }

    def agent_overview(self):
        return {
            "sources": self.meta.get("sources"),
            "n_posts": self.meta.get("n_posts"),
            "n_comments": self.meta.get("n_comments"),
            "categories": [{"category": c["category"], "n_posts": c["n_posts"],
                            "avg_sentiment": c["avg_sentiment"],
                            "top_products": c["top_products"][:4]} for c in self.categories],
            "top_brands": [{"name": e["entity"], "mentions": e["mentions"],
                            "n_posts": e["n_posts"], "sentiment": e["avg_sentiment"]}
                           for e in self.entities if e["entity_type"] == "brand"][:12],
            "top_ingredients": [{"name": e["entity"], "mentions": e["mentions"],
                                 "n_posts": e["n_posts"], "sentiment": e["avg_sentiment"]}
                                for e in self.entities if e["entity_type"] == "ingredient"][:12],
        }

    def product_sentiment(self, name):
        """Fuzzy-find a brand / ingredient / category and return its sentiment rollup."""
        key = (name or "").strip().lower()
        if not key:
            return {"error": "empty name"}
        # exact then substring match across all entities
        cand = [e for e in self.entities if e["entity"].lower() == key] or \
               [e for e in self.entities if key in e["entity"].lower()]
        if not cand:
            return {"error": f"'{name}' not found among tracked products/ingredients/categories."}
        e = max(cand, key=lambda x: x["mentions"])
        return {"name": e["entity"], "type": e["entity_type"], "mentions": e["mentions"],
                "n_posts": e["n_posts"], "avg_sentiment": e["avg_sentiment"],
                "sentiment_label": _label(e["avg_sentiment"])}

    def _result_card(self, p, score):
        top_comment = None
        if p["top_comments"]:
            tc = p["top_comments"][0]
            top_comment = {"body": tc["body"], "ups": tc["ups"],
                           "sentiment": tc["sentiment"], "label": _label(tc["sentiment"])}
        return {
            "id": p["id"], "source": p["source"], "subreddit": p["subreddit"],
            "title": p["title"],
            "snippet": (p["content"][:240] + "…") if len(p["content"]) > 240 else p["content"],
            "permalink": ("https://reddit.com" + p["permalink"]) if p.get("permalink", "").startswith("/") else p.get("permalink"),
            "post_sentiment": p["post_sentiment"],
            "post_sentiment_label": _label(p["post_sentiment"]),
            "discussion_sentiment": p["discussion_sentiment"],
            "discussion_label": _label(p["discussion_sentiment"]),
            "n_comments": p["n_comments"],
            "categories": p["categories"],
            "brands": p["brands"],
            "ingredients": p["ingredients"],
            "top_comment": top_comment,
            "relevance": round(score, 1),
        }

    # ---------- category page bundle (Amazon + Trends + Reddit) ----------
    def category_page(self, name):
        from amazon import get_amazon
        from trends import get_trends
        amazon = get_amazon().category(name)
        reddit = self.search(name, limit=6)
        cat = next((c for c in self.categories if c["category"] == name), None)
        return {
            "category": name,
            "social_summary": {
                "n_posts": cat["n_posts"] if cat else 0,
                "avg_sentiment": cat["avg_sentiment"] if cat else None,
                "sentiment_label": _label(cat["avg_sentiment"]) if cat else "n/a",
                "top_products": cat["top_products"] if cat else [],
                "top_ingredients": cat["top_ingredients"] if cat else [],
            },
            "amazon": amazon,
            "trends": get_trends().category_block(name),
            "reddit": {
                "summary": reddit["summary"],
                "posts": reddit["results"][:5],
            },
        }

_social = None


def get_social():
    global _social
    if _social is None:
        _social = SocialData()
    return _social