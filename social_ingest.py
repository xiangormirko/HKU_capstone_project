"""
Social Ingestion + Entity/Sentiment Pipeline for Product Scout (PostgreSQL Engine).
Role: Scheduler 2 (Consumer/Transformer)

Input: Enriched raw posts from `reddit_posts` where deep_scan = TRUE and pipeline_processed = FALSE.
Output: Processed relational/JSONB analytics stored into PostgreSQL target tables:
        - social_posts
        - social_relationships
        - social_entities
        - social_categories
        - social_meta
"""

import os
import json
import re
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from social_taxonomy import TAXONOMY

# -------------------------------------------------------------------------
# DATABASE CONNECTION SETUP (Safely handles special characters like '+')
# -------------------------------------------------------------------------
load_dotenv()

db_user = os.getenv("DB_USER", "postgres")
db_password = urllib.parse.quote_plus(os.getenv("DB_PASSWORD", ""))
db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "5432")
db_name = os.getenv("DB_NAME", "capstone_db")

# Fallback to explicit DATABASE_URL if available, otherwise auto-construct safely
DATABASE_URL = os.getenv("DATABASE_URL") or f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

if not DATABASE_URL:
    print("Error: Missing database configurations in .env file.")
    sys.exit(1)

engine = create_engine(DATABASE_URL)
analyzer = SentimentIntensityAnalyzer()

# ───────────────────────── ENTITY MATCHER (UNCHANGED) ─────────────────────────

def build_matchers():
    """For each entity type, compile one regex + a surface-form -> canonical map."""
    matchers = {}
    for etype, mapping in TAXONOMY.items():
        syn2canon = {}
        for canon, syns in mapping.items():
            for s in syns:
                syn2canon[s.lower()] = canon
        forms = sorted(syn2canon, key=len, reverse=True)
        pattern = "|".join(re.escape(f) for f in forms)
        rx = re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" % pattern, re.IGNORECASE)
        matchers[etype] = (rx, syn2canon)
    return matchers

def extract(text, matchers):
    """text -> {etype: Counter(canonical -> mentions)}."""
    low = text.lower()
    found = {}
    for etype, (rx, syn2canon) in matchers.items():
        c = Counter()
        for m in rx.finditer(low):
            canon = syn2canon.get(m.group(0))
            if canon:
                c[canon] += 1
        if c:
            found[etype] = c
    return found

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

def split_sentences(text):
    return [s.strip() for s in SENT_SPLIT.split(text or "") if s.strip()]

def analyze_text(text, matchers):
    """Return (doc_sentiment, mentions{type:Counter}, contexts[(type,name,sent)])."""
    sents = split_sentences(text)
    if not sents:
        return 0.0, {}, []
    comps = []
    mentions = defaultdict(Counter)
    contexts = []
    for s in sents:
        sc = analyzer.polarity_scores(s[:1000])["compound"]
        comps.append(sc)
        for et, counter in extract(s, matchers).items():
            for name, cnt in counter.items():
                mentions[et][name] += cnt
            contexts.append((et, name, sc))
    return round(sum(comps) / len(comps), 4), mentions, contexts


def ensure_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
    return list(value)


def merge_top_items(existing_values, new_values):
    merged = []
    seen = set()
    for value in list(ensure_list(existing_values)) + list(ensure_list(new_values)):
        if value is None:
            continue
        key = str(value)
        if key not in seen:
            merged.append(value)
            seen.add(key)
    return merged[:5]


