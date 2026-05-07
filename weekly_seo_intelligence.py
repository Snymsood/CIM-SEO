#!/usr/bin/env python3
"""
weekly_seo_intelligence.py
CIM SEO — Weekly Intelligence Layer

Runs AFTER all individual report scripts have completed.
Synthesises findings from all report CSV outputs into:
  - weekly_seo_action_queue.csv / .json
  - weekly_seo_anomalies.csv
  - weekly_content_decay_candidates.csv
  - weekly_seo_intelligence_report.html
  - weekly_seo_intelligence_ai_recommendations.md

Usage:
  python weekly_seo_intelligence.py
  python weekly_seo_intelligence.py --dry-run   (skips Monday.com, uses local data only)

Environment variables:
  ENABLE_WEEKLY_INTELLIGENCE=true   (default true)
  ENABLE_AI_ACTION_PLAN=true        (default true if GROQ_API_KEY set)
  GROQ_API_KEY                      (optional, for AI action plan)
  MONDAY_API_TOKEN                  (optional, for Monday.com posting)
  MONDAY_INTELLIGENCE_ITEM_ID       (optional, Monday item for intelligence report)
  GOOGLE_SHEET_ID                   (optional, for historical trend data)
"""

from __future__ import annotations

import argparse
import base64
import html as _html
import json
import math
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from seo_intelligence_utils import (
    safe_pct_change, safe_float, classify_trend, compute_trend_fields,
    load_thresholds, detect_anomaly, build_anomaly_table,
    score_content_decay, make_action, sort_action_queue, deduplicate_actions,
    compute_conversion_rate, estimate_business_value,
    make_warning, check_csv_available, build_action_plan_prompt,
    effort_label_to_score, severity_to_urgency, confidence_label_to_score,
    clamp,
)
from seo_utils import get_weekly_date_windows, short_url
from pdf_report_formatter import format_pct_change

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

ENABLE_INTELLIGENCE  = os.getenv("ENABLE_WEEKLY_INTELLIGENCE", "true").lower() == "true"
ENABLE_AI_PLAN       = os.getenv("ENABLE_AI_ACTION_PLAN", "true").lower() == "true"
GROQ_API_KEY         = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN     = os.getenv("MONDAY_API_TOKEN")
MONDAY_INTEL_ITEM_ID = os.getenv("MONDAY_INTELLIGENCE_ITEM_ID")

# Brand palette (matches REPORT_DESIGN_PRINCIPLES.md)
C_NAVY   = "#212878"
C_TEAL   = "#2A9D8F"
C_CORAL  = "#E76F51"
C_SLATE  = "#6C757D"
C_GREEN  = "#059669"
C_RED    = "#DC2626"
C_AMBER  = "#D97706"
C_BORDER = "#E2E8F0"

FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400'
    '&family=Source+Serif+4:ital,wght@0,300;0,400;0,600;1,400'
    '&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">'
)

# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

def _load(path: str, label: str = "") -> pd.DataFrame:
    """Safely load a CSV. Returns empty DataFrame on any failure."""
    try:
        df = pd.read_csv(path)
        return df
    except Exception:
        return pd.DataFrame()


def load_all_report_data() -> dict:
    """Load every CSV produced by the existing report scripts."""
    return {
        # GA4
        "ga4_summary":        _load("ga4_summary_comparison.csv"),
        "ga4_pages":          _load("ga4_pages_comparison.csv"),
        "ga4_channels":       _load("ga4_top_channels.csv"),
        "ga4_devices":        _load("ga4_device_split.csv"),
        # Conversions
        "conv_summary":       _load("ga4_conversion_summary.csv"),
        "conv_pages":         _load("ga4_conversion_pages.csv"),
        "conv_channels":      _load("ga4_conversion_channels.csv"),
        "conv_current":       _load("ga4_conversions_current.csv"),
        # GSC
        "gsc_comparison":     _load("weekly_comparison.csv"),
        "gsc_queries":        _load("top_queries.csv"),
        "gsc_pages":          _load("gsc_landing_pages_comparison.csv"),
        # Keywords
        "kw_comparison":      _load("tracked_keywords_comparison.csv"),
        # PageSpeed
        "speed":              _load("site_speed_comparison.csv"),
        "speed_snapshot":     _load("site_speed_latest_snapshot.csv"),
        # Broken links
        "broken_links":       _load("broken_link_results.csv"),
        # Internal linking
        "internal_pages":     _load("internal_linking_page_summary.csv"),
        "internal_flagged":   _load("internal_linking_flagged_pages.csv"),
        "internal_priority":  _load("internal_linking_priority_targets.csv"),
        # Content audit
        "content_audit":      _load("content_audit_candidates.csv"),
        "content_selection":  _load("content_audit_selection.csv"),
        # Content categories
        "content_cat":        _load("content_category_performance.csv"),
        # AI snippet
        "ai_snippet":         _load("reports/ai_snippet_verification.csv"),
        # Config
        "conv_config":        _load("tracked_conversions.csv"),
        "tracked_pages":      _load("tracked_pages.csv"),
    }


def load_historical_data() -> dict:
    """
    Attempt to read historical data from Google Sheets.
    Returns empty DataFrames if unavailable — intelligence layer degrades gracefully.
    """
    try:
        from google_sheets_db import read_sheet_as_dataframe
        return {
            "hist_gsc":      read_sheet_as_dataframe("GSC_Weekly_Summary"),
            "hist_ga4":      read_sheet_as_dataframe("GA4_Summary"),
            "hist_kw":       read_sheet_as_dataframe("GSC_Keyword_Rankings"),
            "hist_speed":    read_sheet_as_dataframe("Site_Speed_Summary"),
            "hist_conv":     read_sheet_as_dataframe("GA4_Conversions"),
        }
    except Exception as e:
        print(f"  ⚠ Could not load historical data from Google Sheets: {e}")
        return {k: pd.DataFrame() for k in
                ["hist_gsc", "hist_ga4", "hist_kw", "hist_speed", "hist_conv"]}


# ══════════════════════════════════════════════════════════════════════════════
# KPI EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def extract_kpis(data: dict) -> dict:
    """Extract headline KPIs from loaded DataFrames."""
    kpis = {}

    # GA4
    ga4 = data["ga4_summary"]
    if not ga4.empty and "metric" in ga4.columns:
        for _, row in ga4.iterrows():
            m = str(row.get("metric", ""))
            kpis[f"ga4_{m}_curr"] = safe_float(row.get("current", 0))
            kpis[f"ga4_{m}_prev"] = safe_float(row.get("previous", 0))

    # GSC
    gsc = data["gsc_comparison"]
    if not gsc.empty:
        for col in ["clicks_current", "clicks_previous", "impressions_current",
                    "impressions_previous", "position_current", "position_previous"]:
            if col in gsc.columns:
                gsc[col] = pd.to_numeric(gsc[col], errors="coerce").fillna(0)
        kpis["gsc_clicks_curr"]      = gsc.get("clicks_current",      pd.Series([0])).sum()
        kpis["gsc_clicks_prev"]      = gsc.get("clicks_previous",     pd.Series([0])).sum()
        kpis["gsc_impressions_curr"] = gsc.get("impressions_current", pd.Series([0])).sum()
        kpis["gsc_impressions_prev"] = gsc.get("impressions_previous",pd.Series([0])).sum()
        pos_curr = gsc.loc[gsc.get("impressions_current", pd.Series([0])) > 0, "position_current"].mean()                    if "position_current" in gsc.columns else 0
        pos_prev = gsc.loc[gsc.get("impressions_previous", pd.Series([0])) > 0, "position_previous"].mean()                    if "position_previous" in gsc.columns else 0
        kpis["gsc_avg_position_curr"] = round(float(pos_curr or 0), 1)
        kpis["gsc_avg_position_prev"] = round(float(pos_prev or 0), 1)

    # Conversions
    conv = data["conv_summary"]
    if not conv.empty and "current_count" in conv.columns:
        kpis["conv_total_curr"] = safe_float(conv["current_count"].sum())
        kpis["conv_total_prev"] = safe_float(conv["previous_count"].sum())                                   if "previous_count" in conv.columns else 0

    # PageSpeed
    speed = data["speed_snapshot"]
    if not speed.empty and "strategy" in speed.columns and "performance_score" in speed.columns:
        mob = speed[speed["strategy"] == "mobile"]
        if not mob.empty:
            kpis["mobile_score_curr"] = round(
                pd.to_numeric(mob["performance_score"], errors="coerce").mean(), 1)

    # Broken links
    bl = data["broken_links"]
    if not bl.empty and "issue_type" in bl.columns:
        kpis["broken_links_curr"] = int((bl["issue_type"] == "broken").sum())

    return kpis


