"""
Amazon reviews intelligence for Product Scout category pages.

Reads hardcoded Amazon review exports for the top product categories and
compiles sourcer-oriented insight: per-product ratings & aspect sentiment,
category-wide pain points (= sourcing opportunities) and strengths, a
voice-of-customer feed of real review quotes, and headline insights.

The export already carries product-level aspect sentiment (positive/negative
mention counts per aspect) and AI summaries; we aggregate and interpret them.

A live scraper/ingestion will replace the static files later; the analysis
layer and API stay the same.
"""

import html
import json
import math
import re
import shutil
from collections import defaultdict
from pathlib import Path

from social_taxonomy import BRANDS

HERE = Path(__file__).parent
AMZ_DIR = HERE / "data" / "amazon"
DOWNLOADS = Path.home() / "Downloads"

# social category name -> source file
CATEGORY_FILES = {
    "Sunscreen / SPF": "Sunscreen&SPF.json",
    "Moisturizer & Hydration": "moisturizer&hydration.json",
    "Cleanser & Oil Control": "cleanser&oilcontrol.json",
}

# normalise near-duplicate aspect names for category aggregation
ASPECT_SYNONYMS = {
    "gentle": "Gentleness", "gentleness": "Gentleness",
    "fragrance": "Fragrance", "fragrance-free": "Fragrance-free", "fragrance free": "Fragrance-free",
    "non-greasy": "Greasiness", "greasiness": "Greasiness", "non greasy": "Greasiness",
    "skin compatibility": "Skin compatibility", "skin irritation": "Skin irritation",
    "value for money": "Value for money",
}

_BRAND_FORMS = sorted(
    ((form, canon) for canon, forms in BRANDS.items() for form in forms),
    key=lambda x: -len(x[0]),
)


def clean(text):
    if not text:
        return ""
    t = html.unescape(str(text))
    # the export sometimes concatenates a duplicated copy of the text
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
    return ASPECT_SYNONYMS.get((name or "").strip().lower(), (name or "").strip().capitalize())


