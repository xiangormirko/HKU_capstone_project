"""
Ingest real global cosmetics trade data (HS 3304 — beauty / make-up preparations)
from the free, legal UN Comtrade public API and write directly into PostgreSQL.

Tables written:
1. world_exports — each country's TOTAL exports to the World, per year
2. world_imports — each country's TOTAL imports from the World, per year
3. bilateral — exporter -> importer flows (for corridors & matrix)
4. monthly_trade — rolling monthly totals (for recent trend analysis)

Each row is enriched with ISO alpha-3, ISO numeric, and a world region.
"""

import os
import time
import sys
import datetime
import urllib.parse
import requests
import pandas as pd
import pycountry
import pycountry_convert as pcc
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# -------------------------------------------------------------------------
# DATABASE CONNECTION SETUP
# -------------------------------------------------------------------------
load_dotenv()

db_user = os.getenv("DB_USER", "postgres")
db_password = urllib.parse.quote_plus(os.getenv("DB_PASSWORD", ""))
db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "5432")
db_name = os.getenv("DB_NAME", "capstone_db")

DATABASE_URL = os.getenv("DATABASE_URL") or f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
engine = create_engine(DATABASE_URL)

# -------------------------------------------------------------------------
# CONSTANTS & CONFIGURATIONS
# -------------------------------------------------------------------------
ANNUAL_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
MONTHLY_URL = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
HS_CODE = "3304"

# Annual coverage boundaries
BASE_HISTORY_YEAR = 2018

def get_target_years(full_history=False):
    """
    Dynamically calculate the target years based on the current execution date.
    - Full History: Fetches everything from BASE_HISTORY_YEAR to the current year.
    - Routine Update: Fetches only the last 2 years to capture lagging updates efficiently.
    """
    current_year = datetime.date.today().year
    if full_history:
        return list(range(BASE_HISTORY_YEAR, current_year + 1))
    else:
        # Routine mode: sync previous year and current year (e.g., 2025 and 2026)
        return [current_year - 1, current_year]