# ══════════════════════════════════════════════════════════════════════════════
# ANOMALY DETECTION
# ══════════════════════════════════════════════════════════════════════════════

ANOMALY_CATEGORY_MAP = {
    "clicks":             "organic_visibility",
    "impressions":        "organic_visibility",
    "ctr":                "organic_visibility",
    "avg_position":       "organic_visibility",
    "sessions":           "traffic",
    "conversions":        "business",
    "conversion_rate":    "business",
    "mobile_score":       "technical",
    "cwv_pass_rate":      "technical",
    "broken_links":       "technical",
    "keyword_visibility": "keyword",
}


def run_anomaly_detection(kpis: dict, data: dict, thresholds: dict) -> list[dict]:
    """Run anomaly detection across all key metrics. Returns list of anomaly dicts."""
    anomalies = []

    def _check(metric, curr_key, prev_key, entity="site-wide"):
        curr = safe_float(kpis.get(curr_key, 0))
        prev = safe_float(kpis.get(prev_key, 0))
        if curr == 0 and prev == 0:
            return
        result = detect_anomaly(metric, curr, prev, thresholds=thresholds)
        if result:
            result["entity"] = entity
            result["category"] = ANOMALY_CATEGORY_MAP.get(metric, "general")
            anomalies.append(result)

    _check("clicks",      "gsc_clicks_curr",      "gsc_clicks_prev")
    _check("impressions", "gsc_impressions_curr",  "gsc_impressions_prev")
    _check("sessions",    "ga4_sessions_curr",     "ga4_sessions_prev")
    _check("conversions", "conv_total_curr",        "conv_total_prev")
    _check("mobile_score","mobile_score_curr",      "mobile_score_curr")  # no prev yet
    _check("broken_links","broken_links_curr",      "broken_links_curr")  # no prev yet

    # Position: worsen = current > previous
    pos_curr = safe_float(kpis.get("gsc_avg_position_curr", 0))
    pos_prev = safe_float(kpis.get("gsc_avg_position_prev", 0))
    if pos_curr > 0 and pos_prev > 0:
        result = detect_anomaly("avg_position", pos_curr, pos_prev, thresholds=thresholds)
        if result:
            result["entity"] = "site-wide"
            result["category"] = "organic_visibility"
            anomalies.append(result)

    # Keyword visibility
    kw = data["kw_comparison"]
    if not kw.empty and "impressions_current" in kw.columns:
        kw["impressions_current"]  = pd.to_numeric(kw["impressions_current"],  errors="coerce").fillna(0)
        kw["impressions_previous"] = pd.to_numeric(kw.get("impressions_previous", pd.Series([0])), errors="coerce").fillna(0)
        vis_curr = int((kw["impressions_current"] > 0).sum())
        vis_prev = int((kw["impressions_previous"] > 0).sum())
        result = detect_anomaly("keyword_visibility", vis_curr, vis_prev, thresholds=thresholds)
        if result:
            result["entity"] = "tracked keywords"
            result["category"] = "keyword"
            anomalies.append(result)

    return anomalies


# ══════════════════════════════════════════════════════════════════════════════
# CONTENT DECAY DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def run_content_decay_detection(data: dict) -> pd.DataFrame:
    """
    Identify decaying pages using GSC page data and GA4 landing page data.
    Returns a DataFrame of decay candidates sorted by decay_score descending.
    """
    gsc_pages = data.get("gsc_pages", pd.DataFrame())
    ga4_pages = data.get("ga4_pages", pd.DataFrame())
    conv_pages = data.get("conv_pages", pd.DataFrame())
    tracked_pages_df = data.get("tracked_pages", pd.DataFrame())

    # Build priority page set
    priority_pages = set()
    if not tracked_pages_df.empty and "page" in tracked_pages_df.columns:
        high_priority = tracked_pages_df[
            tracked_pages_df.get("priority", pd.Series(["medium"] * len(tracked_pages_df))) == "high"
        ]
        priority_pages = set(high_priority["page"].astype(str).tolist())

    # Use GSC page data as primary source
    if gsc_pages.empty:
        return pd.DataFrame()

    # Normalise column names
    page_col = "page" if "page" in gsc_pages.columns else gsc_pages.columns[0]
    c_clicks = "clicks_current"  if "clicks_current"  in gsc_pages.columns else "clicks"
    p_clicks = "clicks_previous" if "clicks_previous" in gsc_pages.columns else None
    c_impr   = "impressions_current"  if "impressions_current"  in gsc_pages.columns else "impressions"
    c_pos    = "position_current"     if "position_current"     in gsc_pages.columns else "position"
    c_ctr    = "ctr_current"          if "ctr_current"          in gsc_pages.columns else "ctr"

    for col in [c_clicks, c_impr, c_pos, c_ctr]:
        if col in gsc_pages.columns:
            gsc_pages[col] = pd.to_numeric(gsc_pages[col], errors="coerce").fillna(0)
    if p_clicks and p_clicks in gsc_pages.columns:
        gsc_pages[p_clicks] = pd.to_numeric(gsc_pages[p_clicks], errors="coerce").fillna(0)

    # Build GA4 session lookup
    ga4_lookup: dict = {}
    if not ga4_pages.empty:
        lp_col = "landingPage" if "landingPage" in ga4_pages.columns else ga4_pages.columns[0]
        s_curr = "sessions_current" if "sessions_current" in ga4_pages.columns else "sessions"
        s_prev = "sessions_previous" if "sessions_previous" in ga4_pages.columns else None
        for _, row in ga4_pages.iterrows():
            page = str(row.get(lp_col, ""))
            ga4_lookup[page] = {
                "sessions_curr": safe_float(row.get(s_curr, 0)),
                "sessions_prev": safe_float(row.get(s_prev, 0)) if s_prev else 0,
            }

    # Build conversion lookup
    conv_lookup: dict = {}
    if not conv_pages.empty and "landingPage" in conv_pages.columns:
        for _, row in conv_pages.iterrows():
            conv_lookup[str(row["landingPage"])] = safe_float(row.get("total_conversions", 0))

    decay_candidates = []
    for _, row in gsc_pages.iterrows():
        page = str(row.get(page_col, ""))
        curr_clicks = safe_float(row.get(c_clicks, 0))
        prev_clicks = safe_float(row.get(p_clicks, 0)) if p_clicks else 0
        curr_impr   = safe_float(row.get(c_impr, 0))
        avg_pos     = safe_float(row.get(c_pos, 0))
        ctr         = safe_float(row.get(c_ctr, 0))

        ga4_info = ga4_lookup.get(page, {})
        curr_sessions = ga4_info.get("sessions_curr", 0)
        prev_sessions = ga4_info.get("sessions_prev", 0)
        curr_conv     = conv_lookup.get(page, 0)

        result = score_content_decay(
            page=page,
            current_clicks=curr_clicks,
            previous_clicks=prev_clicks,
            current_sessions=curr_sessions,
            previous_sessions=prev_sessions,
            current_impressions=curr_impr,
            avg_position=avg_pos,
            ctr=ctr,
            current_conversions=curr_conv,
            is_priority_page=(page in priority_pages),
        )
        if result:
            decay_candidates.append(result)

    if not decay_candidates:
        return pd.DataFrame()

    df = pd.DataFrame(decay_candidates).sort_values("decay_score", ascending=False)
    return df.head(30)  # top 30 decay candidates


