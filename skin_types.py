"""
Consumer skin-type distribution — opportunity segmentation context for the agent.

Source: Statista Consumer Insights infographic "Men More Likely To Define Their
Skin Type as Normal" (US, 18-64, 60,800 respondents, Jul 2024-Jun 2025, multiple
answers possible). Free to use with attribution (Statista Infographics, CC BY-ND).
Data captured directly from the published chart.

Used to SIZE addressable demand segments by skin type and connect them to product
categories — e.g. how big is the oily-skin segment, and does it skew male/female?
"""

import json
from pathlib import Path

DATA = Path(__file__).parent / "data" / "skin_types.json"
_cache = None


def get_skin_types():
    global _cache
    if _cache is None:
        _cache = json.loads(DATA.read_text())
    return _cache


def _segment(r):
    men, women = r["men"], r["women"]
    blended = round((men + women) / 2, 1)             # ~50/50 adult gender split
    skew = women - men                                # +ve = over-indexes female
    if abs(skew) <= 2:
        skew_label = "even"
    elif skew > 0:
        skew_label = f"skews female (+{skew}pp)"
    else:
        skew_label = f"skews male ({skew}pp)"
    return {
        "skin_type": r["type"], "men_pct": men, "women_pct": women,
        "approx_all_pct": blended, "gender_skew": skew_label,
        "related_category": r.get("related_category"),
    }


def agent_summary():
    """Segmentation-oriented view for the Claude agent."""
    d = get_skin_types()
    segments = sorted((_segment(r) for r in d["skin_types"]),
                      key=lambda s: s["approx_all_pct"], reverse=True)
    return {
        "what": "US consumer skin-type self-identification — addressable demand "
                "segments for opportunity sizing & targeting.",
        "geography": d["geography"], "age_range": d["age_range"],
        "sample_size": d["sample_size"], "survey_period": d["survey_period"],
        "metric": d["metric"], "caveat": d["note"],
        "source": d["source"], "source_url": d["source_url"], "license": d["license"],
        "segments": segments,
        "how_to_use": "approx_all_pct ~ share of US adults claiming that skin type "
                      "(multi-select, so they overlap). Use gender_skew for audience "
                      "targeting and related_category to tie a segment to Product "
                      "Scout's category data (reviews, trends, social).",
    }
