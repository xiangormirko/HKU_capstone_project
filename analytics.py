"""
Analytics layer over the real UN Comtrade HS 3304 data.

Loads the CSVs produced by fetch_data.py and provides:
  * build_payload()  -> everything the dashboard frontend needs (one JSON)
  * a set of query_* functions the Claude agent calls as tools

All numbers come from official customs data — nothing is mocked.
"""

from pathlib import Path
import pandas as pd
import pycountry

DATA_DIR = Path(__file__).parent / "data"

_FLAG_CACHE = {}


def flag_for(iso3):
    """ISO3 -> flag emoji (regional indicator letters). Cached."""
    if iso3 in _FLAG_CACHE:
        return _FLAG_CACHE[iso3]
    try:
        a2 = pycountry.countries.get(alpha_3=iso3).alpha_2
        f = "".join(chr(0x1F1E6 + ord(c) - 65) for c in a2)
    except Exception:  # noqa: BLE001
        f = "🏳️"
    _FLAG_CACHE[iso3] = f
    return f

# Common name aliases so the agent can resolve casual user phrasing.
ALIASES = {
    "south korea": "Rep. of Korea", "korea": "Rep. of Korea", "s korea": "Rep. of Korea",
    "uk": "United Kingdom", "britain": "United Kingdom", "great britain": "United Kingdom",
    "usa": "USA", "us": "USA", "united states": "USA", "america": "USA",
    "uae": "United Arab Emirates", "emirates": "United Arab Emirates",
    "hong kong": "China, Hong Kong SAR", "turkey": "Türkiye",
    "vietnam": "Viet Nam", "russia": "Russian Federation", "czech republic": "Czechia",
}