# ══════════════════════════════════════════════════════════════════════════════
# ACTION QUEUE BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_action_queue(data: dict, kpis: dict, anomalies: list[dict],
                       decay_df: pd.DataFrame) -> list[dict]:
    """
    Build the prioritised SEO action queue from all available signals.
    Returns a sorted list of action dicts.
    """
    actions: list[dict] = []

    # ── 1. CTR Opportunity Gap (GSC) ─────────────────────────────────────────
    gsc_queries = data.get("gsc_queries", pd.DataFrame())
    if not gsc_queries.empty:
        click_col = "clicks_current" if "clicks_current" in gsc_queries.columns else "clicks"
        impr_col  = "impressions_current" if "impressions_current" in gsc_queries.columns else "impressions"
        pos_col   = "position_current" if "position_current" in gsc_queries.columns else "position"
        ctr_col   = "ctr_current" if "ctr_current" in gsc_queries.columns else "ctr"
        for col in [click_col, impr_col, pos_col, ctr_col]:
            if col in gsc_queries.columns:
                gsc_queries[col] = pd.to_numeric(gsc_queries[col], errors="coerce").fillna(0)
        gap = gsc_queries[
            (gsc_queries.get(pos_col, pd.Series([99]*len(gsc_queries))) >= 4) &
            (gsc_queries.get(pos_col, pd.Series([99]*len(gsc_queries))) <= 10) &
            (gsc_queries.get(impr_col, pd.Series([0]*len(gsc_queries))) >= 100) &
            (gsc_queries.get(ctr_col, pd.Series([1]*len(gsc_queries))) < 0.05)
        ].copy()
        if not gap.empty:
            gap["click_potential"] = (gap[impr_col] * 0.05 - gap[click_col]).clip(lower=0)
            top_gap = gap.nlargest(3, "click_potential")
            for _, row in top_gap.iterrows():
                q = str(row.get("query", row.iloc[0]))[:60]
                pos = safe_float(row.get(pos_col, 0))
                ctr = safe_float(row.get(ctr_col, 0))
                impr = safe_float(row.get(impr_col, 0))
                pot = safe_float(row.get("click_potential", 0))
                actions.append(make_action(
                    action=f"Rewrite title/meta for query: '{short_url(q, 50)}'",
                    category="Organic Visibility",
                    source="GSC CTR Gap Analysis",
                    evidence=f"Position {pos:.1f}, CTR {ctr:.1%}, {impr:,.0f} impressions, ~{pot:.0f} additional clicks available",
                    why_it_matters="Page-1 query with low CTR — title/meta optimisation can double clicks without ranking change",
                    estimated_impact="high",
                    effort="low",
                    confidence="high",
                    urgency="medium",
                    business_value=70,
                ))

    # ── 2. Keyword Ranking Losses ─────────────────────────────────────────────
    kw = data.get("kw_comparison", pd.DataFrame())
    if not kw.empty and "position_change" in kw.columns:
        kw["position_change"] = pd.to_numeric(kw["position_change"], errors="coerce").fillna(0)
        kw["priority"] = kw.get("priority", pd.Series(["medium"]*len(kw)))
        losers = kw[
            (kw["position_change"] > 3) &
            (kw.get("priority", pd.Series(["medium"]*len(kw))).str.lower() == "high")
        ].nlargest(3, "position_change")
        for _, row in losers.iterrows():
            kw_name = str(row.get("keyword", ""))[:50]
            chg = safe_float(row.get("position_change", 0))
            pos_curr = safe_float(row.get("position_current", 0))
            actions.append(make_action(
                action=f"Investigate ranking drop for keyword: '{kw_name}'",
                category="Keyword Performance",
                source="Keyword Ranking Report",
                evidence=f"Position worsened by {chg:.1f} positions to {pos_curr:.1f} this week",
                why_it_matters="High-priority keyword lost significant ranking — investigate cause before further decline",
                estimated_impact="high",
                effort="medium",
                confidence="high",
                urgency="high",
                business_value=80,
            ))

    # ── 3. Content Decay ──────────────────────────────────────────────────────
    if not decay_df.empty:
        top_decay = decay_df.head(3)
        for _, row in top_decay.iterrows():
            page = short_url(str(row.get("page", "")), 60)
            score = safe_float(row.get("decay_score", 0))
            click_pct = safe_float(row.get("pct_change_clicks", 0))
            rec = str(row.get("recommendation", "Refresh content"))
            actions.append(make_action(
                action=f"{rec}: {page}",
                category="Content Performance",
                source="Content Decay Detection",
                evidence=f"Clicks declined {click_pct:.1%} WoW, decay score {score:.0f}/100",
                why_it_matters="Page is losing organic traffic — early intervention prevents further ranking loss",
                estimated_impact="medium",
                effort="medium",
                confidence="medium",
                urgency="medium",
                business_value=60,
            ))

    # ── 4. Broken Links ───────────────────────────────────────────────────────
    bl = data.get("broken_links", pd.DataFrame())
    if not bl.empty and "issue_type" in bl.columns:
        broken_count = int((bl["issue_type"] == "broken").sum())
        if broken_count > 0:
            # Find broken links on priority pages
            tracked_pages = data.get("tracked_pages", pd.DataFrame())
            priority_urls = set()
            if not tracked_pages.empty and "page" in tracked_pages.columns:
                priority_urls = set(
                    tracked_pages[tracked_pages.get("priority", pd.Series(["medium"]*len(tracked_pages))) == "high"]["page"].tolist()
                )
            src_col = "source_url" if "source_url" in bl.columns else bl.columns[0]
            priority_broken = bl[
                (bl["issue_type"] == "broken") &
                (bl[src_col].isin(priority_urls))
            ] if priority_urls else pd.DataFrame()
            urgency = "high" if not priority_broken.empty else "medium"
            actions.append(make_action(
                action=f"Fix {broken_count} broken links (404/410) across CIM domains",
                category="Technical Health",
                source="Broken Link Report",
                evidence=f"{broken_count} broken links found" + (
                    f", including {len(priority_broken)} on high-priority pages" if not priority_broken.empty else ""
                ),
                why_it_matters="Broken links damage user experience, waste crawl budget, and dilute link equity",
                estimated_impact="medium",
                effort="low",
                confidence="high",
                urgency=urgency,
                business_value=50,
            ))

    # ── 5. PageSpeed / CWV ────────────────────────────────────────────────────
    speed = data.get("speed_snapshot", pd.DataFrame())
    if not speed.empty and "strategy" in speed.columns:
        mob = speed[speed["strategy"] == "mobile"].copy()
        if not mob.empty:
            mob["performance_score"] = pd.to_numeric(mob["performance_score"], errors="coerce")
            poor_pages = mob[mob["performance_score"] < 50].copy()
            if not poor_pages.empty:
                page_col = "page" if "page" in poor_pages.columns else poor_pages.columns[0]
                worst = poor_pages.nsmallest(1, "performance_score")
                page = short_url(str(worst.iloc[0].get(page_col, "")), 55)
                score = safe_float(worst.iloc[0].get("performance_score", 0))
                actions.append(make_action(
                    action=f"Improve mobile PageSpeed for: {page}",
                    category="Technical Health",
                    source="Site Speed Report",
                    evidence=f"Mobile performance score: {score:.0f}/100 (poor threshold: 50)",
                    why_it_matters="Poor mobile speed directly impacts Core Web Vitals, rankings, and user experience",
                    estimated_impact="high",
                    effort="high",
                    confidence="high",
                    urgency="high",
                    business_value=70,
                ))
            # CWV failures
            if "cwv_pass" in mob.columns:
                mob["cwv_pass"] = mob["cwv_pass"].map(
                    {"True": True, "False": False, True: True, False: False,
                     1: True, 0: False, 1.0: True, 0.0: False}
                )
                cwv_fail = mob[mob["cwv_pass"] == False]
                if not cwv_fail.empty:
                    actions.append(make_action(
                        action=f"Resolve Core Web Vitals failures on {len(cwv_fail)} page(s)",
                        category="Technical Health",
                        source="Site Speed Report",
                        evidence=f"{len(cwv_fail)} pages fail CWV field data (LCP/INP/CLS)",
                        why_it_matters="CWV failures are a confirmed Google ranking signal",
                        estimated_impact="high",
                        effort="high",
                        confidence="high",
                        urgency="medium",
                        business_value=65,
                    ))

    # ── 6. Internal Linking ───────────────────────────────────────────────────
    int_priority = data.get("internal_priority", pd.DataFrame())
    if not int_priority.empty and "flag_low_inlinks" in int_priority.columns:
        weak = int_priority[int_priority["flag_low_inlinks"] == True]
        if not weak.empty:
            target_col = "priority_target" if "priority_target" in weak.columns else weak.columns[0]
            page = short_url(str(weak.iloc[0].get(target_col, "")), 55)
            actions.append(make_action(
                action=f"Add internal links to priority page: {page}",
                category="Technical Health",
                source="Internal Linking Audit",
                evidence=f"{len(weak)} priority page(s) have insufficient internal link support",
                why_it_matters="Priority pages need internal links to receive crawl budget and link equity",
                estimated_impact="medium",
                effort="low",
                confidence="high",
                urgency="medium",
                business_value=55,
            ))

    # ── 7. Conversion Drop ────────────────────────────────────────────────────
    conv = data.get("conv_summary", pd.DataFrame())
    if not conv.empty and "current_count" in conv.columns and "previous_count" in conv.columns:
        conv["current_count"]  = pd.to_numeric(conv["current_count"],  errors="coerce").fillna(0)
        conv["previous_count"] = pd.to_numeric(conv["previous_count"], errors="coerce").fillna(0)
        total_curr = conv["current_count"].sum()
        total_prev = conv["previous_count"].sum()
        pct = safe_pct_change(total_curr, total_prev)
        if pct is not None and pct < -0.20 and total_prev >= 5:
            actions.append(make_action(
                action="Investigate organic conversion drop",
                category="Business Impact",
                source="GA4 Conversion Report",
                evidence=f"Total conversions: {total_curr:.0f} vs {total_prev:.0f} ({pct:+.1%} WoW)",
                why_it_matters="Conversion decline directly impacts CIM event registrations and membership goals",
                estimated_impact="high",
                effort="medium",
                confidence="medium",
                urgency="high",
                business_value=100,
            ))

    # ── 8. High-Traffic Low-Conversion Pages ──────────────────────────────────
    conv_pages = data.get("conv_pages", pd.DataFrame())
    ga4_pages  = data.get("ga4_pages",  pd.DataFrame())
    if not ga4_pages.empty and not conv_pages.empty:
        lp_col = "landingPage" if "landingPage" in ga4_pages.columns else ga4_pages.columns[0]
        s_col  = "sessions_current" if "sessions_current" in ga4_pages.columns else "sessions"
        ga4_pages[s_col] = pd.to_numeric(ga4_pages.get(s_col, pd.Series([0]*len(ga4_pages))), errors="coerce").fillna(0)
        high_traffic = ga4_pages.nlargest(20, s_col)
        conv_set = set(conv_pages.get("landingPage", pd.Series()).astype(str).tolist())                    if "landingPage" in conv_pages.columns else set()
        htlc = high_traffic[~high_traffic[lp_col].astype(str).isin(conv_set)]
        if not htlc.empty:
            page = short_url(str(htlc.iloc[0].get(lp_col, "")), 55)
            sessions = safe_float(htlc.iloc[0].get(s_col, 0))
            actions.append(make_action(
                action=f"Improve CTA on high-traffic low-conversion page: {page}",
                category="Business Impact",
                source="GA4 + Conversion Report",
                evidence=f"{sessions:,.0f} sessions but no recorded conversions this week",
                why_it_matters="High-traffic pages without conversions represent missed business value",
                estimated_impact="high",
                effort="low",
                confidence="medium",
                urgency="medium",
                business_value=85,
            ))

    # ── 9. AI Snippet Readiness ───────────────────────────────────────────────
    ai_snip = data.get("ai_snippet", pd.DataFrame())
    if not ai_snip.empty and "hallucination_flag" in ai_snip.columns:
        high_risk = ai_snip[ai_snip["hallucination_flag"].astype(str).str.startswith("High")]
        if not high_risk.empty:
            page_col = "target_url" if "target_url" in high_risk.columns else high_risk.columns[0]
            page = short_url(str(high_risk.iloc[0].get(page_col, "")), 55)
            actions.append(make_action(
                action=f"Improve AI snippet readiness for: {page}",
                category="Content Performance",
                source="AI Snippet Verification",
                evidence=f"{len(high_risk)} page(s) flagged as high hallucination risk for AI search",
                why_it_matters="Pages with poor AI readiness may be misrepresented in AI-generated search answers",
                estimated_impact="medium",
                effort="low",
                confidence="medium",
                urgency="low",
                business_value=40,
            ))

    # ── 10. Anomaly-driven actions ────────────────────────────────────────────
    for anomaly in anomalies:
        if anomaly.get("severity") == "high":
            metric = anomaly.get("metric", "unknown")
            evidence = anomaly.get("evidence", "")
            actions.append(make_action(
                action=f"Investigate anomaly: {metric} ({anomaly.get('direction','change')})",
                category=anomaly.get("category", "General").replace("_", " ").title(),
                source="Anomaly Detection",
                evidence=evidence,
                why_it_matters=f"High-severity anomaly in {metric} — requires investigation to rule out technical or algorithmic cause",
                estimated_impact="high",
                effort="low",
                confidence=anomaly.get("confidence", "medium"),
                urgency="high",
                business_value=75,
            ))

    # Deduplicate and sort
    actions = deduplicate_actions(actions)
    actions = sort_action_queue(actions)
    return actions


