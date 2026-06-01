"""
Google Trends intelligence for Product Scout category pages.

Reads two real Google Trends exports:
  metrics.csv     — per keyword/brand/subcategory momentum metrics
                    (avg/peak score, 3m & 6m momentum, YoY growth, trend label)
  timeseries.csv  — weekly relative search interest (0-100) per keyword,
                    per country, 2023-12 -> 2025-12.

Covers 3 categories (cleanser/oil-control, moisturizer/hydration, sunscreen/SPF)
in 2 markets (HK, JP). Provides:
  * category_block(name) — everything the Google Trends UI module needs
  * agent_summary(name)  — a compact view for the Claude agent
"""

import shutil
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
TRENDS_DIR = HERE / "data" / "trends"
DOWNLOADS = Path.home() / "Downloads"

# social category name -> trends category key
CATEGORY_KEYS = {
    "Cleanser & Oil Control": "cleanser_oil_control",
    "Moisturizer & Hydration": "moisturizer_hydration",
    "Sunscreen / SPF": "sunscreen_spf",
}
COUNTRY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "AU": "Australia", "DE": "Germany",
    "FR": "France", "JP": "Japan", "KR": "South Korea", "SG": "Singapore",
    "HK": "Hong Kong", "TW": "Taiwan", "TH": "Thailand", "MY": "Malaysia", "PH": "Philippines",
}
BRANDS_KEY = "brands"
DEFAULT_COUNTRY = "US"
# preferred display order for the country tabs
COUNTRY_ORDER = ["US", "GB", "AU", "DE", "FR", "JP", "KR", "SG", "HK", "TW", "TH", "MY", "PH"]


def _num(v):
    return None if v is None or pd.isna(v) else round(float(v), 3)


