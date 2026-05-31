"""
Social ingestion + entity/sentiment pipeline for Product Scout.

Input : a Reddit dump (data/skincare_multi_sub_data.json by default) with
        {"posts": {...}, "comments": {...}}.
Output (in data/):
  social_posts.json        — processed posts: text, VADER sentiment, discussion
                             sentiment, matched categories/brands/ingredients,
                             top comments. (source-tagged for multi-platform.)
  social_relationships.csv — the RELATIONSHIP TABLE: post <-> entity links
                             (post_id, subreddit, entity_type, entity, where, mentions)
  social_entities.json     — per-entity rollup (mentions, #posts, avg sentiment)
  social_categories.json   — per-category rollup (#posts, avg sentiment, top products)
  social_meta.json         — totals & provenance

Designed to be source-agnostic: every record carries a `source` field, so
Google Trends / TikTok / etc. can be appended later by emitting the same schema.

Run:  python social_ingest.py [path/to/dump.json]
"""

import json
import re
import sys
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from social_taxonomy import TAXONOMY

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(exist_ok=True)

analyzer = SentimentIntensityAnalyzer()


# ───────────────────────── entity matcher ─────────────────────────
def build_matchers():
    """For each entity type, compile one regex + a surface-form -> canonical map."""
    matchers = {}
    for etype, mapping in TAXONOMY.items():
        syn2canon = {}
        for canon, syns in mapping.items():
            for s in syns:
                syn2canon[s.lower()] = canon
        # longest surface forms first so multi-word phrases win
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


# NOTE: sentiment is computed per-SENTENCE (not over whole posts). VADER's
# compound score saturates toward +/-1 on long text, which made long Reddit
# posts read as uniformly "very positive"; sentence-level scoring keeps results
# graded. Entity/product sentiment uses only the sentence containing the mention.
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text):
    return [s.strip() for s in SENT_SPLIT.split(text or "") if s.strip()]


def analyze_text(text, matchers):
    """Return (doc_sentiment, mentions{type:Counter}, contexts[(type,name,sent)]).

    Entities are matched per sentence, and each mention is tagged with the
    sentiment of the SENTENCE it appears in — so 'CeraVe broke me out' attributes
    a negative score to CeraVe regardless of the rest of the post's tone.
    """
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
                contexts.append((et, name, sc))   # one context row per sentence-mention
    return round(sum(comps) / len(comps), 4), mentions, contexts


# ───────────────────────── main pipeline ─────────────────────────
def run(src_path):
    raw = json.loads(Path(src_path).read_text())
    posts_in, comments_in = raw["posts"], raw["comments"]
    matchers = build_matchers()

    # group comments by post
    comments_by_post = defaultdict(list)
    for c in comments_in.values():
        comments_by_post[c["post_id"]].append(c)

    posts_out = []
    rel_rows = []                       # the relationship table
    # mentions = total surface mentions; sent_sum/sent_n = SENTENCE-level sentiment
    # of just the sentences that mention the entity (contextual, not whole-doc).
    entity_stat = defaultdict(lambda: {"mentions": 0, "posts": set(), "sent_sum": 0.0, "sent_n": 0})

    def add_mentions(etype, name, n, post_id):
        s = entity_stat[(etype, name)]
        s["mentions"] += n
        s["posts"].add(post_id)

    def add_context(etype, name, sent):
        s = entity_stat[(etype, name)]
        s["sent_sum"] += sent
        s["sent_n"] += 1

    for pid, p in posts_in.items():
        title = p.get("title", "") or ""
        content = p.get("content", "") or ""
        post_text = f"{title}. {content}".strip()

        # sentence-level analysis of the post
        post_sent, post_ments, post_ctx = analyze_text(post_text, matchers)
        for et, name, sc in post_ctx:
            add_context(et, name, sc)

        # comments
        clist = sorted(comments_by_post.get(pid, []), key=lambda c: c.get("ups", 0), reverse=True)
        comment_blob = []
        comment_ments = {}           # etype -> Counter (aggregated across comments)
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

        # merge post + comment entity mention counts; record relationships
        merged = {}
        for et in set(post_ments) | set(comment_ments):
            pc = post_ments.get(et, Counter())
            cc = comment_ments.get(et, Counter())
            merged[et] = []
            for name in set(pc) | set(cc):
                pm, cm = pc.get(name, 0), cc.get(name, 0)
                where = "both" if pm and cm else ("post" if pm else "comment")
                merged[et].append({"name": name, "mentions": pm + cm, "where": where})
                rel_rows.append({"post_id": pid, "subreddit": p.get("subreddit"),
                                 "entity_type": et, "entity": name,
                                 "where": where, "mentions": pm + cm})
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

    # ---------- entity rollup ----------
    entities = []
    for (etype, name), s in entity_stat.items():
        entities.append({
            "entity_type": etype, "entity": name,
            "mentions": s["mentions"], "n_posts": len(s["posts"]),
            "avg_sentiment": round(s["sent_sum"] / s["sent_n"], 4) if s["sent_n"] else 0.0,
        })
    entities.sort(key=lambda e: e["mentions"], reverse=True)
    ent_sent = {(e["entity_type"], e["entity"]): e["avg_sentiment"] for e in entities}

    # ---------- category rollup ----------
    # category sentiment uses the SENTENCE-context score for that category entity
    # (consistent with brands/ingredients), not the whole-post average.
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
            "category": name, "n_posts": cs["posts"],
            "avg_sentiment": ent_sent.get(("category", name), 0.0),
            "top_products": [b for b, _ in cs["products"].most_common(5)],
            "top_ingredients": [i for i, _ in cs["ingredients"].most_common(5)],
        })
    categories.sort(key=lambda c: c["n_posts"], reverse=True)

    # ---------- save ----------
    (DATA_DIR / "social_posts.json").write_text(json.dumps(posts_out))
    pd.DataFrame(rel_rows).to_csv(DATA_DIR / "social_relationships.csv", index=False)
    (DATA_DIR / "social_entities.json").write_text(json.dumps(entities))
    (DATA_DIR / "social_categories.json").write_text(json.dumps(categories))
    (DATA_DIR / "social_meta.json").write_text(json.dumps({
        "sources": ["reddit"],
        "subreddits": sorted({p["subreddit"] for p in posts_out if p["subreddit"]}),
        "n_posts": len(posts_out),
        "n_comments": len(comments_in),
        "n_relationships": len(rel_rows),
        "n_entities": len(entities),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "avg_post_sentiment": round(sum(p["post_sentiment"] for p in posts_out) / len(posts_out), 4),
    }))

    print(f"Processed {len(posts_out):,} posts, {len(comments_in):,} comments")
    print(f"Relationship table: {len(rel_rows):,} post<->entity links")
    print(f"Distinct entities: {len(entities)} | categories: {len(categories)}")
    print("Top entities:", [f"{e['entity']}({e['mentions']})" for e in entities[:8]])


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src:
        # default: copy the user's dump into data/ for reproducibility
        default = DATA_DIR / "skincare_multi_sub_data.json"
        downloads = Path.home() / "Downloads" / "skincare_multi_sub_data.json"
        if not default.exists() and downloads.exists():
            shutil.copy(downloads, default)
        src = default
    print(f"Ingesting {src} ...")
    run(src)