# ══════════════════════════════════════════════════════════════════════════════
# AI ACTION PLAN
# ══════════════════════════════════════════════════════════════════════════════

def generate_ai_action_plan(action_queue: list[dict], anomalies: list[dict],
                             kpis: dict, date_range: str) -> str:
    """
    Generate AI-written action plan using Groq/Llama.
    Falls back to deterministic summary if AI unavailable.
    """
    if not GROQ_API_KEY or not ENABLE_AI_PLAN:
        return _deterministic_action_plan(action_queue, kpis, date_range)

    kpi_summary = {
        "GSC Clicks (curr vs prev)": f"{kpis.get('gsc_clicks_curr', 0):,.0f} vs {kpis.get('gsc_clicks_prev', 0):,.0f}",
        "GSC Impressions":           f"{kpis.get('gsc_impressions_curr', 0):,.0f} vs {kpis.get('gsc_impressions_prev', 0):,.0f}",
        "Avg Position":              f"{kpis.get('gsc_avg_position_curr', 0):.1f} vs {kpis.get('gsc_avg_position_prev', 0):.1f}",
        "GA4 Sessions":              f"{kpis.get('ga4_sessions_curr', 0):,.0f} vs {kpis.get('ga4_sessions_prev', 0):,.0f}",
        "Conversions":               f"{kpis.get('conv_total_curr', 0):,.0f} vs {kpis.get('conv_total_prev', 0):,.0f}",
        "Mobile PageSpeed":          f"{kpis.get('mobile_score_curr', 0):.0f}/100",
        "Broken Links":              f"{kpis.get('broken_links_curr', 0):,}",
    }

    prompt = build_action_plan_prompt(action_queue, anomalies, kpi_summary, date_range)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a senior SEO analyst. Write precise, evidence-based action plans. Never invent data."},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        raw = response.choices[0].message.content.strip()
        # Clean markdown
        lines = []
        for line in raw.splitlines():
            clean = line.replace("**", "").replace("__", "").strip()
            if clean:
                lines.append(clean)
        return "\n".join(lines)
    except Exception as e:
        print(f"  ⚠ AI action plan failed: {e}")
        return _deterministic_action_plan(action_queue, kpis, date_range)


