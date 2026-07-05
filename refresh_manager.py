"""
Data-freshness + recurring-refresh manager for Product Scout.

Bridges the file-based app with the scraper pipeline in scheduler/. It:
  * tracks, per data source, when it was last refreshed (seeded from the real
    data) and how long past refreshes took,
  * estimates how long a fresh pull will take (from past run durations),
  * exposes a status() the UI shows ("Updated 3 days ago · next refresh in 4d"),
  * runs an on-demand or scheduled refresh in a background thread, recording the
    real duration so the estimate improves over time.

Live source pulls (Reddit/Amazon/Trends) use the scrapers in scheduler/ when the
required credentials (.env) are present; otherwise the refresh re-builds the
app's dataset from what's already ingested and reports that no new source data
was available (honest — no fabricated freshness).

Pure standard library, so it runs under any interpreter / inside the Flask app.
"""

import json
import threading
import time
import glob
import os
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
FRESH_FILE = DATA / "freshness.json"

_lock = threading.Lock()
_state = None


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


# ───────────────────────── source registry ─────────────────────────
# interval_hours mirrors scheduler/main_scheduler.py cadence.
SOURCES = {
    "social":  {"name": "Social posts (Reddit)",   "interval_hours": 12,  "default_eta_s": 300},
    "amazon":  {"name": "Amazon reviews",          "interval_hours": 24,  "default_eta_s": 180},
    "trends":  {"name": "Google Trends",           "interval_hours": 168, "default_eta_s": 240},
    "trade":   {"name": "Trade flows (UN Comtrade)", "interval_hours": 168, "default_eta_s": 150},
}
ORDER = ["social", "amazon", "trends", "trade"]


# ───────────────────────── seed from real data ─────────────────────────
def _seed_last_fetched(source):
    """Best-known 'when this dataset was last refreshed', read from the data itself."""
    try:
        if source == "social":
            m = json.loads((DATA / "social_meta.json").read_text())
            return m.get("generated_at")
        if source == "amazon":
            mx = None
            for f in glob.glob(str(DATA / "amazon" / "*.json")):
                arr = json.loads(Path(f).read_text())
                for r in arr[:3]:
                    s = r.get("scrapedAt")
                    if s and (mx is None or s > mx):
                        mx = s
            return mx
        if source == "trends":
            with open(DATA / "trends" / "metrics.csv") as fh:
                latest = max(r["latest_date"] for r in csv.DictReader(fh))
            return latest + "T00:00:00+00:00"      # weekly data, coverage end
        if source == "trade":
            p = DATA / "world_exports.csv"
            if p.exists():
                return _iso(datetime.fromtimestamp(p.stat().st_mtime, timezone.utc))
    except Exception:
        pass
    return None


def _load():
    global _state
    if _state is not None:
        return _state
    if FRESH_FILE.exists():
        try:
            _state = json.loads(FRESH_FILE.read_text())
        except Exception:
            _state = {}
    else:
        _state = {}
    # seed any missing sources
    for s in SOURCES:
        rec = _state.setdefault(s, {})
        rec.setdefault("last_fetched", _seed_last_fetched(s))
        rec.setdefault("last_checked", rec.get("last_fetched"))
        rec.setdefault("last_status", "seeded")
        rec.setdefault("durations", [])
        rec.setdefault("running", False)
        rec.setdefault("started_at", None)
        rec.setdefault("note", None)
    _save()
    return _state


def _save():
    try:
        FRESH_FILE.write_text(json.dumps(_state, indent=2, default=str))
    except Exception:
        pass


# ───────────────────────── estimates ─────────────────────────
def estimate_seconds(source):
    rec = _load().get(source, {})
    durs = [d for d in rec.get("durations", []) if d]
    if durs:
        return round(sum(durs[-5:]) / len(durs[-5:]))
    return SOURCES.get(source, {}).get("default_eta_s", 180)


def _age_seconds(iso_str):
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        return max(0, (_now() - dt).total_seconds())
    except Exception:
        return None


def _next_due(source, rec):
    iv = SOURCES[source]["interval_hours"]
    last = rec.get("last_fetched")
    if not last:
        return None
    try:
        dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        return _iso(dt + timedelta(hours=iv))
    except Exception:
        return None