class AmazonData:
    def __init__(self):
        self._cache = {}

    def _load_file(self, fname):
        path = AMZ_DIR / fname
        if not path.exists():
            AMZ_DIR.mkdir(parents=True, exist_ok=True)
            src = DOWNLOADS / fname
            if src.exists():
                shutil.copy(src, path)
        return json.loads(path.read_text())

    def available_categories(self):
        return list(CATEGORY_FILES.keys())

    def category(self, name):
        if name in self._cache:
            return self._cache[name]
        fname = CATEGORY_FILES.get(name)
        if not fname:
            return {"available": False, "category": name}
        reviews = self._load_file(fname)
        result = self._analyze(name, reviews)
        self._cache[name] = result
        return result

    # ---------- compact summary for the agent ----------
    def agent_summary(self, name):
        d = self.category(name)
        if not d.get("available"):
            return {"available": False,
                    "note": f"No Amazon review data for '{name}'. Available: "
                            f"{self.available_categories()}"}
        sm = d["summary"]
        return {
            "available": True, "category": name, "source": d["meta"]["source"],
            "avg_rating_weighted": sm["avg_rating_weighted"], "n_products": sm["n_products"],
            "total_ratings": sm["total_ratings"],
            "top_painpoint": sm["top_painpoint"], "top_strength": sm["top_strength"],
            "best_in_class": sm["best_product"],
            "products": [{"brand": p["brand"], "avg_rating": p["avg_rating"],
                          "total_ratings": p["total_ratings"],
                          "aspect_negative_rate": p["overall_neg_rate"],
                          "weakest_aspect": p["dominant_negative"],
                          "ai_summary": (p["ai_summary"] or "")[:300]}
                         for p in d["products"]],
            "category_pain_points": [{"aspect": a["name"], "neg_rate": a["neg_rate"],
                                      "mentions": a["mentions"]}
                                     for a in d["category_aspects"] if a["neg_rate"] >= 25][:6],
        }

    # ---------- analysis ----------
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
            for a in (head.get("aspects") or []):
                m = a.get("aspectMention", 0) or 0
                neg = a.get("aspectMentionNegative", 0) or 0
                pos = a.get("aspectMentionPositive", 0) or 0
                if m <= 0:
                    continue
                nr = round(neg / m * 100, 1)
                aspects.append({"name": a["aspectName"], "mentions": m, "pos": pos, "neg": neg,
                                "neg_rate": nr, "sentiment": a.get("aspectSentiment"),
                                "summary": clean(a.get("aspectSummary"))})
                tot_m += m
                tot_n += neg
                k = norm_aspect(a["aspectName"])
                cat_aspects[k]["mentions"] += m
                cat_aspects[k]["pos"] += pos
                cat_aspects[k]["neg"] += neg
            aspects.sort(key=lambda x: x["mentions"], reverse=True)
            neg_aspects = [a for a in aspects if a["mentions"] >= 5]
            dom_neg = max(neg_aspects, key=lambda a: a["neg_rate"], default=None)
            dom_pos = max(aspects, key=lambda a: a["pos"], default=None)
            rs = head.get("ratingSummary") or {}
            products.append({
                "asin": asin,
                "brand": brand_of(head.get("productTitle")),
                "title": clean(head.get("productTitle")),
                "avg_rating": head.get("averageRating"),
                "total_ratings": head.get("totalRatings") or 0,
                "n_reviews": len(revs),
                "star_summary": {k: rs.get(k, 0) for k in
                                 ["five_stars", "four_stars", "three_stars", "two_stars", "one_star"]},
                "overall_neg_rate": round(tot_n / tot_m * 100, 1) if tot_m else 0,
                "dominant_negative": {"name": dom_neg["name"], "neg_rate": dom_neg["neg_rate"]} if dom_neg else None,
                "dominant_positive": dom_pos["name"] if dom_pos else None,
                "ai_summary": clean(head.get("reviewsAISummary")),
                "url": head.get("productUrl"),
                "aspects": aspects,
                # credibility-weighted quality: rating tempered by review volume
                "quality_score": round((head.get("averageRating") or 0)
                                       * math.log10((head.get("totalRatings") or 0) + 10), 2),
            })
        # market leaders first (a sourcer reads the dominant SKUs top-down)
        products.sort(key=lambda p: p["total_ratings"], reverse=True)

        # category aspect rollup
        cat_aspect_list = []
        for nm, v in cat_aspects.items():
            if v["mentions"] < 5:
                continue
            cat_aspect_list.append({
                "name": nm, "mentions": v["mentions"], "pos": v["pos"], "neg": v["neg"],
                "neg_rate": round(v["neg"] / v["mentions"] * 100, 1),
                "pos_rate": round(v["pos"] / v["mentions"] * 100, 1),
            })
        cat_aspect_list.sort(key=lambda a: a["mentions"], reverse=True)

        summary = self._summary(name, products, cat_aspect_list)
        voc = self._voice_of_customer(reviews)
        return {
            "available": True, "category": name,
            "summary": summary,
            "category_aspects": cat_aspect_list,
            "products": products,
            "voice_of_customer": voc,
            "meta": {"source": "Amazon reviews (sample export; live scraping pending)",
                     "scraped_at": (reviews[0].get("scrapedAt") if reviews else None)},
        }

    def _summary(self, name, products, cat_aspects):
        n_products = len(products)
        n_reviews = sum(p["n_reviews"] for p in products)
        total_ratings = sum(p["total_ratings"] for p in products)
        simple_avg = round(sum(p["avg_rating"] or 0 for p in products) / n_products, 2) if n_products else 0
        wsum = sum((p["avg_rating"] or 0) * p["total_ratings"] for p in products)
        weighted = round(wsum / total_ratings, 2) if total_ratings else simple_avg

        sizable = [a for a in cat_aspects if a["mentions"] >= 20]
        painpoint = max(sizable, key=lambda a: a["neg_rate"], default=None)
        strength = max(sizable, key=lambda a: a["pos_rate"], default=None)
        # best-in-class = credibility-weighted, not raw stars on thin volume
        best = max(products, key=lambda p: p["quality_score"], default=None) if products else None
        worst = max(products, key=lambda p: p["overall_neg_rate"], default=None)

        insights = []
        if best:
            insights.append({"tag": "Market", "tone": "neutral",
                             "text": f"{n_products} leading products average {weighted}★ across "
                                     f"{total_ratings:,} total ratings — a validated, competitive category."})
        if painpoint:
            insights.append({"tag": "Opportunity", "tone": "opportunity",
                             "text": f"Biggest shared weakness is <strong>{painpoint['name']}</strong> "
                                     f"({painpoint['neg_rate']:.0f}% negative over {painpoint['mentions']:,} mentions) "
                                     f"— sourcing a product that solves it is the clearest way to differentiate."})
        if best:
            insights.append({"tag": "Benchmark", "tone": "good",
                             "text": f"Best-in-class to benchmark: <strong>{best['brand']}</strong> "
                                     f"({best['avg_rating']}★, {best['total_ratings']:,} ratings)."})
        if worst and worst["dominant_negative"] and worst["overall_neg_rate"] >= 20:
            insights.append({"tag": "Watch", "tone": "bad",
                             "text": f"Most-criticised incumbent: <strong>{worst['brand']}</strong> "
                                     f"({worst['overall_neg_rate']:.0f}% aspect-negative, worst on "
                                     f"{worst['dominant_negative']['name']}) — a beatable target."})
        return {
            "n_products": n_products, "n_reviews": n_reviews, "total_ratings": total_ratings,
            "avg_rating": simple_avg, "avg_rating_weighted": weighted,
            "top_painpoint": painpoint, "top_strength": strength,
            "best_product": {"brand": best["brand"], "title": best["title"],
                             "avg_rating": best["avg_rating"],
                             "total_ratings": best["total_ratings"]} if best else None,
            "insights": insights,
        }

    def _voice_of_customer(self, reviews):
        def pick(revs, n=3):
            out = []
            seen = set()
            for r in revs:
                txt = clean(r.get("reviewText"))
                if len(txt) < 40 or txt[:60] in seen:
                    continue
                seen.add(txt[:60])
                out.append({
                    "title": clean(r.get("reviewTitle")),
                    "text": txt[:340] + ("…" if len(txt) > 340 else ""),
                    "rating": r.get("rating"),
                    "helpful": r.get("helpfulVoteCount") or 0,
                    "brand": brand_of(r.get("productTitle")),
                    "verified": r.get("verifiedPurchase"),
                })
                if len(out) >= n:
                    break
            return out

        neg = sorted([r for r in reviews if (r.get("rating") or 5) <= 2],
                     key=lambda r: (r.get("helpfulVoteCount") or 0), reverse=True)
        pos = sorted([r for r in reviews if (r.get("rating") or 0) >= 5],
                     key=lambda r: (r.get("helpfulVoteCount") or 0), reverse=True)
        return {"negative": pick(neg), "positive": pick(pos)}


_amazon = None


def get_amazon():
    global _amazon
    if _amazon is None:
        _amazon = AmazonData()
    return _amazon