class TrendsData:
    def __init__(self):
        self._ensure()
        self.metrics = pd.read_csv(TRENDS_DIR / "metrics.csv")
        self.ts = pd.read_csv(TRENDS_DIR / "timeseries.csv")

    def _ensure(self):
        TRENDS_DIR.mkdir(parents=True, exist_ok=True)
        for f in ["metrics.csv", "timeseries.csv"]:
            dest = TRENDS_DIR / f
            if not dest.exists() and (DOWNLOADS / f).exists():
                shutil.copy(DOWNLOADS / f, dest)

    def has(self, name):
        return name in CATEGORY_KEYS

    # ---------- metric helpers ----------
    def _metric(self, row):
        return {
            "keyword": row["keyword"],
            "type": row["type"],
            "trend_label": row.get("trend_label"),
            "avg_score": _num(row.get("avg_score")),
            "peak_score": _num(row.get("peak_score")),
            "momentum_3m": _num(row.get("momentum_3m")),
            "momentum_6m": _num(row.get("momentum_6m")),
            "growth_yoy": _num(row.get("growth_yoy")),
        }

    def _series(self, df, dates):
        m = dict(zip(df["date"], df["score"]))
        return [None if d not in m else int(m[d]) for d in dates]

    def _order_countries(self, countries):
        cs = set(countries)
        ordered = [c for c in COUNTRY_ORDER if c in cs]
        ordered += sorted(cs - set(ordered))
        return ordered

    def _dedup_brands(self, bm):
        """Brand metrics span tier1/tier2 (with duplicates) — keep one row per
        brand, the highest-scoring instance, sorted by avg_score."""
        best = {}
        for _, r in bm.iterrows():
            kw = r["keyword"]
            cur = best.get(kw)
            if cur is None or (r.get("avg_score") or 0) > (cur.get("avg_score") or 0):
                best[kw] = self._metric(r)
        return sorted(best.values(), key=lambda s: s["avg_score"] or 0, reverse=True)

    # ---------- full block for the UI ----------
    def category_block(self, name):
        key = CATEGORY_KEYS.get(name)
        if not key:
            return {"available": False, "category": name}
        m = self.metrics[self.metrics["category"] == key]
        ts = self.ts[self.ts["category"] == key]
        bm = self.metrics[self.metrics["category"] == BRANDS_KEY]    # brands (global)
        bts = self.ts[self.ts["category"] == BRANDS_KEY]
        countries = self._order_countries(set(m["country"]) | set(bm["country"]))
        by_country = {c: self._country_block(c, m[m["country"] == c], ts[ts["country"] == c],
                                             bm[bm["country"] == c], bts[bts["country"] == c])
                      for c in countries}
        default = DEFAULT_COUNTRY if DEFAULT_COUNTRY in countries else (countries[0] if countries else None)
        latest = str(m["latest_date"].max()) if len(m) else None
        return {
            "available": True, "category": name, "trends_key": key,
            "countries": [{"code": c, "name": COUNTRY_NAMES.get(c, c)} for c in countries],
            "default_country": default, "by_country": by_country, "latest_date": latest,
            "source": "Google Trends — relative search interest (0–100), weekly",
        }

    def _country_block(self, country, m, ts, bm, bts):
        baseline_m = m[m["type"] == "baseline"]
        baseline = self._metric(baseline_m.iloc[0]) if len(baseline_m) else None

        brands = self._dedup_brands(bm)                  # brand momentum (deduped, ranked)

        # chart lines: category baseline + the 2 top brands' time series
        dates = sorted(set(ts["date"]) | set(bts["date"]))
        lines = []
        b = ts[ts["type"] == "baseline"]
        if len(b):
            lines.append({"name": b.iloc[0]["keyword"], "role": "category",
                          "values": self._series(b, dates)})
        for br in brands[:2]:
            bb = bts[bts["keyword"] == br["keyword"]]
            if len(bb):
                lines.append({"name": br["keyword"], "role": "brand",
                              "values": self._series(bb, dates)})

        subs = [self._metric(r) for _, r in m[m["type"] == "subcategory"].iterrows()]
        subs = [s for s in subs if (s["peak_score"] or 0) > 0]
        subs.sort(key=lambda s: (s["momentum_3m"] if s["momentum_3m"] is not None else -99,
                                 s["growth_yoy"] if s["growth_yoy"] is not None else -99),
                  reverse=True)

        return {"country": country, "country_name": COUNTRY_NAMES.get(country, country),
                "baseline": baseline, "series": {"dates": dates, "lines": lines},
                "rising_subcategories": subs, "brands": brands}

    # ---------- compact summary for the agent ----------
    def agent_summary(self, name, country=None):
        block = self.category_block(name)
        if not block.get("available"):
            return {"available": False,
                    "note": f"No Google Trends data for '{name}'. Available: "
                            f"{list(CATEGORY_KEYS)}"}
        out = {"category": name, "source": block["source"], "by_country": {}}
        for c, cb in block["by_country"].items():
            if country and c != country:
                continue
            out["by_country"][c] = {
                "market": cb["country_name"],
                "category_trend": cb["baseline"]["trend_label"] if cb["baseline"] else None,
                "category_momentum_3m": cb["baseline"]["momentum_3m"] if cb["baseline"] else None,
                "category_growth_yoy": cb["baseline"]["growth_yoy"] if cb["baseline"] else None,
                "rising_subcategories": [
                    {"keyword": s["keyword"], "trend": s["trend_label"],
                     "momentum_3m": s["momentum_3m"], "growth_yoy": s["growth_yoy"]}
                    for s in cb["rising_subcategories"][:5]],
                "brand_momentum": [
                    {"brand": b["keyword"], "trend": b["trend_label"],
                     "avg_score": b["avg_score"], "momentum_3m": b["momentum_3m"],
                     "growth_yoy": b["growth_yoy"]} for b in cb["brands"]],
            }
        return out

    def available_categories(self):
        return list(CATEGORY_KEYS.keys())


_trends = None


def get_trends():
    global _trends
    if _trends is None:
        _trends = TrendsData()
    return _trends