def upsert_entity_row(conn, entity_type, entity, mentions, n_posts, avg_sentiment):
    existing = conn.execute(text("""
        SELECT mentions, n_posts, avg_sentiment
        FROM social_entities
        WHERE entity_type = :entity_type AND entity = :entity
    """), {"entity_type": entity_type, "entity": entity}).mappings().first()

    if existing:
        total_mentions = (existing["mentions"] or 0) + (mentions or 0)
        total_posts = (existing["n_posts"] or 0) + (n_posts or 0)
        
        existing_avg = float(existing["avg_sentiment"]) if existing["avg_sentiment"] is not None else 0.0
        new_avg = float(avg_sentiment or 0.0)
        
        weighted_avg = (
            ((existing["mentions"] or 0) * existing_avg) +
            ((mentions or 0) * new_avg)
        ) / total_mentions if total_mentions else 0.0

        conn.execute(text("""
            UPDATE social_entities
            SET mentions = :mentions,
                n_posts = :n_posts,
                avg_sentiment = :avg_sentiment
            WHERE entity_type = :entity_type AND entity = :entity
        """), {
            "entity_type": entity_type,
            "entity": entity,
            "mentions": total_mentions,
            "n_posts": total_posts,
            "avg_sentiment": round(weighted_avg, 4),
        })
    else:
        conn.execute(text("""
            INSERT INTO social_entities (entity_type, entity, mentions, n_posts, avg_sentiment)
            VALUES (:entity_type, :entity, :mentions, :n_posts, :avg_sentiment)
        """), {
            "entity_type": entity_type,
            "entity": entity,
            "mentions": mentions,
            "n_posts": n_posts,
            "avg_sentiment": round(avg_sentiment, 4),
        })


def upsert_category_row(conn, category, n_posts, avg_sentiment, top_products, top_ingredients):
    existing = conn.execute(text("""
        SELECT n_posts, avg_sentiment, top_products, top_ingredients
        FROM social_categories
        WHERE category = :category
    """), {"category": category}).mappings().first()

    if existing:
        total_posts = (existing["n_posts"] or 0) + (n_posts or 0)
        
        existing_avg = float(existing["avg_sentiment"]) if existing["avg_sentiment"] is not None else 0.0
        new_avg = float(avg_sentiment or 0.0)
        
        weighted_avg = (
            ((existing["n_posts"] or 0) * existing_avg) +
            ((n_posts or 0) * new_avg)
        ) / total_posts if total_posts else 0.0

        merged_products = merge_top_items(existing["top_products"], top_products)
        merged_ingredients = merge_top_items(existing["top_ingredients"], top_ingredients)

        conn.execute(text("""
            UPDATE social_categories
            SET n_posts = :n_posts,
                avg_sentiment = :avg_sentiment,
                top_products = :top_products,
                top_ingredients = :top_ingredients
            WHERE category = :category
        """), {
            "category": category,
            "n_posts": total_posts,
            "avg_sentiment": round(weighted_avg, 4),
            "top_products": json.dumps(merged_products),
            "top_ingredients": json.dumps(merged_ingredients),
        })
    else:
        conn.execute(text("""
            INSERT INTO social_categories (category, n_posts, avg_sentiment, top_products, top_ingredients)
            VALUES (:category, :n_posts, :avg_sentiment, :top_products, :top_ingredients)
        """), {
            "category": category,
            "n_posts": n_posts,
            "avg_sentiment": round(avg_sentiment, 4),
            "top_products": json.dumps(merge_top_items([], top_products)),
            "top_ingredients": json.dumps(merge_top_items([], top_ingredients)),
        })


