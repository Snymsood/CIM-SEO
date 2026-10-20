"""Rank exported GSC query/page pairs without implying page-level prior clicks."""

from __future__ import annotations

import re
import pandas as pd

BRAND = re.compile(r"\b(?:cim|canadian institute of mining|cim magazine)\b", re.I)
COLUMNS = ["query", "page", "demand_type", "query_clicks_previous", "query_clicks_current",
           "query_lost_clicks", "page_impressions_current", "query_impressions_current",
           "current_impression_share", "allocated_lost_clicks", "evidence_scope"]


def rank_query_page_losses(comparison: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    required_comparison = {"query", "clicks_previous", "clicks_current"}
    required_mapping = {"query", "page", "impressions"}
    if not required_comparison.issubset(comparison) or not required_mapping.issubset(mapping):
        return pd.DataFrame(columns=COLUMNS)
    q = comparison[["query", "clicks_previous", "clicks_current"]].copy()
    for col in ("clicks_previous", "clicks_current"):
        q[col] = pd.to_numeric(q[col], errors="coerce")
    q = q.dropna(subset=["clicks_previous", "clicks_current"])
    q["query_lost_clicks"] = (q["clicks_previous"] - q["clicks_current"]).clip(lower=0)
    q = q[q["query_lost_clicks"] > 0]
    pages = mapping[["query", "page", "impressions"]].copy()
    pages["impressions"] = pd.to_numeric(pages["impressions"], errors="coerce").fillna(0)
    pages = pages.groupby(["query", "page"], as_index=False)["impressions"].sum()
    pages["query_impressions_current"] = pages.groupby("query")["impressions"].transform("sum")
    joined = pages.merge(q, on="query", how="inner")
    joined = joined[joined["query_impressions_current"] > 0].copy()
    joined["current_impression_share"] = joined["impressions"] / joined["query_impressions_current"]
    joined["allocated_lost_clicks"] = joined["query_lost_clicks"] * joined["current_impression_share"]
    joined["demand_type"] = joined["query"].astype(str).map(lambda value: "branded" if BRAND.search(value) else "non-branded")
    joined["evidence_scope"] = "Exported query loss allocated by current page impressions; estimate, not page-level previous clicks"
    return (joined.rename(columns={"clicks_previous": "query_clicks_previous", "clicks_current": "query_clicks_current",
                                   "impressions": "page_impressions_current"})[COLUMNS]
            .sort_values("allocated_lost_clicks", ascending=False).reset_index(drop=True))
