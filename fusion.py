"""
Trade <-> Social fusion: the "Source-to-Sell" opportunity engine.

This is Product Scout's differentiator: nobody else connects official customs
TRADE flows (who exports/imports cosmetics) with SOCIAL demand & sentiment
(what consumers actually want and how they feel).

The bridge between the two datasets is BRAND ORIGIN: social posts mention brands,
and each brand has a country of origin, which joins to that country's HS 3304
trade. So "K-beauty brands people love" links to "Korea's export strength".

Three outputs:
  * sourcing_origins  — where to SOURCE: origin countries whose brands have social
                        love, scored against that country's export trade.
  * sell_to_markets   — where to SELL: countries importing far more cosmetics than
                        they export (unmet demand), with growth.
  * category_opportunities — per social category: demand+sentiment + the sourcing
                        origins of its brands + the best sell-to markets.

Honest scope: HS 3304 trade is one 6-digit code (all beauty/make-up prep), so the
trade side is category-agnostic; the social side supplies the product-type and
sentiment granularity. Brand origin makes the sourcing link category-specific.
"""

from collections import Counter, defaultdict

from social import get_social
from analytics import get_data

# Brand -> trade country-of-origin (names match the Comtrade dataset exactly).
BRAND_ORIGIN = {
    # USA
    "CeraVe": "USA", "Cetaphil": "USA", "Paula's Choice": "USA", "Neutrogena": "USA",
    "Drunk Elephant": "USA", "Vanicream": "USA", "Differin": "USA", "La Mer": "USA",
    "Tatcha": "USA", "Kiehl's": "USA", "First Aid Beauty": "USA", "Good Molecules": "USA",
    "Naturium": "USA", "Versed": "USA", "Aveeno": "USA", "Olay": "USA", "Clinique": "USA",
    "SkinCeuticals": "USA", "Krave Beauty": "USA", "Stratia": "USA", "Glow Recipe": "USA",
    # Korea (K-beauty)
    "COSRX": "Rep. of Korea", "Anua": "Rep. of Korea", "Beauty of Joseon": "Rep. of Korea",
    "Skin1004": "Rep. of Korea", "Isntree": "Rep. of Korea", "Round Lab": "Rep. of Korea",
    "Purito": "Rep. of Korea", "Some By Mi": "Rep. of Korea", "Innisfree": "Rep. of Korea",
    "Laneige": "Rep. of Korea", "Mixsoon": "Rep. of Korea", "Torriden": "Rep. of Korea",
    "Numbuzin": "Rep. of Korea",
    # France
    "La Roche-Posay": "France", "Bioderma": "France", "Avene": "France",
    "Vichy": "France", "Garnier": "France",
    # Others
    "The Ordinary": "Canada", "Skinfix": "Canada",
    "Eucerin": "Germany", "Hada Labo": "Japan",
    "Medik8": "United Kingdom", "Byoma": "United Kingdom",
}

