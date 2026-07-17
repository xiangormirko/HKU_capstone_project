"""
Core-logic tests for Product Scout.

These exercise the analytical layer directly (no network, no API key) against
the real data files in data/. They lock in the behaviours that are easy to
regress: partial-year handling, the pain-point negativity floor, opportunity
ranking, and the shared trade/monthly recency logic.

Run:  .venv/bin/python -m pytest -q
"""

import os
import sys

import analytics
import home
import fusion
import refresh_manager
from amazon import get_amazon


# ─────────────────────────── analytics / trade ───────────────────────────
def test_server_loads_project_dotenv_file(monkeypatch):
    for name in ["DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "ANTHROPIC_API_KEY", "PORT", "MODEL"]:
        monkeypatch.delenv(name, raising=False)
    sys.modules.pop("server", None)
    import server  # noqa: F401
    assert os.environ.get("DB_NAME") == "capstone_db"


def test_latest_complete_not_after_latest():
    td = analytics.TradeData()
    assert td.latest_complete in td.years
    assert td.latest_complete <= td.latest


def test_latest_complete_drops_partial_year():
    """The newest year is only partially reported; the complete year must have
    materially better country coverage than the newest one."""
    td = analytics.TradeData()
    if td.latest_complete == td.latest:
        return  # no partial year in the current data — nothing to check
    cov = td.exports.groupby("year")["iso3"].nunique().to_dict()
    assert cov[td.latest] < cov[td.latest_complete]


def test_growing_import_markets_sorted_and_filtered():
    td = analytics.TradeData()
    markets = td.growing_import_markets(n=5, min_b=0.3)
    assert markets, "expected at least one growing import market"
    yoys = [m["yoy_pct"] for m in markets]
    assert yoys == sorted(yoys, reverse=True)          # ranked by growth
    assert all(m["value_b"] >= 0.3 for m in markets)   # sizeable only
    assert all(m["yoy_pct"] is not None for m in markets)


def test_monthly_summary_excludes_sparse_months():
    td = analytics.TradeData()
    ms = td.monthly_summary()
    if not ms.get("available"):
        return  # monthly file absent — feature is optional
    m = td.monthly.copy()
    m["period"] = m["period"].astype(str)
    coverage = m.groupby("period")["iso3"].nunique()
    # the reported "latest" month must be reasonably complete, not a stub month
    assert ms["n_countries"] >= 0.6 * coverage.max()
    s = ms["series"]
    assert len(s["periods"]) == len(s["exports_b"]) == len(s["imports_b"])


def test_payload_charts_use_complete_years_only():
    td = analytics.TradeData()
    p = td.build_payload()
    chart_years = p["meta"]["years"]
    assert chart_years[-1] == str(td.latest_complete)
    assert str(td.latest) in p["meta"]["all_years"]
    # every partial year is flagged and excluded from the chart axis
    for py in p["meta"]["partial_years"]:
        assert py not in chart_years
    # volume series length matches the (complete) chart axis
    assert len(p["global_volume"]["exports"]) == len(chart_years)


def test_default_year_is_complete():
    td = analytics.TradeData()
    p = td.build_payload()
    assert p["kpis"]["year"] == td.latest_complete


# ─────────────────────────── amazon / pain points ───────────────────────────
def test_amazon_category_has_aspects():
    amz = get_amazon()
    cat = amz.available_categories()[0]
    d = amz.category(cat)
    assert d["available"]
    aspects = d["category_aspects"]
    assert aspects and all({"name", "mentions", "neg", "neg_rate"} <= set(a) for a in aspects)


def test_home_pain_points_pass_negativity_floor():
    """A 'pain point' must be genuinely negative (>=20%) and have real volume —
    not a high-traffic aspect that's mostly praised."""
    pts = home._pain_points(n=5)
    assert pts, "expected pain points from Amazon data"
    for p in pts:
        pct = float(p["meta"].split("%")[0])
        mentions = int(p["metric"].replace(",", ""))
        assert pct >= 20
        assert mentions >= 30
        assert p["metric"] and p["label"] == "Complaints"


def test_home_pain_points_ranked_by_volume():
    pts = home._pain_points(n=5)
    counts = [int(p["metric"].replace(",", "")) for p in pts]
    assert counts == sorted(counts, reverse=True)


# ─────────────────────────── home payload cohesion ───────────────────────────
def test_home_payload_has_all_signals():
    p = home.payload()
    assert p["blue_ocean"] is not None
    assert p["pain_points"]
    assert p["trade"] and p["trade"]["markets"]
    # every data source has a freshness entry (incl. trade)
    assert {"amazon", "trends", "trade", "social"} <= set(p["freshness"])
    assert p["brief"]


# ─────────────────────────── fusion opportunity engine ───────────────────────────
def test_fusion_uses_complete_trade_year():
    f = fusion.Fusion()
    assert f._tyear == getattr(f.trade, "latest_complete", f.trade.latest)


def test_category_opportunities_are_corroborated():
    f = fusion.Fusion()
    opps = f.category_opportunities(top_n=6)
    assert opps
    for c in opps:
        assert c["n_signals"] >= 2            # social + sentiment at minimum
        assert c["sell_to"]                   # always has a market to sell into
    # sorted by corroboration then conversation volume
    keys = [(c["n_signals"], c["n_posts"]) for c in opps]
    assert keys == sorted(keys, reverse=True)


def test_emerging_formats_ranked_by_breadth():
    f = fusion.Fusion()
    ef = f.emerging_formats()
    for item in ef:
        assert {"format", "category", "n_markets", "avg_momentum"} <= set(item)
    keys = [(e["n_markets"], e["avg_momentum"]) for e in ef]
    assert keys == sorted(keys, reverse=True)


# ─────────────────────────── refresh manager ───────────────────────────
def test_refresh_sources_and_status():
    assert {"social", "amazon", "trends", "trade"} <= set(refresh_manager.SOURCES)
    st = refresh_manager.status()
    assert "sources" in st and st["sources"]
    for s in st["sources"]:
        assert s["source"] in refresh_manager.SOURCES


def test_refresh_eta_positive():
    for src in refresh_manager.SOURCES:
        assert refresh_manager.estimate_seconds(src) > 0