def _recent_months(n=15):
    """
    Generate the last `n` calendar months as YYYYMM integers, oldest first.
    Unpublished months from Comtrade will return empty and be skipped downstream.
    """
    d = datetime.date.today().replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.year * 100 + d.month)
        d = (d.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    return sorted(out)


MONTHS = _recent_months(15)

# Major cosmetics exporters (Comtrade M49 codes) for bilateral flows
MAJOR_EXPORTERS = {
    251: "France",
    842: "USA",
    276: "Germany",
    410: "Rep. of Korea",
    156: "China",
    826: "United Kingdom",
    380: "Italy",
    392: "Japan",
    724: "Spain",
    616: "Poland",
    702: "Singapore",
    528: "Netherlands",
    56: "Belgium",
    124: "Canada",
    699: "India",
    372: "Ireland",
    757: "Switzerland",
    344: "China, Hong Kong SAR",
    764: "Thailand",
    484: "Mexico",
    76: "Brazil",
    792: "Türkiye",
    203: "Czechia",
}

CONTINENT_NAMES = {
    "AF": "Africa",
    "AS": "Asia",
    "EU": "Europe",
    "NA": "North America",
    "SA": "Latin America",
    "OC": "Oceania",
}

# Regional mapping overrides for detailed trade flow breakdown
REGION_OVERRIDE = {
    "KOR": "East Asia", "JPN": "East Asia", "CHN": "East Asia",
    "HKG": "East Asia", "TWN": "East Asia", "MNG": "East Asia",
    "THA": "SE Asia", "VNM": "SE Asia", "IDN": "SE Asia",
    "MYS": "SE Asia", "SGP": "SE Asia", "PHL": "SE Asia",
    "MMR": "SE Asia", "KHM": "SE Asia",
    "IND": "South Asia", "PAK": "South Asia", "BGD": "South Asia", "LKA": "South Asia",
    "ARE": "MENA", "SAU": "MENA", "QAT": "MENA", "KWT": "MENA",
    "ISR": "MENA", "EGY": "MENA", "TUR": "MENA", "IRN": "MENA",
    "JOR": "MENA", "LBN": "MENA",
}


def country_meta(iso3):
    """
    Resolve ISO3 to (iso_numeric, region). 
    Safe fallback for unknown, aggregate, or disputed codes.
    """
    try:
        c = pycountry.countries.get(alpha_3=iso3)
        numeric = int(c.numeric)
        if iso3 in REGION_OVERRIDE:
            region = REGION_OVERRIDE[iso3]
        else:
            cont = pcc.country_alpha2_to_continent_code(c.alpha_2)
            region = CONTINENT_NAMES.get(cont, "Other")
        return numeric, region
    except Exception:
        return None, "Other"


def get(params, url=ANNUAL_URL, tries=5):
    """
    HTTP GET wrapper with exponential backoff for 429 Rate Limiting.
    """
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
    """
    Fetch reference tables from UN Comtrade for reporters and partner areas mapping.
    """
    lookup = {}
    for url, ck, dk, ik in [
        ("https://comtradeapi.un.org/files/v1/app/reference/Reporters.json", "reporterCode", "reporterDesc", "reporterCodeIsoAlpha3"),
        ("https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json", "PartnerCode", "PartnerDesc", "PartnerCodeIsoAlpha3"),
    ]:
        for r in requests.get(url, timeout=30).json()["results"]:
            lookup[int(r[ck])] = (r[dk], r.get(ik))
    return lookup


def fetch_world_totals(flow, years):
    """
    Fetch annual total trade volumes for all countries over the target years.
    """
    frames = []
    for year in years:
        params = {
            "reporterCode": "",
            "period": str(year),
            "partnerCode": "0",
            "cmdCode": HS_CODE,
            "flowCode": flow,
            "partner2Code": "0",
            "customsCode": "C00",
            "motCode": "0",
        }
        try:
            data = get(params)
        except Exception as e:
            print(f" {year}: FAILED ({e})")
            continue
        print(f" {year}: {len(data)} countries")
        if data:
            frames.append(pd.DataFrame(data))
        time.sleep(0.4)
    valid_frames = [f for f in frames if not f.empty]
    return pd.concat(valid_frames, ignore_index=True) if valid_frames else pd.DataFrame()


def fetch_bilateral(years):
    """
    Fetch annual bilateral trade details for MAJOR_EXPORTERS over the target years.
    """
    frames = []
    for code, name in MAJOR_EXPORTERS.items():
        got = 0
        for year in years:
            params = {
                "reporterCode": str(code),
                "period": str(year),
                "partnerCode": "",
                "cmdCode": HS_CODE,
                "flowCode": "X",
                "partner2Code": "0",
                "customsCode": "C00",
                "motCode": "0",
            }
            try:
                data = get(params)
            except Exception:
                continue
            if data:
                frames.append(pd.DataFrame(data))
                got += len(data)
            time.sleep(0.35)
        print(f" {name:<22} {got} rows")
    valid_frames = [f for f in frames if not f.empty]
    return pd.concat(valid_frames, ignore_index=True) if valid_frames else pd.DataFrame()


def fetch_monthly(flow):
    """
    Fetch rolling monthly trade volumes for all countries (Partner = World).
    """
    frames = []
    for period in MONTHS:
        params = {
            "reporterCode": "",
            "period": str(period),
            "partnerCode": "0",
            "cmdCode": HS_CODE,
            "flowCode": flow,
            "partner2Code": "0",
            "customsCode": "C00",
            "motCode": "0",
        }
        try:
            data = get(params, url=MONTHLY_URL)
        except Exception as e:
            print(f" {period}: FAILED ({e})")
            continue
        if data:
            print(f" {period}: {len(data)} countries")
            frames.append(pd.DataFrame(data))
        time.sleep(0.5)
    valid_frames = [f for f in frames if not f.empty]
    return pd.concat(valid_frames, ignore_index=True) if valid_frames else pd.DataFrame()


def tidy_monthly(df, lookup, flow):
    """
    Clean, filter, and structure the monthly trade DataFrame.
    """
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
    """
    Clean, enrich, and structure the annual global total trade DataFrame.
    """
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


def main(full_history=False):
    target_years = get_target_years(full_history=full_history)
    print(f"Target execution timeline identified: {target_years}")
    
    print("Loading reference tables ...")
    lookup = load_country_lookup()

    print("\nConnecting to PostgreSQL database...")
    with engine.begin() as conn:

        # 1. WORLD-TOTAL EXPORTS
        print("\nFetching WORLD-TOTAL EXPORTS (flow X) ...")
        exp = tidy_totals(fetch_world_totals("X", target_years), lookup, "country")
        if not exp.empty:
            print(f" -> Refreshing years {target_years} in 'world_exports'...")
            # Targeted deletion to prevent wiping out older historical constants
            conn.execute(text(f"DELETE FROM world_exports WHERE year IN ({','.join(map(str, target_years))})"))
            exp.to_sql("world_exports", con=conn, if_exists="append", index=False)
        else:
            print(" Warning: No export data returned.")

        # 2. WORLD-TOTAL IMPORTS
        print("\nFetching WORLD-TOTAL IMPORTS (flow M) ...")
        imp = tidy_totals(fetch_world_totals("M", target_years), lookup, "country")
        if not imp.empty:
            print(f" -> Refreshing years {target_years} in 'world_imports'...")
            conn.execute(text(f"DELETE FROM world_imports WHERE year IN ({','.join(map(str, target_years))})"))
            imp.to_sql("world_imports", con=conn, if_exists="append", index=False)
        else:
            print(" Warning: No import data returned.")

        # 3. BILATERAL EXPORT FLOWS
        print("\nFetching BILATERAL EXPORT FLOWS (major exporters) ...")
        bi = fetch_bilateral(target_years)
        if not bi.empty:
            bt = pd.DataFrame({
                "year": bi["refYear"],
                "exporter": bi["reporterCode"].map(lambda c: lookup.get(int(c), ("?", None))[0]),
                "exporter_iso3": bi["reporterCode"].map(lambda c: lookup.get(int(c), ("?", None))[1]),
                "importer": bi["partnerCode"].map(lambda c: lookup.get(int(c), ("?", None))[0]),
                "importer_iso3": bi["partnerCode"].map(lambda c: lookup.get(int(c), ("?", None))[1]),
                "importer_code": bi["partnerCode"],
                "trade_value_usd": pd.to_numeric(bi["primaryValue"], errors="coerce"),
            })
            bt = bt[(bt["importer_code"] != 0) & (bt["trade_value_usd"] > 0)]
            bt = bt.dropna(subset=["trade_value_usd"])
            bt_final = bt.drop(columns=["importer_code"])

            print(f" -> Refreshing years {target_years} in 'bilateral'...")
            conn.execute(text(f"DELETE FROM bilateral WHERE year IN ({','.join(map(str, target_years))})"))
            bt_final.to_sql("bilateral", con=conn, if_exists="append", index=False)
        else:
            print(" Warning: No bilateral data returned.")

        # 4. MONTHLY WORLD TOTALS (Always completely refreshed as it is a short rolling window)
        print("\nFetching MONTHLY WORLD TOTALS (rolling recency) ...")
        mx = tidy_monthly(fetch_monthly("X"), lookup, "X")
        mm = tidy_monthly(fetch_monthly("M"), lookup, "M")
        monthly = pd.concat([mx, mm], ignore_index=True) if (not mx.empty or not mm.empty) else pd.DataFrame()

        if not monthly.empty:
            monthly = monthly.drop(columns=["code"])
            print(" -> Truncating and rewriting 'monthly_trade' table...")
            conn.execute(text("TRUNCATE TABLE monthly_trade;"))
            monthly.to_sql("monthly_trade", con=conn, if_exists="append", index=False)
        else:
            print(" -> No monthly data returned (skipped or failed)")

    print("\nDatabase ingestion pipeline executed successfully!")


if __name__ == "__main__":
    # If run manually via terminal, you can choose to force a full historical backfill:
    # e.g., python fetch_data.py --full
    import sys
    force_full = "--full" in sys.argv
    main(full_history=force_full)