# Friendly "movement" name per origin (for the narrative)
ORIGIN_TAGLINE = {
    "Rep. of Korea": "K-beauty", "France": "French pharmacy", "USA": "US derm/clean",
    "Japan": "J-beauty", "Canada": "value actives", "Germany": "derm care",
    "United Kingdom": "indie British",
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


class Fusion:
    def __init__(self):
        self.social = get_social()
        self.trade = get_data()
        # trade export metrics by country name (latest year)
        self._exp = {r["country"]: r for r in self.trade.top("export", n=400)}
        self._imp = {r["country"]: r for r in self.trade.top("import", n=400)}

    # ---------- trade helpers ----------
    def _export_metrics(self, country):
        r = self._exp.get(country)
        if not r:
            return None
        rank = next((i + 1 for i, x in enumerate(self.trade.top("export", n=400))
                     if x["country"] == country), None)
        cagr = self.trade.trend(country, "export").get("cagr_pct")
        return {"export_b": r["value_b"], "export_yoy": r["yoy_pct"],
                "export_rank": rank, "cagr_pct": cagr, "iso3": r["iso3"]}

    # ---------- WHERE TO SOURCE ----------
    def sourcing_origins(self):
        """Origin countries whose brands have social love, scored vs export trade."""
        brands = [e for e in self.social.entities if e["entity_type"] == "brand"]
        agg = defaultdict(lambda: {"mentions": 0, "sent_num": 0.0, "sent_den": 0,
                                   "brands": []})
        for b in brands:
            origin = BRAND_ORIGIN.get(b["entity"])
            if not origin:
                continue
            a = agg[origin]
            a["mentions"] += b["mentions"]
            a["sent_num"] += (b["avg_sentiment"] or 0) * b["mentions"]
            a["sent_den"] += b["mentions"]
            a["brands"].append({"name": b["entity"], "mentions": b["mentions"],
                                "sentiment": b["avg_sentiment"]})

        max_ment = max((a["mentions"] for a in agg.values()), default=1)
        out = []
        for origin, a in agg.items():
            sent = round(a["sent_num"] / a["sent_den"], 3) if a["sent_den"] else 0.0
            tm = self._export_metrics(origin) or {}
            export_b = tm.get("export_b") or 0
            # blended score: consumer pull (demand+sentiment) x trade supply strength
            demand_norm = a["mentions"] / max_ment
            supply_norm = min(export_b / 12.0, 1.0)        # ~$12B caps the scale
            score = round(demand_norm * 0.5 + max(sent, 0) * 0.2 + supply_norm * 0.3, 3)
            a["brands"].sort(key=lambda x: x["mentions"], reverse=True)
            out.append({
                "origin": origin,
                "tagline": ORIGIN_TAGLINE.get(origin, origin),
                "social_mentions": a["mentions"],
                "n_brands": len(a["brands"]),
                "avg_sentiment": sent, "sentiment_label": _label(sent),
                "top_brands": a["brands"][:5],
                "export_b": tm.get("export_b"), "export_rank": tm.get("export_rank"),
                "export_cagr": tm.get("cagr_pct"), "iso3": tm.get("iso3"),
                "score": score,
                "signal": self._origin_signal(sent, tm),
            })
        out.sort(key=lambda x: x["score"], reverse=True)
        return out

    @staticmethod
    def _origin_signal(sent, tm):
        rank = (tm or {}).get("export_rank") or 99
        cagr = (tm or {}).get("cagr_pct") or 0
        if sent >= 0.3 and rank <= 5 and cagr > 5:
            return "Hot — beloved brands + fast-growing exports"
        if sent >= 0.2 and rank <= 8:
            return "Strong — strong demand + established supply"
        if cagr > 8:
            return "Rising — exports accelerating"
        return "Emerging"

    # ---------- WHERE TO SELL ----------
    def sell_to_markets(self, n=8, min_import_b=0.3):
        """Net-importer countries (imports >> exports) = unmet cosmetics demand."""
        yr = self.trade.latest
        ex = (self.trade.exports[self.trade.exports.year == yr]
              .groupby("country")["trade_value_usd"].sum())
        im = (self.trade.imports[self.trade.imports.year == yr]
              .groupby("country")["trade_value_usd"].sum())
        rows = []
        for country, imp in im.items():
            # skip Comtrade aggregate / non-country areas
            if any(t in country for t in ("nes", "Areas", "Free Zones",
                                          "Special Categories", "Bunkers", "World")):
                continue
            imp_b = imp / 1e9
            if imp_b < min_import_b:
                continue
            exp_b = float(ex.get(country, 0)) / 1e9
            net_b = imp_b - exp_b
            if net_b <= 0:
                continue
            prof_yoy = self._imp.get(country, {}).get("yoy_pct")
            rows.append({
                "country": country, "import_b": round(imp_b, 2),
                "export_b": round(exp_b, 2), "net_import_b": round(net_b, 2),
                "import_yoy": prof_yoy,
                "iso3": self._imp.get(country, {}).get("iso3"),
            })
        # rank by net import size, but reward growth
        rows.sort(key=lambda r: r["net_import_b"] * (1 + (r["import_yoy"] or 0) / 100), reverse=True)
        return rows[:n]

    # ---------- per-category fusion ----------
    def _category_brand_origins(self):
        """category -> Counter(origin) from brand mentions in that category's posts."""
        cat_origin = defaultdict(Counter)
        cat_brands = defaultdict(Counter)
        for p in self.social.posts:
            origins = [BRAND_ORIGIN.get(b) for b in p["brands"]]
            for cat in p["categories"]:
                for b in p["brands"]:
                    cat_brands[cat][b] += 1
                for o in origins:
                    if o:
                        cat_origin[cat][o] += 1
        return cat_origin, cat_brands

    def category_opportunities(self, top_n=6):
        ins = self.social.launch_insights(n=20)["opportunities"]
        cat_origin, cat_brands = self._category_brand_origins()
        sell = self.sell_to_markets(n=5)
        out = []
        for o in ins[:top_n]:
            cat = o["category"]
            origins = []
            for origin, cnt in cat_origin.get(cat, Counter()).most_common(4):
                tm = self._export_metrics(origin) or {}
                origins.append({"origin": origin, "tagline": ORIGIN_TAGLINE.get(origin, origin),
                                "weight": cnt, "export_b": tm.get("export_b"),
                                "export_rank": tm.get("export_rank")})
            out.append({
                "category": cat, "angle": o["angle"],
                "n_posts": o["n_posts"], "avg_sentiment": o["avg_sentiment"],
                "sentiment_label": o["sentiment_label"],
                "top_brands": [b for b, _ in cat_brands.get(cat, Counter()).most_common(4)],
                "source_from": origins,
                "sell_to": [{"country": s["country"], "net_import_b": s["net_import_b"],
                             "import_yoy": s["import_yoy"]} for s in sell],
            })
        return out

    # ---------- bundle ----------
    def payload(self):
        origins = self.sourcing_origins()
        sell = self.sell_to_markets(n=8)
        top_origin = origins[0] if origins else None
        headline = None
        if top_origin and sell:
            headline = (
                f"{top_origin['tagline']} ({top_origin['origin']}) is the strongest sourcing "
                f"signal — {top_origin['social_mentions']} social mentions across "
                f"{top_origin['n_brands']} brands ({top_origin['sentiment_label']}) and "
                f"${top_origin['export_b']:.1f}B in exports"
                + (f" growing {top_origin['export_cagr']:+.1f}%/yr" if top_origin.get('export_cagr') else "")
                + f". Biggest unmet-demand market to sell into: {sell[0]['country']} "
                f"(${sell[0]['net_import_b']:.1f}B net imports)."
            )
        return {
            "headline": headline,
            "sourcing_origins": origins,
            "sell_to_markets": sell,
            "category_opportunities": self.category_opportunities(),
            "meta": {
                "trade_year": self.trade.latest,
                "social_posts": self.social.meta.get("n_posts"),
                "note": "Trade = UN Comtrade HS 3304 (country-level, all beauty/make-up prep). "
                        "Social = Reddit brand/category mentions + sentiment. Linked via brand origin.",
            },
        }


_fusion = None


def get_fusion():
    global _fusion
    if _fusion is None:
        _fusion = Fusion()
    return _fusion
