"""
Home / landing dashboard payload.

Two live, data-driven lists:
  * blue_ocean  — trending whitespace: sub-categories whose search interest is
                  rising across multiple markets at once (Google Trends), ranked
                  by breadth x momentum. The literal new-product backlog.
  * pain_points — the consumer complaints with the most weight: review aspects
                  with the highest absolute negative mentions (Amazon), across
                  every category we track.

Both are recomputed on every request, so the landing page refreshes whenever new
data is ingested for any category. Trends-dependent pieces are resilient: if the
trends source is unavailable the page still renders pain points.
"""

from fusion import get_fusion
from amazon import get_amazon
from analytics import get_data
import refresh_manager

# short, headline-friendly category labels
_SHORT = {
    "Sunscreen / SPF": "Sunscreen",
    "Moisturizer & Hydration": "Moisturizer",
    "Cleanser & Oil Control": "Cleanser",
    "Sensitive & Barrier": "Sensitive skin",
    "Brightening & Dark Spots": "Brightening",
}


def _short(cat):
    return _SHORT.get(cat, cat)


def _blue_ocean(n=5):
    """Rising-demand whitespace across markets (Google Trends emerging formats)."""
    try:
        items = get_fusion().emerging_formats()
    except Exception:  # noqa: BLE001
        items = []
    out = []
    for f in items[:n]:
        mk = f.get("markets_rising") or []
        shown = ", ".join(mk[:3]) + ("…" if len(mk) > 3 else "")
        meta = (f"Search interest rising in {f['n_markets']} "
                f"market{'' if f['n_markets'] == 1 else 's'}"
                + (f" ({shown})" if shown else "")
                + f" · {_short(f['category'])}")
        pain_point = f.get("pain_point")
        if isinstance(pain_point, dict) and pain_point.get("name"):
            meta += f". Pairs with an unsolved gap: {pain_point['name']}."
        out.append({
            "title": f["format"],
            "meta": meta,
            "metric": f"+{round(f['avg_momentum'])}%",
            "label": "Momentum",
            "category": f["category"],
        })
    return out


def _pain_points(n=5):
    """Most-weighted consumer complaints (Amazon review aspects, all categories)."""
    amz = get_amazon()
    rows = []
    for cat in amz.available_categories():
        try:
            d = amz.category(cat)
        except Exception:  # noqa: BLE001
            continue
        if not d.get("available"):
            continue
        for a in d.get("category_aspects", []):
            # a genuine pain point needs both real volume AND real negativity —
            # not a high-traffic aspect that's mostly praised.
            if a.get("mentions", 0) < 30 or a.get("neg_rate", 0) < 20:
                continue
            rows.append((cat, a))
    # weight by absolute negative mentions (severity x reach), highest first
    rows.sort(key=lambda r: (r[1]["neg"], r[1]["neg_rate"]), reverse=True)
    out = []
    for cat, a in rows[:n]:
        out.append({
            "title": f"{_short(cat)} — {a['name']}",
            "meta": (f"{a['neg_rate']:.0f}% negative across {a['mentions']:,} review "
                     f"mentions — a formulation or positioning gap to solve."),
            "metric": f"{a['neg']:,}",
            "label": "Complaints",
            "category": cat,
        })
    return out


def _trade_markets(n=5):
    """Fastest-growing cosmetics import markets (UN Comtrade) — the trade layer
    on the landing page: where global demand is expanding fastest."""
    try:
        td = get_data()
        markets = td.growing_import_markets(n=n)
        monthly = td.monthly_summary()
    except Exception:  # noqa: BLE001
        return None
    if not markets:
        return None
    return {
        "markets": [{
            "title": f"{m['country']}",
            "meta": (f"Cosmetics imports grew {m['yoy_pct']:+.1f}% to ${m['value_b']:.2f}B "
                     f"(HS 3304) in {td.latest} — one of the fastest-rising destination markets."),
            "metric": f"{m['yoy_pct']:+.0f}%",
            "label": "Import YoY",
            "country": m["country"],
        } for m in markets],
        "latest_year": td.latest,
        "latest_month": monthly.get("latest_label") if monthly.get("available") else None,
    }


def _brief(blue, pain, trade):
    parts = []
    if pain:
        p = pain[0]
        parts.append(f"A major consumer pain point is surging around "
                     f"<strong>{p['title']}</strong> — {p['metric']} negative review "
                     f"mentions and climbing.")
    if blue:
        b = blue[0]
        parts.append(f"Meanwhile <strong>{b['title']}</strong> is a clear blue-ocean gap, "
                     f"with demand up {b['metric']} across multiple markets.")
    if trade and trade.get("markets"):
        t = trade["markets"][0]
        parts.append(f"On the trade side, <strong>{t['country']}</strong> is the "
                     f"fastest-growing import market ({t['metric']} YoY).")
    return " ".join(parts) if parts else None


def payload():
    blue = _blue_ocean()
    pain = _pain_points()
    trade = _trade_markets()
    return {
        "brief": _brief(blue, pain, trade),
        "blue_ocean": blue,
        "pain_points": pain,
        "trade": trade,
        "freshness": {
            "amazon": refresh_manager.status_for("amazon"),
            "trends": refresh_manager.status_for("trends"),
            "trade": refresh_manager.status_for("trade"),
            "social": refresh_manager.status_for("social"),
        },
        "meta": {
            "note": ("Blue-ocean = sub-categories rising across markets (Google Trends). "
                     "Pain points = most-complained review aspects (Amazon). "
                     "Trade = fastest-growing import markets (UN Comtrade HS 3304). "
                     "Recomputed on every load and on each data ingest."),
            "generated_at": refresh_manager.status().get("generated_at"),
        },
    }