def upsert_meta_row(conn, sources, subreddits, n_posts, n_comments, n_relationships, n_entities, avg_post_sentiment):
    existing = conn.execute(text("""
        SELECT generated_at
        FROM social_meta
        ORDER BY generated_at DESC NULLS LAST
        LIMIT 1
    """)).mappings().first()

    if existing:
        conn.execute(text("""
            UPDATE social_meta
            SET sources = :sources,
                subreddits = :subreddits,
                n_posts = :n_posts,
                n_comments = :n_comments,
                n_relationships = :n_relationships,
                n_entities = :n_entities,
                generated_at = CURRENT_TIMESTAMP,
                avg_post_sentiment = :avg_post_sentiment
            WHERE generated_at = :generated_at
        """), {
            "sources": json.dumps(sorted(set(ensure_list(sources)))),
            "subreddits": json.dumps(sorted(set(ensure_list(subreddits)))),
            "n_posts": n_posts,
            "n_comments": n_comments,
            "n_relationships": n_relationships,
            "n_entities": n_entities,
            "avg_post_sentiment": round(avg_post_sentiment, 4),
            "generated_at": existing["generated_at"],
        })
    else:
        conn.execute(text("""
            INSERT INTO social_meta (
                sources, subreddits, n_posts, n_comments, n_relationships, n_entities, generated_at, avg_post_sentiment
            )
            VALUES (
                :sources, :subreddits, :n_posts, :n_comments, :n_relationships, :n_entities, CURRENT_TIMESTAMP, :avg_post_sentiment
            )
        """), {
            "sources": json.dumps(sorted(set(ensure_list(sources)))),
            "subreddits": json.dumps(sorted(set(ensure_list(subreddits)))),
            "n_posts": n_posts,
            "n_comments": n_comments,
            "n_relationships": n_relationships,
            "n_entities": n_entities,
            "avg_post_sentiment": round(avg_post_sentiment, 4),
        })

# ───────────────────────── MAIN PIPELINE ─────────────────────────