def _deterministic_action_plan(action_queue: list[dict], kpis: dict, date_range: str) -> str:
    """Fallback deterministic action plan when AI is unavailable."""
    lines = [f"Weekly SEO Action Plan — {date_range}", ""]
    if not action_queue:
        lines.append("No significant issues detected this week. Continue monitoring.")
        return "\n".join(lines)
    lines.append(f"Top {min(5, len(action_queue))} priorities this week:")
    lines.append("")
    for i, action in enumerate(action_queue[:5], 1):
        lines.append(f"{i}. [{action.get('category','?')}] {action.get('action','?')} ")
        lines.append(f"   Evidence: {action.get('evidence','?')} ")
        lines.append(f"   Impact: {action.get('estimated_impact','?')} | Effort: {action.get('effort','?')} | Confidence: {action.get('confidence','?')} ")
        lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# DATA QUALITY WARNINGS
# ══════════════════════════════════════════════════════════════════════════════

def collect_data_warnings(data: dict, hist: dict) -> list[dict]:
    """Collect data quality warnings for the intelligence report."""
    warnings = []

    # Check key CSVs
    csv_checks = [
        ("ga4_summary_comparison.csv",    "GA4 Summary",       "GA4 KPIs unavailable"),
        ("weekly_comparison.csv",          "GSC Weekly",        "GSC organic visibility data unavailable"),
        ("tracked_keywords_comparison.csv","Keyword Rankings",  "Keyword movement data unavailable"),
        ("site_speed_latest_snapshot.csv", "Site Speed",        "PageSpeed/CWV data unavailable"),
        ("broken_link_results.csv",        "Broken Links",      "Broken link data unavailable"),
        ("ga4_conversion_summary.csv",     "GA4 Conversions",   "Conversion data unavailable — add events to tracked_conversions.csv"),
    ]
    for path, source, effect in csv_checks:
        w = check_csv_available(path, source, effect)
        if w:
            warnings.append(w)

    # Conversion config check
    conv_config = data.get("conv_config", pd.DataFrame())
    if conv_config.empty:
        warnings.append(make_warning(
            "GA4 Conversions",
            "tracked_conversions.csv is empty or missing",
            "high",
            "Business impact section is incomplete — no conversion data available",
            "Add real GA4 event names to tracked_conversions.csv",
        ))
    else:
        conv_summary = data.get("conv_summary", pd.DataFrame())
        if not conv_summary.empty and "has_data" in conv_summary.columns:
            no_data = conv_summary[conv_summary["has_data"] == False]
            if len(no_data) == len(conv_summary):
                warnings.append(make_warning(
                    "GA4 Conversions",
                    "All configured conversion events returned zero data",
                    "high",
                    "Conversion events may not match actual GA4 event names",
                    "Verify event names in tracked_conversions.csv match GA4 event names exactly",
                ))

    # Historical data check
    hist_gsc = hist.get("hist_gsc", pd.DataFrame())
    if hist_gsc.empty:
        warnings.append(make_warning(
            "Google Sheets History",
            "No historical GSC data available",
            "medium",
            "Trend analysis and anomaly detection use current vs previous period only",
            "Continue running weekly reports to build historical baseline (8+ weeks needed)",
        ))
    elif len(hist_gsc) < 8:
        warnings.append(make_warning(
            "Google Sheets History",
            f"Only {len(hist_gsc)} weeks of historical data available (8+ recommended)",
            "low",
            "Anomaly detection uses simple WoW comparison instead of z-score",
            "Continue running weekly reports to build historical baseline",
        ))

    return warnings


# ══════════════════════════════════════════════════════════════════════════════
# HTML REPORT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _esc(s: str) -> str:
    return _html.escape(str(s))



# ══════════════════════════════════════════════════════════════════════════════
# HTML REPORT BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

_MONO  = "font-family:'JetBrains Mono',monospace"
_SERIF = "font-family:'Source Serif 4',Georgia,serif"
_DISP  = "font-family:'Playfair Display',Georgia,serif"
_TD    = "padding:8px 10px;border-bottom:1px solid #E5E5E5;"


def _kpi_card(label: str, curr, prev=None, lower_better: bool = False,
              is_pct: bool = False, decimals: int = 0) -> str:
    curr_f   = safe_float(curr)
    curr_str = f"{curr_f:.{decimals}%}" if is_pct else f"{curr_f:,.{decimals}f}"
    if prev is not None:
        prev_f   = safe_float(prev)
        prev_str = f"{prev_f:.{decimals}%}" if is_pct else f"{prev_f:,.{decimals}f}"
        delta_str = format_pct_change(curr_f, prev_f)
    else:
        prev_str, delta_str = "\u2014", "-"

    if delta_str == "-":
        delta_html = (
            f'<span style="{_MONO};font-size:10px;color:#525252;">\u2014</span>'
        )
    else:
        is_pos = delta_str.startswith("+")
        good   = (is_pos and not lower_better) or (not is_pos and lower_better)
        bg, fg = ("#000", "#fff") if good else ("#fff", "#000")
        delta_html = (
            f'<span style="{_MONO};font-size:10px;font-weight:700;'
            f'padding:2px 8px;background:{bg};color:{fg};border:1px solid #000;">'
            f'{_esc(delta_str)}</span>'
        )
    return (
        f'<div style="background:#000;color:#fff;padding:20px 16px;border-right:2px solid #fff;">'
        f'<div style="{_MONO};font-size:9px;text-transform:uppercase;letter-spacing:0.15em;'
        f'color:#999;margin-bottom:10px;">{_esc(label)}</div>'
        f'<div style="{_DISP};font-size:30px;font-weight:700;color:#fff;line-height:1;'
        f'margin-bottom:8px;">{_esc(curr_str)}</div>'
        f'<div style="{_MONO};font-size:9px;color:#999;margin-bottom:6px;">prev {_esc(prev_str)}</div>'
        f'{delta_html}'
        f'</div>'
    )


def _section(title: str, content: str, section_id: str = "") -> str:
    id_attr = f' id="{section_id}"' if section_id else ""
    return (
        f'<div style="padding:32px 0;"{id_attr}>'
        f'<div style="{_DISP};font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.15em;color:#000;margin-bottom:20px;'
        f'display:flex;align-items:center;gap:16px;">'
        f'<span style="display:inline-block;width:8px;height:8px;background:#000;flex-shrink:0;"></span>'
        f'{_esc(title)}</div>'
        f'<div style="background:#fff;border:2px solid #000;padding:24px 28px;">'
        f'{content}</div></div>'
        f'<hr style="border:none;border-top:4px solid #000;margin:0;">'
    )