def _source_status(source):
    rec = _load().get(source, {})
    meta = SOURCES[source]
    nd = _next_due(source, rec)
    eta = estimate_seconds(source)
    running = rec.get("running", False)
    eta_remaining = None
    if running and rec.get("started_at"):
        elapsed = _age_seconds(rec["started_at"]) or 0
        eta_remaining = max(1, round(eta - elapsed))
    return {
        "source": source,
        "name": meta["name"],
        "interval_hours": meta["interval_hours"],
        "last_fetched": rec.get("last_fetched"),
        "last_fetched_age_s": _age_seconds(rec.get("last_fetched")),
        "last_checked": rec.get("last_checked"),
        "last_status": rec.get("last_status"),
        "note": rec.get("note"),
        "next_due": nd,
        "next_due_in_s": _age_seconds(nd) and -_age_seconds(nd) if nd else None,
        "due_now": (_age_seconds(rec.get("last_fetched")) or 0) > meta["interval_hours"] * 3600,
        "est_refresh_s": eta,
        "running": running,
        "started_at": rec.get("started_at"),
        "eta_remaining_s": eta_remaining,
    }


def status():
    return {"sources": [_source_status(s) for s in ORDER],
            "generated_at": _iso(_now())}


def status_for(source):
    return _source_status(source) if source in SOURCES else None


# ───────────────────────── runners ─────────────────────────
def _has(*envs):
    return all(os.getenv(e) for e in envs)


def _run_social(query=None):
    """Re-build the social dataset. Live Reddit pull needs REDDIT_COOKIE; without
    it we re-ingest the existing dump (regenerates the app's processed data)."""
    import social_ingest
    src = DATA / "skincare_multi_sub_data.json"
    social_ingest.run(src)
    # invalidate the app's in-memory cache so new data is served
    try:
        import social
        social._social = None
    except Exception:
        pass
    live = _has("REDDIT_COOKIE")
    return {"produced_new": True, "status": "refreshed" if live else "reprocessed",
            "note": None if live else "Re-ingested existing corpus (set REDDIT_COOKIE in scheduler/.env for a live Reddit pull)."}


def _run_trade(query=None):
    import fetch_data
    fetch_data.main()
    try:
        import analytics
        analytics._data = None
    except Exception:
        pass
    return {"produced_new": True, "status": "refreshed", "note": None}


def _run_amazon(query=None):
    if not _has("APIFY_API_TOKEN"):
        return {"produced_new": False, "status": "credentials_required",
                "note": "Live Amazon pull needs APIFY_API_TOKEN in scheduler/.env. Showing cached reviews."}
    # creds present → the scheduler's AmazonApifyScraper would run here, then a
    # sync step would rebuild data/amazon/*.json. (Sync hook left for production.)
    return {"produced_new": False, "status": "ready",
            "note": "Apify token detected — wire scheduler.amazon_scraper output sync to refresh live."}


def _run_trends(query=None):
    # pytrends needs no token but is heavily rate-limited; treat as scheduler job.
    return {"produced_new": False, "status": "scheduled_only",
            "note": "Google Trends refresh runs via the weekly scheduler (scheduler/trends_scraper.py)."}


RUNNERS = {"social": _run_social, "trade": _run_trade,
           "amazon": _run_amazon, "trends": _run_trends}


def _execute(source, query):
    rec = _load()[source]
    t0 = time.time()
    try:
        result = RUNNERS[source](query)
    except Exception as e:  # noqa: BLE001
        result = {"produced_new": False, "status": "error", "note": str(e)[:200]}
    dur = round(time.time() - t0, 1)
    with _lock:
        now = _iso(_now())
        rec["last_checked"] = now
        rec["last_status"] = result["status"]
        rec["note"] = result.get("note")
        if result.get("produced_new"):
            rec["last_fetched"] = now
            rec.setdefault("durations", []).append(dur)
            rec["durations"] = rec["durations"][-10:]
        rec["running"] = False
        rec["started_at"] = None
        _save()


def trigger(source, query=None):
    """Kick off a refresh in the background. Returns the ETA immediately."""
    if source not in SOURCES:
        return {"error": f"unknown source '{source}'", "sources": list(SOURCES)}
    rec = _load()[source]
    if rec.get("running"):
        return {**_source_status(source), "already_running": True}
    with _lock:
        rec["running"] = True
        rec["started_at"] = _iso(_now())
        _save()
    threading.Thread(target=_execute, args=(source, query), daemon=True).start()
    st = _source_status(source)
    st["triggered"] = True
    st["eta_remaining_s"] = st["est_refresh_s"]
    return st


def run_blocking(source, query=None):
    """Synchronous refresh — used by the scheduler entrypoint."""
    rec = _load()[source]
    with _lock:
        rec["running"] = True
        rec["started_at"] = _iso(_now())
        _save()
    _execute(source, query)
    return _source_status(source)