def run():
    """
    Main ingestion pipeline extracting deep-scanned raw records,
    processing text-based NLP data, and pushing outputs to relational snapshots.
    """
    matchers = build_matchers()

    # -------------------------------------------------------------------------
    # STEP 1: Fetch raw posts where deep_scanned = TRUE and pipeline_processed = FALSE
    # -------------------------------------------------------------------------
    print("Querying deep-scanned raw posts from database...")
    with engine.connect() as conn:
        post_rows = conn.execute(text(
            "SELECT id, subreddit, title, content, permalink, created_utc "
            "FROM reddit_posts WHERE deep_scanned = TRUE AND pipeline_processed = FALSE LIMIT 500"
        )).mappings().all()

        if not post_rows:
            print("No new deep-scanned raw reddit posts available for NLP processing. Exiting.")
            return

        posts_in = {r["id"]: dict(r) for r in post_rows}
        post_ids = tuple(posts_in.keys())

        # -------------------------------------------------------------------------
        # STEP 2: Fetch related comments for this active batch
        # -------------------------------------------------------------------------
        print(f"Fetching raw comments for {len(post_ids)} active posts...")
        comment_rows = conn.execute(text(
            "SELECT id, post_id, body, ups, author FROM reddit_comments WHERE post_id IN :pids"
        ), {"pids": post_ids}).mappings().all()

        comments_by_post = defaultdict(list)
        total_comments_count = 0
        for c in comment_rows:
            comments_by_post[c["post_id"]].append(dict(c))
            total_comments_count += 1

    # Containers for relational structures matching original schemas
    posts_out = []
    rel_rows = []
    entity_stat = defaultdict(lambda: {"mentions": 0, "posts": set(), "sent_sum": 0.0, "sent_n": 0})

    def add_mentions(etype, name, n, post_id):
        s = entity_stat[(etype, name)]
        s["mentions"] += n
        s["posts"].add(post_id)

    def add_context(etype, name, sent):
        s = entity_stat[(etype, name)]
        s["sent_sum"] += sent
        s["sent_n"] += 1

    # -------------------------------------------------------------------------
    # CORE PROCESSING LOOP (VADER Sentiment & Entity Aggregation)
    # -------------------------------------------------------------------------
    print("Processing NLP analytics layers...")
    for pid, p in posts_in.items():
        title = p.get("title", "") or ""
        content = p.get("content", "") or ""
        post_text = f"{title}. {content}".strip()
        
        post_sent, post_ments, post_ctx = analyze_text(post_text, matchers)
        for et, name, sc in post_ctx:
            add_context(et, name, sc)

        clist = sorted(comments_by_post.get(pid, []), key=lambda c: c.get("ups", 0) or 0, reverse=True)
        comment_blob = []
        comment_ments = {}
        wsent_num = wsent_den = 0.0
        top_comments = []

        for c in clist:
            body = c.get("body", "") or ""
            cs, c_ments, c_ctx = analyze_text(body, matchers)
            ups = c.get("ups", 0) or 0
            w = ups + 1
            wsent_num += cs * w
            wsent_den += w
            comment_blob.append(body)

            for et, cnt in c_ments.items():
                comment_ments.setdefault(et, Counter()).update(cnt)
            for et, name, sc in c_ctx:
                add_context(et, name, sc)

            if len(top_comments) < 5:
                top_comments.append({"body": body[:400], "ups": ups, "sentiment": cs})

        discussion_sent = round(wsent_num / wsent_den, 4) if wsent_den else None

        merged = {}
        for et in set(post_ments) | set(comment_ments):
            pc = post_ments.get(et, Counter())
            cc = comment_ments.get(et, Counter())
            merged[et] = []
            for name in set(pc) | set(cc):
                pm, cm = pc.get(name, 0), cc.get(name, 0)
                where = "both" if pm and cm else ("post" if pm else "comment")
                merged[et].append({"name": name, "mentions": pm + cm, "where": where})
                rel_rows.append({
                    "post_id": pid,
                    "subreddit": p.get("subreddit"),
                    "entity_type": et,
                    "entity": name,
                    "where": where,
                    "mentions": pm + cm
                })
                add_mentions(et, name, pm + cm, pid)
            merged[et].sort(key=lambda x: x["mentions"], reverse=True)

        posts_out.append({
            "id": pid,
            "source": "reddit",
            "subreddit": p.get("subreddit"),
            "title": title,
            "content": content[:1200],
            "permalink": p.get("permalink"),
            "created_utc": p.get("created_utc"),
            "post_sentiment": post_sent,
            "discussion_sentiment": discussion_sent,
            "n_comments": len(clist),
            "categories": [e["name"] for e in merged.get("category", [])],
            "brands": [e["name"] for e in merged.get("brand", [])],
            "ingredients": [e["name"] for e in merged.get("ingredient", [])],
            "entities": merged,
            "top_comments": top_comments,
            "search_blob": (post_text + " " + " ".join(comment_blob))[:6000].lower(),
        })

    # ---------- Global Entity Rollup Summary ----------
    entities = []
    for (etype, name), s in entity_stat.items():
        entities.append({
            "entity_type": etype,
            "entity": name,
            "mentions": s["mentions"],
            "n_posts": len(s["posts"]),
            "avg_sentiment": round(s["sent_sum"] / s["sent_n"], 4) if s["sent_n"] else 0.0,
        })
    entities.sort(key=lambda e: e["mentions"], reverse=True)
    ent_sent = {(e["entity_type"], e["entity"]): e["avg_sentiment"] for e in entities}

    # ---------- Global Category Rollup Summary ----------
    cat_stat = {}
    for post in posts_out:
        for cat in post["categories"]:
            cs = cat_stat.setdefault(cat, {"posts": 0, "products": Counter(), "ingredients": Counter()})
            cs["posts"] += 1
            cs["products"].update(post["brands"])
            cs["ingredients"].update(post["ingredients"])

    categories = []
    for name, cs in cat_stat.items():
        categories.append({
            "category": name,
            "n_posts": cs["posts"],
            "avg_sentiment": ent_sent.get(("category", name), 0.0),
            "top_products": [b for b, _ in cs["products"].most_common(5)],
            "top_ingredients": [i for i, _ in cs["ingredients"].most_common(5)],
        })
    categories.sort(key=lambda c: c["n_posts"], reverse=True)

    # -------------------------------------------------------------------------
    # STEP 3: Persist Analytical Layers into PostgreSQL System Tables
    # -------------------------------------------------------------------------
    print("Syncing processed analytical results to target database tables...")
    with engine.begin() as conn:

        # 1. UPSERT into social_posts (keeps existing rows updated instead of wiping them)
        post_sql = text("""
            INSERT INTO social_posts (
                id, source, subreddit, title, content, permalink, created_utc,
                post_sentiment, discussion_sentiment, n_comments,
                categories, brands, ingredients, entities, top_comments, search_blob
            ) VALUES (
                :id, :source, :subreddit, :title, :content, :permalink, :created_utc,
                :post_sentiment, :discussion_sentiment, :n_comments,
                :categories, :brands, :ingredients, :entities, :top_comments, :search_blob
            ) ON CONFLICT (id) DO UPDATE SET
                source = EXCLUDED.source,
                subreddit = EXCLUDED.subreddit,
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                permalink = EXCLUDED.permalink,
                created_utc = EXCLUDED.created_utc,
                post_sentiment = EXCLUDED.post_sentiment,
                discussion_sentiment = EXCLUDED.discussion_sentiment,
                n_comments = EXCLUDED.n_comments,
                categories = EXCLUDED.categories,
                brands = EXCLUDED.brands,
                ingredients = EXCLUDED.ingredients,
                entities = EXCLUDED.entities,
                top_comments = EXCLUDED.top_comments,
                search_blob = EXCLUDED.search_blob;
        """)
        for p in posts_out:
            conn.execute(post_sql, {
                "id": p["id"], "source": p["source"], "subreddit": p["subreddit"],
                "title": p["title"], "content": p["content"], "permalink": p["permalink"],
                "created_utc": p["created_utc"], "post_sentiment": p["post_sentiment"],
                "discussion_sentiment": p["discussion_sentiment"], "n_comments": p["n_comments"],
                "categories": json.dumps(p["categories"]),
                "brands": json.dumps(p["brands"]),
                "ingredients": json.dumps(p["ingredients"]),
                "entities": json.dumps(p["entities"]),
                "top_comments": json.dumps(p["top_comments"]),
                "search_blob": p["search_blob"]
            })

        # 2. Re-link active post-entity links in social_relationships
        if post_ids:
            conn.execute(text("DELETE FROM social_relationships WHERE post_id IN :ids"), {"ids": post_ids})

        rel_sql = text("""
            INSERT INTO social_relationships (post_id, subreddit, entity_type, entity, "where", mentions)
            VALUES (:post_id, :subreddit, :entity_type, :entity, :where, :mentions);
        """)
        for r in rel_rows:
            conn.execute(rel_sql, r)

        # 3. Merge global entities cache instead of truncating it
        for e in entities:
            upsert_entity_row(conn, e["entity_type"], e["entity"], e["mentions"], e["n_posts"], e["avg_sentiment"])

        # 4. Merge global categories cache instead of truncating it
        for c in categories:
            upsert_category_row(conn, c["category"], c["n_posts"], c["avg_sentiment"], c["top_products"], c["top_ingredients"])

        # 5. Refresh metadata snapshot without wiping previous rows
        upsert_meta_row(
            conn,
            ["reddit"],
            sorted({p["subreddit"] for p in posts_out if p["subreddit"]}),
            len(posts_out),
            total_comments_count,
            len(rel_rows),
            len(entities),
            round(sum(p["post_sentiment"] for p in posts_out) / len(posts_out), 4) if posts_out else 0.0
        )

        # -------------------------------------------------------------------------
        # STEP 4: Synchronize Pipeline State (Acknowledge processing is done)
        # -------------------------------------------------------------------------
        print("Marking processed raw posts as pipeline completed (pipeline_processed = TRUE)...")
        conn.execute(text("UPDATE reddit_posts SET pipeline_processed = TRUE WHERE id IN :ids"), {"ids": post_ids})

    print(f"Successfully transformed and synchronized {len(posts_out)} records into the system tables.")

if __name__ == "__main__":
    print("Starting Database-Driven Social Ingestion Pipeline...")
    run()