def _bullets(items: list) -> str:
    if not items:
        return f'<p style="{_MONO};font-size:10px;color:#94A3B8;">No items.</p>'
    li = "".join(
        f'<li style="{_SERIF};font-size:13px;color:#000;line-height:1.7;'
        f'padding:8px 0 8px 20px;border-bottom:1px solid #E5E5E5;'
        f'position:relative;list-style:none;">'
        f'<span style="position:absolute;left:0;color:#525252;{_MONO};">\u2014</span>'
        f'{_esc(b)}</li>'
        for b in items
    )
    return f'<ul style="margin:0;padding:0;">{li}</ul>'


def _th_row(headers: list) -> str:
    return "".join(
        f'<th style="{_TD}background:#000;color:#fff;{_MONO};'
        f'font-size:8px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.1em;text-align:left;">{h}</th>'
        for h in headers
    )


def _action_table(actions: list) -> str:
    if not actions:
        return f'<p style="{_MONO};font-size:10px;color:#94A3B8;">No actions generated.</p>'
    severity_colors = {"high": C_RED, "medium": C_AMBER, "low": C_TEAL}
    headers = ["#", "Action", "Category", "Evidence", "Impact", "Effort", "Confidence"]
    rows = []
    for a in actions[:15]:
        impact = str(a.get("estimated_impact", "medium")).lower()
        color  = severity_colors.get(impact, C_SLATE)
        rows.append(
            f'<tr>'
            f'<td style="{_TD}{_MONO};font-size:10px;color:#94A3B8;">{a.get("priority","")}</td>'
            f'<td style="{_TD}{_SERIF};font-size:12px;max-width:280px;">{_esc(str(a.get("action",""))[:100])}</td>'
            f'<td style="{_TD}{_MONO};font-size:9px;white-space:nowrap;">{_esc(str(a.get("category","")))}</td>'
            f'<td style="{_TD}{_MONO};font-size:9px;max-width:220px;">{_esc(str(a.get("evidence",""))[:120])}</td>'
            f'<td style="{_TD}{_MONO};font-size:9px;">'
            f'<span style="background:{color};color:#fff;padding:2px 6px;font-size:8px;font-weight:700;">'
            f'{_esc(impact.upper())}</span></td>'
            f'<td style="{_TD}{_MONO};font-size:9px;">{_esc(str(a.get("effort","")))}</td>'
            f'<td style="{_TD}{_MONO};font-size:9px;">{_esc(str(a.get("confidence","")))}</td>'
            f'</tr>'
        )
    return (
        f'<table style="width:100%;border-collapse:collapse;table-layout:fixed;">'
        f'<thead><tr>{_th_row(headers)}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _anomaly_table(anomalies: list) -> str:
    if not anomalies:
        return f'<p style="{_MONO};font-size:10px;color:#059669;">No anomalies detected this week.</p>'
    severity_colors = {"high": C_RED, "medium": C_AMBER, "low": C_TEAL}
    headers = ["Metric", "Category", "Current", "Previous", "Change", "Severity", "Confidence"]
    rows = []
    for a in anomalies:
        sev   = str(a.get("severity", "medium")).lower()
        color = severity_colors.get(sev, C_SLATE)
        pct   = a.get("pct_change")
        pct_str = f"{pct:+.1%}" if pct is not None else "n/a"
        rows.append(
            f'<tr>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{_esc(str(a.get("metric","")))}</td>'
            f'<td style="{_TD}{_MONO};font-size:9px;">{_esc(str(a.get("category","")))}</td>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{a.get("current_value",0):,.1f}</td>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{a.get("previous_value",0):,.1f}</td>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{pct_str}</td>'
            f'<td style="{_TD}">'
            f'<span style="background:{color};color:#fff;padding:2px 6px;{_MONO};font-size:8px;font-weight:700;">'
            f'{_esc(sev.upper())}</span></td>'
            f'<td style="{_TD}{_MONO};font-size:9px;">{_esc(str(a.get("confidence","")))}</td>'
            f'</tr>'
        )
    return (
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr>{_th_row(headers)}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _warnings_table(warnings: list) -> str:
    if not warnings:
        return f'<p style="{_MONO};font-size:10px;color:#059669;">All data sources loaded successfully.</p>'
    headers = ["Source", "Issue", "Severity", "Effect", "Suggested Fix"]
    rows = []
    for w in warnings:
        rows.append(
            f'<tr>'
            + "".join(
                f'<td style="{_TD}{_MONO};font-size:9px;">{_esc(str(w.get(k,"")))}</td>'
                for k in ["source", "issue", "severity", "effect", "suggested_fix"]
            )
            + '</tr>'
        )
    return (
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr>{_th_row(headers)}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _decay_table(decay_df) -> str:
    if decay_df.empty:
        return f'<p style="{_MONO};font-size:10px;color:#059669;">No significant content decay detected this week.</p>'
    headers = ["Page", "Clicks (curr)", "Clicks (prev)", "\u0394 Clicks", "Sessions", "Position", "CTR", "Decay Score", "Recommendation"]
    rows = []
    for _, row in decay_df.head(10).iterrows():
        pct = safe_float(row.get("pct_change_clicks", 0))
        pct_str = f"{pct:+.1%}"
        score = safe_float(row.get("decay_score", 0))
        score_color = C_RED if score >= 60 else C_AMBER if score >= 35 else C_SLATE
        rows.append(
            f'<tr>'
            f'<td style="{_TD}{_SERIF};font-size:11px;max-width:200px;">{_esc(short_url(str(row.get("page","")),55))}</td>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{safe_float(row.get("current_clicks",0)):,.0f}</td>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{safe_float(row.get("previous_clicks",0)):,.0f}</td>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{pct_str}</td>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{safe_float(row.get("current_sessions",0)):,.0f}</td>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{safe_float(row.get("avg_position",0)):.1f}</td>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{safe_float(row.get("ctr",0)):.2%}</td>'
            f'<td style="{_TD}">'
            f'<span style="background:{score_color};color:#fff;padding:2px 6px;{_MONO};font-size:9px;font-weight:700;">'
            f'{score:.0f}</span></td>'
            f'<td style="{_TD}{_MONO};font-size:10px;">{_esc(str(row.get("recommendation","")))}</td>'
            f'</tr>'
        )
    return (
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr>{_th_row(headers)}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def generate_html_report(
    kpis: dict,
    action_queue: list,
    anomalies: list,
    decay_df,
    warnings: list,
    ai_plan: str,
    data: dict,
    current_start, current_end, previous_start, previous_end,
) -> str:
    today = date.today().strftime("%B %d, %Y")
    date_range = f"{current_start} to {current_end}"

    # KPI grid
    kpi_cards = "".join([
        _kpi_card("GSC Clicks",      kpis.get("gsc_clicks_curr", 0),      kpis.get("gsc_clicks_prev", 0)),
        _kpi_card("GSC Impressions", kpis.get("gsc_impressions_curr", 0),  kpis.get("gsc_impressions_prev", 0)),
        _kpi_card("Avg Position",    kpis.get("gsc_avg_position_curr", 0), kpis.get("gsc_avg_position_prev", 0), lower_better=True, decimals=1),
        _kpi_card("GA4 Sessions",    kpis.get("ga4_sessions_curr", 0),     kpis.get("ga4_sessions_prev", 0)),
        _kpi_card("Conversions",     kpis.get("conv_total_curr", 0),       kpis.get("conv_total_prev", 0)),
        _kpi_card("Mobile Score",    kpis.get("mobile_score_curr", 0),     None),
        _kpi_card("Broken Links",    kpis.get("broken_links_curr", 0),     None, lower_better=True),
    ])
    kpi_grid = (
        f'<div style="display:grid;grid-template-columns:repeat(7,1fr);border:2px solid #000;margin-bottom:2px;">'
        f'{kpi_cards}</div>'
    )

    # Executive summary bullets
    exec_bullets = []
    clicks_curr = kpis.get("gsc_clicks_curr", 0)
    clicks_prev = kpis.get("gsc_clicks_prev", 0)
    if clicks_curr > 0:
        pct = safe_pct_change(clicks_curr, clicks_prev)
        pct_str = f" ({pct:+.1%})" if pct is not None else ""
        exec_bullets.append(f"GSC clicks: {clicks_curr:,.0f} this week{pct_str} vs {clicks_prev:,.0f} previous week.")
    sessions_curr = kpis.get("ga4_sessions_curr", 0)
    sessions_prev = kpis.get("ga4_sessions_prev", 0)
    if sessions_curr > 0:
        pct = safe_pct_change(sessions_curr, sessions_prev)
        pct_str = f" ({pct:+.1%})" if pct is not None else ""
        exec_bullets.append(f"GA4 sessions: {sessions_curr:,.0f}{pct_str}.")
    conv_curr = kpis.get("conv_total_curr", 0)
    conv_prev = kpis.get("conv_total_prev", 0)
    if conv_curr > 0:
        pct = safe_pct_change(conv_curr, conv_prev)
        pct_str = f" ({pct:+.1%})" if pct is not None else ""
        exec_bullets.append(f"Conversions: {conv_curr:,.0f}{pct_str}.")
    elif conv_curr == 0:
        exec_bullets.append("Conversion data unavailable — verify event names in tracked_conversions.csv.")
    if anomalies:
        high_sev = [a for a in anomalies if a.get("severity") == "high"]
        if high_sev:
            exec_bullets.append(f"{len(high_sev)} high-severity anomaly/anomalies detected — see Anomalies section.")
    if not decay_df.empty:
        exec_bullets.append(f"{len(decay_df)} content decay candidate(s) identified — see Content Performance section.")
    if action_queue:
        exec_bullets.append(f"This week's action queue contains {len(action_queue)} prioritised items — see Action Queue section.")

    # Conversion section
    conv_summary = data.get("conv_summary", pd.DataFrame())
    if not conv_summary.empty and "current_count" in conv_summary.columns:
        total_curr = safe_float(conv_summary["current_count"].sum())
        total_prev = safe_float(conv_summary.get("previous_count", pd.Series([0])).sum())
        pct = safe_pct_change(total_curr, total_prev)
        pct_str = f" ({pct:+.1%})" if pct is not None else ""
        conv_rows = []
        for _, row in conv_summary.iterrows():
            pct_r = row.get("pct_change")
            pct_s = f"{pct_r:+.1%}" if (pct_r is not None and not (isinstance(pct_r, float) and math.isnan(pct_r))) else "\u2014"
            has_data = "\u2713" if row.get("has_data") else "\u2717"
            vals = [
                str(row.get("conversion_event", "")),
                str(row.get("display_name", "")),
                str(row.get("category", "")),
                f'{safe_float(row.get("current_count", 0)):,.0f}',
                f'{safe_float(row.get("previous_count", 0)):,.0f}',
                pct_s,
                has_data,
            ]
            conv_rows.append(
                "<tr>" + "".join(
                    f'<td style="{_TD}{_MONO};font-size:9px;">{_esc(v)}</td>'
                    for v in vals
                ) + "</tr>"
            )
        conv_headers = ["Event", "Display Name", "Category", "Current", "Previous", "Change", "Has Data"]
        conv_content = (
            f'<p style="{_SERIF};font-size:13px;margin-bottom:16px;">'
            f'Total conversions: <strong>{total_curr:,.0f}</strong>{pct_str} vs {total_prev:,.0f} previous week.</p>'
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<thead><tr>{_th_row(conv_headers)}</tr></thead>'
            f'<tbody>{"".join(conv_rows)}</tbody></table>'
        )
    else:
        conv_content = (
            f'<p style="{_MONO};font-size:10px;color:#94A3B8;">'
            f'No conversion data available. Add real GA4 event names to tracked_conversions.csv.</p>'
        )

    ai_plan_html = (
        f'<pre style="{_SERIF};font-size:13px;line-height:1.7;white-space:pre-wrap;color:#000;">'
        f'{_esc(ai_plan)}</pre>'
    )

    body = (
        f'<header style="background:#000;color:#fff;padding:40px 48px;margin:0 -40px 0;">'
        f'<div style="{_MONO};font-size:10px;text-transform:uppercase;letter-spacing:0.2em;color:#999;margin-bottom:12px;">CIM SEO Intelligence</div>'
        f'<h1 style="{_DISP};font-size:clamp(28px,4vw,52px);font-weight:900;line-height:1;letter-spacing:-0.02em;color:#fff;margin-bottom:16px;">Weekly SEO<br>Intelligence Report</h1>'
        f'<div style="{_MONO};font-size:11px;color:#666;letter-spacing:0.05em;">'
        f'<span style="display:inline-block;width:24px;height:2px;background:#fff;vertical-align:middle;margin-right:16px;"></span>'
        f'{date_range} \u2022 Generated {today}</div>'
        f'</header>'
        f'<hr style="border:none;border-top:4px solid #000;margin:0;">'
        f'<div style="padding:32px 0;">{kpi_grid}</div>'
        f'<hr style="border:none;border-top:4px solid #000;margin:0;">'
        + _section("Executive Summary",                _bullets(exec_bullets),       "executive-summary")
        + _section("Business Impact \u2014 Conversions", conv_content,               "business-impact")
        + _section("Anomalies Detected",               _anomaly_table(anomalies),    "anomalies")
        + _section("Content Decay Candidates",         _decay_table(decay_df),       "content-decay")
        + _section("This Week\u2019s SEO Action Queue", _action_table(action_queue), "action-queue")
        + _section("AI Analyst Notes",                 ai_plan_html,                 "ai-notes")
        + _section("Data Quality / Missing Inputs",    _warnings_table(warnings),    "data-quality")
        + f'<hr style="border:none;border-top:4px solid #000;margin:0;">'
        + f'<footer style="padding:32px 0;display:flex;justify-content:space-between;align-items:center;">'
        + f'<span style="{_DISP};font-size:13px;font-weight:700;letter-spacing:0.05em;">CIM SEO Intelligence</span>'
        + f'<span style="{_MONO};font-size:9px;color:#525252;text-transform:uppercase;letter-spacing:0.12em;">Weekly Intelligence Report \u2022 {today}</span>'
        + f'</footer>'
    )

    return (
        f'<!DOCTYPE html><html lang="en"><head>'
        f'<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'<title>CIM SEO Weekly Intelligence Report \u2014 {today}</title>'
        f'{FONT_LINK}'
        f'<style>'
        f'*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}'
        f'html {{ background: #fff; }}'
        f'body {{ font-family: \'Source Serif 4\', Georgia, serif; font-size: 14px; color: #000;'
        f'background: #fff; line-height: 1.625; max-width: 1200px; margin: 0 auto; padding: 0 40px 80px; }}'
        f'@media (max-width: 768px) {{ body {{ padding: 0 20px 60px; }} }}'
        f'a {{ color: {C_NAVY}; }}'
        f'</style></head><body>{body}</body></html>'
    )

def post_to_monday(action_queue: list[dict], kpis: dict, html_path: str,
                   dry_run: bool = False) -> None:
    if dry_run:
        print("  [dry-run] Skipping Monday.com post.")
        return
    if not MONDAY_API_TOKEN or not MONDAY_INTEL_ITEM_ID:
        print("  Monday intelligence post skipped: MONDAY_API_TOKEN or MONDAY_INTELLIGENCE_ITEM_ID not set.")
        return

    import requests as _req
    top3 = action_queue[:3]
    top3_html = "".join(f"<li>{_html.escape(a.get('action',''))}</li>" for a in top3)
    clicks_curr = kpis.get("gsc_clicks_curr", 0)
    clicks_prev = kpis.get("gsc_clicks_prev", 0)
    pct = safe_pct_change(clicks_curr, clicks_prev)
    pct_str = f" ({pct:+.1%})" if pct is not None else ""

    body = (
        f"<h2>Weekly SEO Intelligence Report — {date.today().strftime('%B %d, %Y')}</h2>"
        f"<p><strong>Top priorities this week:</strong></p><ol>{top3_html}</ol>"
        f"<p><strong>Key changes:</strong></p><ul>"
        f"<li>Organic clicks: {clicks_curr:,.0f}{pct_str}</li>"
        f"<li>Conversions: {kpis.get('conv_total_curr',0):,.0f}</li>"
        f"<li>Anomalies detected: {kpis.get('anomaly_count',0)}</li>"
        f"</ul>"
    )

    MONDAY_API_URL = "https://api.monday.com/v2"
    MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"
    try:
        update_q = """mutation ($item_id: ID!, $body: String!) {
          create_update(item_id: $item_id, body: $body) { id }
        }"""
        resp = _req.post(
            MONDAY_API_URL,
            headers={"Authorization": MONDAY_API_TOKEN, "Content-Type": "application/json"},
            json={"query": update_q, "variables": {"item_id": str(MONDAY_INTEL_ITEM_ID), "body": body}},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(data["errors"])
        update_id = data["data"]["create_update"]["id"]
        print(f"  ✓ Posted intelligence summary to Monday.com item {MONDAY_INTEL_ITEM_ID}")

        # Attach HTML file
        file_q = """mutation ($update_id: ID!, $file: File!) {
          add_file_to_update(update_id: $update_id, file: $file) { id }
        }"""
        html_file = Path(html_path)
        if html_file.exists():
            with open(html_file, "rb") as f:
                file_resp = _req.post(
                    MONDAY_FILE_API_URL,
                    headers={"Authorization": MONDAY_API_TOKEN},
                    data={
                        "query": file_q,
                        "variables": '{"update_id": "' + str(update_id) + '", "file": null}',
                        "map": '{"file": ["variables.file"]}',
                    },
                    files={"file": ("weekly-seo-intelligence.html", f, "text/html")},
                    timeout=120,
                )
            file_resp.raise_for_status()
            print("  ✓ Attached weekly-seo-intelligence.html to Monday.com")
    except Exception as e:
        print(f"  ✗ Monday intelligence post failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main(dry_run: bool = False) -> None:
    if not ENABLE_INTELLIGENCE:
        print("Weekly intelligence layer disabled (ENABLE_WEEKLY_INTELLIGENCE=false). Skipping.")
        return

    print("\n" + "=" * 70)
    print("WEEKLY SEO INTELLIGENCE LAYER — STARTING")
    if dry_run:
        print("[DRY RUN MODE — Monday.com posting disabled]")
    print("=" * 70 + "\n")

    current_start, current_end, previous_start, previous_end = get_weekly_date_windows()
    date_range = f"{current_start} to {current_end}"
    print(f"Period: {date_range} vs {previous_start} to {previous_end}\n")

    # Phase 1: Load data
    print("[1/7] Loading report data...")
    data = load_all_report_data()
    hist = load_historical_data()

    # Phase 2: Extract KPIs
    print("[2/7] Extracting KPIs...")
    kpis = extract_kpis(data)

    # Phase 3: Anomaly detection
    print("[3/7] Running anomaly detection...")
    thresholds = load_thresholds()
    anomalies  = run_anomaly_detection(kpis, data, thresholds)
    kpis["anomaly_count"] = len(anomalies)
    print(f"  {len(anomalies)} anomaly/anomalies detected")

    # Phase 4: Content decay
    print("[4/7] Running content decay detection...")
    decay_df = run_content_decay_detection(data)
    print(f"  {len(decay_df)} decay candidate(s) found")

    # Phase 5: Action queue
    print("[5/7] Building action queue...")
    action_queue = build_action_queue(data, kpis, anomalies, decay_df)
    print(f"  {len(action_queue)} action(s) in queue")

    # Phase 6: AI action plan
    print("[6/7] Generating AI action plan...")
    ai_plan = generate_ai_action_plan(action_queue, anomalies, kpis, date_range)

    # Phase 7: Collect warnings
    warnings = collect_data_warnings(data, hist)

    # Save outputs
    print("[7/7] Saving outputs...")

    # Action queue CSV + JSON
    if action_queue:
        aq_df = pd.DataFrame(action_queue)
        aq_df.to_csv("weekly_seo_action_queue.csv", index=False)
        with open("weekly_seo_action_queue.json", "w") as f:
            json.dump(action_queue, f, indent=2, default=str)
        print(f"  ✓ weekly_seo_action_queue.csv ({len(action_queue)} actions)")

    # Anomalies CSV
    if anomalies:
        anom_df = build_anomaly_table(anomalies, ANOMALY_CATEGORY_MAP)
        anom_df.to_csv("weekly_seo_anomalies.csv", index=False)
        print(f"  ✓ weekly_seo_anomalies.csv ({len(anomalies)} anomalies)")

    # Content decay CSV
    if not decay_df.empty:
        decay_df.to_csv("weekly_content_decay_candidates.csv", index=False)
        print(f"  ✓ weekly_content_decay_candidates.csv ({len(decay_df)} candidates)")

    # AI recommendations markdown
    with open("weekly_seo_intelligence_ai_recommendations.md", "w") as f:
        f.write(f"# Weekly SEO AI Action Plan\n\n**Period:** {date_range}\n\n")
        f.write(ai_plan)
    print("  ✓ weekly_seo_intelligence_ai_recommendations.md")

    # HTML report
    html_content = generate_html_report(
        kpis, action_queue, anomalies, decay_df, warnings, ai_plan, data,
        current_start, current_end, previous_start, previous_end,
    )
    html_path = "weekly_seo_intelligence_report.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    size_kb = len(html_content.encode()) // 1024
    print(f"  ✓ {html_path} ({size_kb} KB)")

    # Intelligence summary JSON
    summary = {
        "generated": date.today().isoformat(),
        "period": date_range,
        "kpis": {k: v for k, v in kpis.items() if isinstance(v, (int, float))},
        "anomaly_count": len(anomalies),
        "action_count": len(action_queue),
        "decay_candidates": len(decay_df),
        "warning_count": len(warnings),
        "top_3_actions": [a.get("action", "") for a in action_queue[:3]],
    }
    with open("weekly_seo_intelligence_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print("  ✓ weekly_seo_intelligence_summary.json")

    # Monday.com
    try:
        post_to_monday(action_queue, kpis, html_path, dry_run=dry_run)
    except Exception as e:
        print(f"  ✗ Monday post failed (non-fatal): {e}")

    print("\n" + "=" * 70)
    print("WEEKLY SEO INTELLIGENCE LAYER — COMPLETE")
    print(f"  Actions: {len(action_queue)} | Anomalies: {len(anomalies)} | Decay: {len(decay_df)} | Warnings: {len(warnings)}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CIM SEO Weekly Intelligence Layer")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run without posting to Monday.com")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