class TradeData:
    def __init__(self):
        self.exports = pd.read_csv(DATA_DIR / "world_exports.csv")
        self.imports = pd.read_csv(DATA_DIR / "world_imports.csv")
        self.bilateral = pd.read_csv(DATA_DIR / "bilateral.csv")
        self.years = sorted(set(self.exports["year"]) | set(self.imports["year"]))
        self.latest = self.years[-1]
        self.first = self.years[0]

    # ---------- helpers ----------
    def _flow_df(self, flow):
        return self.exports if flow.startswith("e") else self.imports

    def resolve_country(self, name, flow="export"):
        """Best-effort match of a user-supplied name to a country in the data."""
        if not name:
            return None
        df = self._flow_df(flow)
        names = df["country"].unique()
        key = name.strip().lower()
        key = ALIASES.get(key, key).lower()
        # exact, then startswith, then contains
        for n in names:
            if n.lower() == key:
                return n
        for n in names:
            if n.lower().startswith(key) or key in n.lower():
                return n
        return None

    def _yoy(self, df, country, year):
        cur = df[(df.country == country) & (df.year == year)]["trade_value_usd"].sum()
        prev = df[(df.country == country) & (df.year == year - 1)]["trade_value_usd"].sum()
        if prev > 0 and cur > 0:
            return round((cur - prev) / prev * 100, 1)
        return None

    # ---------- ranked tables ----------
    def top(self, flow="export", year=None, n=10):
        year = year or self.latest
        df = self._flow_df(flow)
        yr = df[df.year == year]
        total = yr["trade_value_usd"].sum()
        ranked = (yr.groupby(["country", "iso3", "iso_numeric", "region"], as_index=False)
                  ["trade_value_usd"].sum()
                  .sort_values("trade_value_usd", ascending=False).head(n))
        rows = []
        for _, r in ranked.iterrows():
            rows.append({
                "country": r["country"], "iso3": r["iso3"], "flag": flag_for(r["iso3"]),
                "iso_numeric": None if pd.isna(r["iso_numeric"]) else int(r["iso_numeric"]),
                "value_usd": float(r["trade_value_usd"]),
                "value_b": round(r["trade_value_usd"] / 1e9, 2),
                "share_pct": round(r["trade_value_usd"] / total * 100, 1) if total else 0,
                "yoy_pct": self._yoy(df, r["country"], year),
            })
        return rows

    def trend(self, country, flow="export"):
        df = self._flow_df(flow)
        resolved = self.resolve_country(country, flow)
        if not resolved:
            return {"error": f"Country '{country}' not found in {flow} data."}
        s = (df[df.country == resolved].groupby("year")["trade_value_usd"].sum()
             .reindex(self.years))
        series = [None if pd.isna(v) else round(v / 1e9, 3) for v in s.values]
        vals = s.dropna()
        cagr = None
        if len(vals) >= 2 and vals.iloc[0] > 0:
            n = vals.index[-1] - vals.index[0]
            cagr = round(((vals.iloc[-1] / vals.iloc[0]) ** (1 / n) - 1) * 100, 1) if n else None
        return {"country": resolved, "flow": flow, "years": self.years,
                "values_b": series, "cagr_pct": cagr,
                "latest_b": round(vals.iloc[-1] / 1e9, 2) if len(vals) else None}

    def country_profile(self, country, year=None):
        year = year or self.latest
        exp_name = self.resolve_country(country, "export")
        imp_name = self.resolve_country(country, "import")
        name = exp_name or imp_name
        if not name:
            return {"error": f"Country '{country}' not found."}
        ex = self.exports[(self.exports.country == name) & (self.exports.year == year)]["trade_value_usd"].sum()
        im = self.imports[(self.imports.country == name) & (self.imports.year == year)]["trade_value_usd"].sum()
        # rank
        exp_rank = imp_rank = None
        et = self.top("export", year, n=500)
        it = self.top("import", year, n=500)
        for i, r in enumerate(et, 1):
            if r["country"] == name:
                exp_rank = i
        for i, r in enumerate(it, 1):
            if r["country"] == name:
                imp_rank = i
        return {
            "country": name, "year": year,
            "exports_b": round(ex / 1e9, 2), "imports_b": round(im / 1e9, 2),
            "trade_balance_b": round((ex - im) / 1e9, 2),
            "export_yoy_pct": self._yoy(self.exports, name, year),
            "import_yoy_pct": self._yoy(self.imports, name, year),
            "export_rank": exp_rank, "import_rank": imp_rank,
        }

    def corridors(self, n=15, exporter=None, importer=None, year=None):
        year = year or self.bilateral["year"].max()
        df = self.bilateral[self.bilateral.year == year]
        if exporter:
            ex = self.resolve_country(exporter, "export")
            if ex:
                df = df[df.exporter == ex]
        if importer:
            df = df[df.importer.str.lower().str.contains(importer.strip().lower(), na=False)]
        ranked = (df.groupby(["exporter", "exporter_iso3", "importer", "importer_iso3"],
                             as_index=False)["trade_value_usd"].sum()
                  .sort_values("trade_value_usd", ascending=False).head(n))
        return [{"exporter": r.exporter, "importer": r.importer,
                 "from_flag": flag_for(r.exporter_iso3), "to_flag": flag_for(r.importer_iso3),
                 "value_b": round(r.trade_value_usd / 1e9, 3)} for r in ranked.itertuples()]

    def region_breakdown(self, year=None):
        year = year or self.latest
        out = []
        for region, g in self.exports.groupby("region"):
            cur = g[g.year == year]["trade_value_usd"].sum()
            base = g[g.year == self.first]["trade_value_usd"].sum()
            n = year - self.first
            cagr = round(((cur / base) ** (1 / n) - 1) * 100, 1) if base > 0 and n else None
            out.append({"region": region, "exports_b": round(cur / 1e9, 2), "cagr_pct": cagr})
        return sorted(out, key=lambda x: x["exports_b"], reverse=True)

    # ---------- full dashboard payload ----------
    def build_payload(self, year=None):
        # year drives the "current" views (KPIs, top tables, map, matrix);
        # trend charts always span all available years.
        yr = int(year) if year and int(year) in self.years else self.latest
        years = [str(y) for y in self.years]

        def series(flow, names):
            df = self._flow_df(flow)
            d = {}
            for nm in names:
                s = (df[df.country == nm].groupby("year")["trade_value_usd"].sum()
                     .reindex(self.years))
                d[nm] = [None if pd.isna(v) else round(v / 1e9, 3) for v in s.values]
            return d

        top_exp = self.top("export", yr, 10)
        top_imp = self.top("import", yr, 10)

        # global volume per year
        ge = self.exports.groupby("year")["trade_value_usd"].sum().reindex(self.years)
        gi = self.imports.groupby("year")["trade_value_usd"].sum().reindex(self.years)
        vol_exp = [round(v / 1e9, 2) if not pd.isna(v) else None for v in ge.values]
        vol_imp = [round(v / 1e9, 2) if not pd.isna(v) else None for v in gi.values]

        # KPIs (for the selected year)
        cur_exp = ge.loc[yr]
        prev_exp = ge.loc[yr - 1] if (yr - 1) in ge.index else None
        cur_imp = gi.loc[yr]
        prev_imp = gi.loc[yr - 1] if (yr - 1) in gi.index else None
        n_years = yr - self.first
        base_exp = ge.loc[self.first]
        cagr = round(((cur_exp / base_exp) ** (1 / n_years) - 1) * 100, 1) if base_exp and n_years else None
        byear = min(yr, int(self.bilateral["year"].max()))
        corridors_latest = self.bilateral[self.bilateral.year == byear]
        n_corridors = corridors_latest.groupby(["exporter", "importer"]).ngroups

        kpis = {
            "year": yr,
            "global_exports_b": round(cur_exp / 1e9, 1),
            "exports_yoy": round((cur_exp - prev_exp) / prev_exp * 100, 1) if prev_exp else None,
            "global_imports_b": round(cur_imp / 1e9, 1),
            "imports_yoy": round((cur_imp - prev_imp) / prev_imp * 100, 1) if prev_imp else None,
            "cagr_pct": cagr, "first_year": self.first, "latest_year": self.latest,
            "tracked_corridors": int(n_corridors),
        }

        # bilateral matrix among the top exporters that are also tracked
        tracked = list(self.bilateral["exporter"].unique())
        order = [r["country"] for r in top_exp if r["country"] in tracked][:8]
        if len(order) < 8:
            for nm in tracked:
                if nm not in order:
                    order.append(nm)
                if len(order) == 8:
                    break
        bsub = self.bilateral[self.bilateral.year == byear]
        matrix = []
        for ex in order:
            row = []
            for im in order:
                if ex == im:
                    row.append(None)
                else:
                    v = bsub[(bsub.exporter == ex) & (bsub.importer == im)]["trade_value_usd"].sum()
                    row.append(round(v / 1e9, 3))
            matrix.append(row)

        # map data (selected year, all countries)
        ex_latest = self.exports[self.exports.year == yr]
        im_latest = self.imports[self.imports.year == yr]
        ex_map = ex_latest.groupby(["iso_numeric", "iso3", "country"], as_index=False)["trade_value_usd"].sum()
        im_map = im_latest.set_index("iso3")["trade_value_usd"].groupby(level=0).sum().to_dict()
        map_data = []
        for r in ex_map.itertuples():
            if pd.isna(r.iso_numeric):
                continue
            imp_v = im_map.get(r.iso3, 0)
            map_data.append({
                "iso_numeric": int(r.iso_numeric), "iso3": r.iso3, "country": r.country,
                "flag": flag_for(r.iso3),
                "export_b": round(r.trade_value_usd / 1e9, 3),
                "import_b": round(imp_v / 1e9, 3),
            })
        # add import-only countries
        seen = {m["iso3"] for m in map_data}
        for r in im_latest.groupby(["iso_numeric", "iso3", "country"], as_index=False)["trade_value_usd"].sum().itertuples():
            if pd.isna(r.iso_numeric) or r.iso3 in seen:
                continue
            map_data.append({"iso_numeric": int(r.iso_numeric), "iso3": r.iso3,
                             "country": r.country, "flag": flag_for(r.iso3), "export_b": 0,
                             "import_b": round(r.trade_value_usd / 1e9, 3)})

        # corridors for the selected year, with ISO numerics for map flow arcs
        name_iso = {m["country"]: m["iso_numeric"] for m in map_data}
        corridors = self.corridors(12, year=byear)
        for c in corridors:
            c["from_iso"] = name_iso.get(c["exporter"])
            c["to_iso"] = name_iso.get(c["importer"])

        return {
            "meta": {"hs_code": "3304", "years": years, "latest": str(self.latest),
                     "source": "UN Comtrade (official customs statistics)"},
            "kpis": kpis,
            "top_exporters": top_exp,
            "top_importers": top_imp,
            "export_trends": series("export", [r["country"] for r in top_exp]),
            "import_trends": series("import", [r["country"] for r in top_imp]),
            "global_volume": {"years": years, "exports": vol_exp, "imports": vol_imp},
            "regions": self.region_breakdown(yr),
            "bilateral": {"countries": order, "matrix": matrix},
            "corridors": corridors,
            "map": map_data,
            "opportunities": self._opportunities(yr),
        }

    def _opportunities(self, year=None):
        """Data-driven opportunity cards (real numbers, not hand-written)."""
        year = year or self.latest
        out = []
        # 1) fastest-growing importers (YoY) among sizeable markets (>$500M)
        it = self.top("import", year, 40)
        growers = [r for r in it if r["yoy_pct"] is not None and r["value_b"] > 0.5]
        growers.sort(key=lambda r: r["yoy_pct"], reverse=True)
        for r in growers[:3]:
            out.append({
                "tag": "rising", "title": f"{r['country']} — fast-growing import market",
                "desc": (f"{r['country']} cosmetics imports grew {r['yoy_pct']:+.1f}% YoY to "
                         f"${r['value_b']:.2f}B, making it one of the fastest-expanding "
                         f"destination markets for HS 3304."),
                "metrics": [{"l": "Import YoY", "v": f"{r['yoy_pct']:+.1f}%"},
                            {"l": "Market size", "v": f"${r['value_b']:.2f}B"},
                            {"l": "Global rank", "v": f"#{it.index(r)+1}"}],
            })
        # 2) biggest net importers (import >> export = supply gap)
        gaps = []
        for r in self.top("import", year, 30):
            prof = self.country_profile(r["country"], year)
            if prof.get("trade_balance_b", 0) < 0:
                gaps.append((r["country"], prof["imports_b"], prof["trade_balance_b"]))
        gaps.sort(key=lambda x: x[2])
        for country, imp_b, bal in gaps[:2]:
            out.append({
                "tag": "hot", "title": f"{country} — large net-import gap",
                "desc": (f"{country} runs a ${abs(bal):.2f}B cosmetics trade deficit "
                         f"(imports ${imp_b:.2f}B), signalling demand well above domestic "
                         f"supply — an opening for exporters and e-commerce sellers."),
                "metrics": [{"l": "Imports", "v": f"${imp_b:.2f}B"},
                            {"l": "Trade balance", "v": f"-${abs(bal):.2f}B"}],
            })
        # 3) fastest-growing bilateral corridor
        b = self.bilateral
        yrs = sorted(b["year"].unique())
        if len(yrs) >= 2:
            piv = (b.assign(lane=b.exporter + " → " + b.importer)
                   .pivot_table(index="lane", columns="year", values="trade_value_usd", aggfunc="sum"))
            f, l = yrs[0], yrs[-1]
            if f in piv.columns and l in piv.columns:
                g = piv[[f, l]].dropna()
                g = g[g[f] > 5e6]
                g["growth"] = (g[l] - g[f]) / g[f] * 100
                for lane, row in g.sort_values("growth", ascending=False).head(2).iterrows():
                    out.append({
                        "tag": "emerging", "title": f"Emerging lane: {lane}",
                        "desc": (f"The {lane} corridor grew {row['growth']:+.0f}% from {f} to {l}, "
                                 f"reaching ${row[l]/1e9:.2f}B — a rising trade route worth tracking."),
                        "metrics": [{"l": f"{f}→{l} growth", "v": f"{row['growth']:+.0f}%"},
                                    {"l": f"{l} value", "v": f"${row[l]/1e9:.2f}B"}],
                    })
        return out


# module-level singleton (lazy)
_data = None


def get_data():
    global _data
    if _data is None:
        _data = TradeData()
    return _data
