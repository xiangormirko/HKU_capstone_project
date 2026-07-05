"""
Ingest real global cosmetics trade data (HS 3304 — beauty / make-up
preparations) from the free, legal UN Comtrade public API.

Produces three CSVs in data/:
  world_exports.csv  — each country's TOTAL exports to the World, per year
  world_imports.csv  — each country's TOTAL imports from the World, per year
  bilateral.csv      — exporter -> importer flows (for corridors & matrix)

Each row is enriched with ISO alpha-3, ISO numeric (to join the D3 world map)
and a world region (for regional growth analysis).

The commercial aggregators (e.g. Volza) resell exactly this customs data; here
we go straight to the public source — no scraping, no paywall.
"""

import time
import sys
import datetime
import requests
import pandas as pd
import pycountry
import pycountry_convert as pcc
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

ANNUAL_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
MONTHLY_URL = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
PREVIEW_URL = ANNUAL_URL  # back-compat
HS_CODE = "3304"

# Annual coverage. Bump END_YEAR as UN Comtrade publishes newer years; an
# empty/unpublished year is simply skipped, so it's safe to look ahead.
START_YEAR, END_YEAR = 2018, 2025
YEARS = list(range(START_YEAR, END_YEAR + 1))


def _recent_months(n=15):
    """Last `n` calendar months as YYYYMM ints, oldest first (for the rolling
    monthly trend). Months Comtrade hasn't published yet return no data and are
    dropped downstream."""
    d = datetime.date.today().replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.year * 100 + d.month)
        d = (d.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    return sorted(out)


MONTHS = _recent_months(15)

# Major cosmetics exporters (Comtrade M49 codes) — used for bilateral flows,
# which the free 500-row/call preview can only return one reporter at a time.
MAJOR_EXPORTERS = {
    251: "France", 842: "USA", 276: "Germany", 410: "Rep. of Korea",
    156: "China", 826: "United Kingdom", 380: "Italy", 392: "Japan",
    724: "Spain", 616: "Poland", 702: "Singapore", 528: "Netherlands",
    56: "Belgium", 124: "Canada", 699: "India", 372: "Ireland",
    757: "Switzerland", 344: "China, Hong Kong SAR", 764: "Thailand",
    484: "Mexico", 76: "Brazil", 792: "Türkiye", 203: "Czechia",
}

CONTINENT_NAMES = {
    "AF": "Africa", "AS": "Asia", "EU": "Europe",
    "NA": "North America", "SA": "Latin America", "OC": "Oceania",
}
# Finer buckets than raw continents for trade analysis
REGION_OVERRIDE = {
    "KOR": "East Asia", "JPN": "East Asia", "CHN": "East Asia",
    "HKG": "East Asia", "TWN": "East Asia", "MNG": "East Asia",
    "THA": "SE Asia", "VNM": "SE Asia", "IDN": "SE Asia", "MYS": "SE Asia",
    "SGP": "SE Asia", "PHL": "SE Asia", "MMR": "SE Asia", "KHM": "SE Asia",
    "IND": "South Asia", "PAK": "South Asia", "BGD": "South Asia", "LKA": "South Asia",
    "ARE": "MENA", "SAU": "MENA", "QAT": "MENA", "KWT": "MENA", "ISR": "MENA",
    "EGY": "MENA", "TUR": "MENA", "IRN": "MENA", "JOR": "MENA", "LBN": "MENA",
}


def country_meta(iso3):
    """ISO3 -> (iso_numeric, region). Robust to unknown / aggregate codes."""
    try:
        c = pycountry.countries.get(alpha_3=iso3)
        numeric = int(c.numeric)
        if iso3 in REGION_OVERRIDE:
            region = REGION_OVERRIDE[iso3]
        else:
            cont = pcc.country_alpha2_to_continent_code(c.alpha_2)
            region = CONTINENT_NAMES.get(cont, "Other")
        return numeric, region
    except Exception:  # noqa: BLE001
        return None, "Other"


def get(params, url=ANNUAL_URL, tries=5):
    """GET with exponential backoff on 429 (the free preview is rate-limited)."""
    delay = 1.5
    for attempt in range(tries):
        r = requests.get(url, params=params, timeout=60)
        if r.status_code == 429:
            if attempt == tries - 1:
                r.raise_for_status()
            time.sleep(delay)
            delay *= 2
            continue
        r.raise_for_status()
        return r.json().get("data", [])
    return []


def load_country_lookup():
    lookup = {}
    for url, ck, dk, ik in [
        ("https://comtradeapi.un.org/files/v1/app/reference/Reporters.json",
         "reporterCode", "reporterDesc", "reporterCodeIsoAlpha3"),
        ("https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json",
         "PartnerCode", "PartnerDesc", "PartnerCodeIsoAlpha3"),
    ]:
        for r in requests.get(url, timeout=30).json()["results"]:
            lookup[int(r[ck])] = (r[dk], r.get(ik))
    return lookup


def fetch_world_totals(flow):
    """One country-total row per reporter per year (partner = World)."""
    frames = []
    for year in YEARS:
        params = {
            "reporterCode": "", "period": str(year), "partnerCode": "0",
            "cmdCode": HS_CODE, "flowCode": flow, "partner2Code": "0",
            "customsCode": "C00", "motCode": "0",
        }
        try:
            data = get(params)
        except Exception as e:  # noqa: BLE001
            print(f"  {year}: FAILED ({e})")
            continue
        print(f"  {year}: {len(data)} countries")
        if data:
            frames.append(pd.DataFrame(data))
        time.sleep(0.4)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_bilateral():
    frames = []
    for code, name in MAJOR_EXPORTERS.items():
        got = 0
        for year in YEARS:
            params = {
                "reporterCode": str(code), "period": str(year), "partnerCode": "",
                "cmdCode": HS_CODE, "flowCode": "X", "partner2Code": "0",
                "customsCode": "C00", "motCode": "0",
            }
            try:
                data = get(params)
            except Exception:  # noqa: BLE001
                continue
            if data:
                frames.append(pd.DataFrame(data))
                got += len(data)
            time.sleep(0.35)
        print(f"  {name:<22} {got} rows")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_monthly(flow):
    """World-total value per reporter per MONTH (partner = World), for the last
    ~15 months. One call per month keeps each response under the 500-row cap."""
    frames = []
    for period in MONTHS:
        params = {
            "reporterCode": "", "period": str(period), "partnerCode": "0",
            "cmdCode": HS_CODE, "flowCode": flow, "partner2Code": "0",
            "customsCode": "C00", "motCode": "0",
        }
        try:
            data = get(params, url=MONTHLY_URL)
        except Exception as e:  # noqa: BLE001
            print(f"  {period}: FAILED ({e})")
            continue
        if data:
            print(f"  {period}: {len(data)} countries")
            frames.append(pd.DataFrame(data))
        time.sleep(0.5)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def tidy_monthly(df, lookup, flow):
    if df.empty:
        return df
    period = df["period"].astype(str)
    out = pd.DataFrame({
        "period": period,
        "year": period.str[:4].astype(int),
        "month": period.str[4:6].astype(int),
        "code": df["reporterCode"],
        "flow": "export" if flow == "X" else "import",
        "trade_value_usd": pd.to_numeric(df["primaryValue"], errors="coerce"),
    })
    out["country"] = out["code"].map(lambda c: lookup.get(int(c), ("?", None))[0])
    out["iso3"] = out["code"].map(lambda c: lookup.get(int(c), ("?", None))[1])
    out = out.dropna(subset=["trade_value_usd"])
    out = out[(out["trade_value_usd"] > 0) & (out["iso3"].notna())]
    return out


def tidy_totals(df, lookup, who_col):
    out = pd.DataFrame({
        "year": df["refYear"],
        "code": df["reporterCode"],
        "trade_value_usd": pd.to_numeric(df["primaryValue"], errors="coerce"),
        "net_weight_kg": pd.to_numeric(df.get("netWgt"), errors="coerce"),
    })
    out["country"] = out["code"].map(lambda c: lookup.get(int(c), ("?", None))[0])
    out["iso3"] = out["code"].map(lambda c: lookup.get(int(c), ("?", None))[1])
    meta = out["iso3"].map(lambda i: country_meta(i) if isinstance(i, str) else (None, "Other"))
    out["iso_numeric"] = meta.map(lambda m: m[0])
    out["region"] = meta.map(lambda m: m[1])
    out = out.dropna(subset=["trade_value_usd"])
    out = out[(out["trade_value_usd"] > 0) & (out["iso3"].notna())]
    out = out.rename(columns={"country": who_col})
    return out


def main():
    print("Loading reference tables ...")
    lookup = load_country_lookup()

    print("\nFetching WORLD-TOTAL EXPORTS (flow X) ...")
    exp = tidy_totals(fetch_world_totals("X"), lookup, "country")
    exp.to_csv(DATA_DIR / "world_exports.csv", index=False)
    print(f"  -> {len(exp):,} rows, {exp['country'].nunique()} countries")

    print("\nFetching WORLD-TOTAL IMPORTS (flow M) ...")
    imp = tidy_totals(fetch_world_totals("M"), lookup, "country")
    imp.to_csv(DATA_DIR / "world_imports.csv", index=False)
    print(f"  -> {len(imp):,} rows, {imp['country'].nunique()} countries")

    print("\nFetching BILATERAL EXPORT FLOWS (major exporters) ...")
    bi = fetch_bilateral()
    bt = pd.DataFrame({
        "year": bi["refYear"],
        "exporter": bi["reporterCode"].map(lambda c: lookup.get(int(c), ("?", None))[0]),
        "exporter_iso3": bi["reporterCode"].map(lambda c: lookup.get(int(c), ("?", None))[1]),
        "importer": bi["partnerCode"].map(lambda c: lookup.get(int(c), ("?", None))[0]),
        "importer_iso3": bi["partnerCode"].map(lambda c: lookup.get(int(c), ("?", None))[1]),
        "importer_code": bi["partnerCode"],
        "trade_value_usd": pd.to_numeric(bi["primaryValue"], errors="coerce"),
    })
    bt = bt[(bt["importer_code"] != 0) & (bt["trade_value_usd"] > 0)]  # drop World aggregate
    bt = bt.dropna(subset=["trade_value_usd"])
    bt.drop(columns=["importer_code"]).to_csv(DATA_DIR / "bilateral.csv", index=False)
    print(f"  -> {len(bt):,} bilateral rows")

    print("\nFetching MONTHLY WORLD TOTALS (rolling recency) ...")
    mx = tidy_monthly(fetch_monthly("X"), lookup, "X")
    mm = tidy_monthly(fetch_monthly("M"), lookup, "M")
    monthly = pd.concat([mx, mm], ignore_index=True)
    if not monthly.empty:
        monthly = monthly.drop(columns=["code"])
        monthly.to_csv(DATA_DIR / "monthly_trade.csv", index=False)
        span = f"{monthly['period'].min()}–{monthly['period'].max()}"
        print(f"  -> {len(monthly):,} monthly rows, {span}")
    else:
        print("  -> no monthly data returned (skipped)")

    if exp.empty or imp.empty:
        print("\nWARNING: missing world totals — check connection.", file=sys.stderr)
    print("\nDone. Years with data:", sorted(set(exp["year"]) | set(imp["year"])))


if __name__ == "__main__":
    main()
