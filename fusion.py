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
from amazon import get_amazon
from trends import get_trends
import skin_types

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
        # category -> dominant consumer skin segment (US share), from Statista
        self._skin = {}
        try:
            for s in skin_types.agent_summary()["segments"]:
                rc = s.get("related_category")
                if rc and (rc not in self._skin or s["approx_all_pct"] > self._skin[rc]["pct"]):
                    self._skin[rc] = {"skin_type": s["skin_type"], "pct": s["approx_all_pct"]}
        except Exception:  # noqa: BLE001
            pass

    # ---------- Amazon (unmet need) + Trends (demand momentum) helpers ----------
    def _amazon_signal(self, category):
        """Top review pain point (= unmet need) + best-in-class + a real complaint."""
        try:
            d = get_amazon().category(category)
        except Exception:  # noqa: BLE001
            return None
        if not d.get("available"):
            return None
        sm = d["summary"]
        voc = (d.get("voice_of_customer") or {}).get("negative") or []
        return {
            "pain_point": sm.get("top_painpoint"),          # {name, neg_rate, mentions}
            "best_in_class": sm.get("best_product"),
            "avg_rating": sm.get("avg_rating_weighted"),
            "complaint": (voc[0]["text"][:160] + "…") if voc and voc[0].get("text") else None,
            "complaint_brand": voc[0]["brand"] if voc else None,
        }

    def _demand_markets(self, category):
        """Markets where THIS category's search interest is rising / declining,
        plus its rising sub-categories (Google Trends). Sharper than HS-3304 net
        imports because it is category- AND country-specific."""
        try:
            block = get_trends().category_block(category)
        except Exception:  # noqa: BLE001
            return None
        if not block.get("available"):
            return None
        rising, declining, subs = [], [], Counter()
        sub_mom = defaultdict(list)
        for code, cb in block["by_country"].items():
            base = cb.get("baseline") or {}
            tl, m3 = base.get("trend_label"), base.get("momentum_3m")
            row = {"market": cb["country_name"], "code": code, "momentum_3m": m3,
                   "yoy": base.get("growth_yoy")}
            if tl == "rising":
                rising.append(row)
            elif tl == "declining":
                declining.append(cb["country_name"])
            for s in cb.get("rising_subcategories", []):
                if s.get("trend_label") == "rising" and s.get("momentum_3m") is not None:
                    subs[s["keyword"]] += 1
                    sub_mom[s["keyword"]].append(s["momentum_3m"])
        rising.sort(key=lambda r: r["momentum_3m"] or 0, reverse=True)
        emerging = [{"format": kw, "markets": subs[kw],
                     "avg_momentum": round(sum(sub_mom[kw]) / len(sub_mom[kw]), 2)}
                    for kw, _ in subs.most_common(3)]
        return {"rising": rising[:5], "declining": declining, "emerging_formats": emerging}

    def emerging_formats(self):
        """Cross-market new-product whitespace: rising sub-categories ranked by how
        many markets they're rising in (Google Trends)."""
        try:
            trends = get_trends()
            cats = trends.available_categories()
        except Exception:  # noqa: BLE001
            return []
        agg = {}
        for name in cats:
            try:
                block = trends.category_block(name)
            except Exception:  # noqa: BLE001
                continue
            if not block.get("available"):
                continue
            for code, cb in block["by_country"].items():
                for s in cb.get("rising_subcategories", []):
                    if s.get("trend_label") == "rising" and s.get("momentum_3m") is not None:
                        d = agg.setdefault((name, s["keyword"]),
                                           {"markets": set(), "mom": []})
                        d["markets"].add(cb["country_name"])
                        d["mom"].append(s["momentum_3m"])
        out = [{"format": kw, "category": cat,
                "markets_rising": sorted(v["markets"]), "n_markets": len(v["markets"]),
                "avg_momentum": round(sum(v["mom"]) / len(v["mom"]), 2),
                "pain_point": (self._amazon_signal(cat) or {}).get("pain_point")}
               for (cat, kw), v in agg.items()]
        out.sort(key=lambda x: (x["n_markets"], x["avg_momentum"]), reverse=True)
        return out[:8]

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
            amz = self._amazon_signal(cat)              # unmet need (Amazon reviews)
            dem = self._demand_markets(cat)             # rising/declining markets (Trends)
            skin = self._skin.get(cat)                  # addressable skin segment (Statista)

            # Where to sell: prefer category-specific rising-demand markets (Trends);
            # fall back to category-agnostic HS-3304 net importers (trade).
            if dem and dem["rising"]:
                sell_to = [{"country": r["market"], "momentum_3m": r["momentum_3m"],
                            "yoy": r["yoy"], "basis": "search demand rising"}
                           for r in dem["rising"][:5]]
            else:
                sell_to = [{"country": s["country"], "net_import_b": s["net_import_b"],
                            "import_yoy": s["import_yoy"], "basis": "net cosmetics imports"}
                           for s in sell]

            # corroboration: social + sentiment always present, then each extra dataset
            n_signals = 2 + sum(bool(x) for x in (origins, amz, dem, skin))

            out.append({
                "category": cat, "angle": o["angle"],
                "n_posts": o["n_posts"], "avg_sentiment": o["avg_sentiment"],
                "sentiment_label": o["sentiment_label"],
                "top_brands": [b for b, _ in cat_brands.get(cat, Counter()).most_common(4)],
                "source_from": origins,
                "sell_to": sell_to,
                "sell_basis": sell_to[0]["basis"] if sell_to else None,
                "unmet_need": amz["pain_point"] if amz else None,
                "best_in_class": amz["best_in_class"] if amz else None,
                "complaint": amz["complaint"] if amz else None,
                "complaint_brand": amz["complaint_brand"] if amz else None,
                "addressable_segment": skin,
                "declining_markets": (dem or {}).get("declining") or [],
                "emerging_formats": (dem or {}).get("emerging_formats") or [],
                "n_signals": n_signals,
            })
        # surface the most-corroborated opportunities first
        out.sort(key=lambda c: (c["n_signals"], c["n_posts"]), reverse=True)
        return out

    def _headline(self, origins, sell, cats):
        """Lead with the single best cross-signal opportunity if we have one
        (category × unmet need × rising market × source), else the sourcing story."""
        best = next((c for c in cats if c.get("unmet_need") and c.get("source_from")
                     and c["sell_to"]), None)
        if best:
            pp = best["unmet_need"]
            src = best["source_from"][0]
            mkt = best["sell_to"][0]
            seg = best.get("addressable_segment")
            seg_txt = (f" for the {seg['skin_type'].lower()}-skin segment (~{seg['pct']}% of consumers)"
                       if seg else "")
            return (
                f"Top opportunity: a {best['category']} product that fixes "
                f"<strong>{pp['name']}</strong> — {pp['neg_rate']:.0f}% of Amazon reviews "
                f"({pp['mentions']:,} mentions) complain about it{seg_txt}. "
                f"Source from {src['tagline']} ({src['origin']}); sell into "
                f"{mkt['country']} where {best['sell_basis']}."
            )
        top_origin = origins[0] if origins else None
        if top_origin and sell:
            return (
                f"{top_origin['tagline']} ({top_origin['origin']}) is the strongest sourcing "
                f"signal — {top_origin['social_mentions']} social mentions across "
                f"{top_origin['n_brands']} brands ({top_origin['sentiment_label']}) and "
                f"${top_origin['export_b']:.1f}B in exports"
                + (f" growing {top_origin['export_cagr']:+.1f}%/yr" if top_origin.get('export_cagr') else "")
                + f". Biggest unmet-demand market to sell into: {sell[0]['country']} "
                f"(${sell[0]['net_import_b']:.1f}B net imports)."
            )
        return None

    # ---------- bundle ----------
    def payload(self):
        origins = self.sourcing_origins()
        sell = self.sell_to_markets(n=8)
        cats = self.category_opportunities()
        return {
            "headline": self._headline(origins, sell, cats),
            "sourcing_origins": origins,
            "sell_to_markets": sell,
            "category_opportunities": cats,
            "emerging_formats": self.emerging_formats(),
            "meta": {
                "trade_year": self.trade.latest,
                "social_posts": self.social.meta.get("n_posts"),
                "signals": ["Reddit demand+sentiment", "Amazon review pain points",
                            "Google Trends momentum (13 markets)", "UN Comtrade HS 3304 trade",
                            "Statista skin-type segments"],
                "note": "Trade = UN Comtrade HS 3304 (country-level, all beauty/make-up prep). "
                        "Social = Reddit brand/category mentions + sentiment. Amazon = review "
                        "aspect pain points. Trends = category search momentum by market. "
                        "Linked via brand origin + category.",
            },
        }


_fusion = None


def get_fusion():
    global _fusion
    if _fusion is None:
        _fusion = Fusion()
    return _fusion
