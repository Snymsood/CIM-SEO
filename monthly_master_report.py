#!/usr/bin/env python3
"""
Monthly Master Report Orchestrator

Main entry point for generating the monthly SEO master dashboard.
Coordinates all phases:
1. Data collection (GA4, GSC)
2. KPI aggregation
3. Chart generation
4. AI analysis
5. HTML dashboard generation
6. Monday.com upload
7. Google Sheets logging

Runs on the 1st of each month to analyze the previous month.
Example: On May 1st, generates April vs March report.
"""

import os
import pandas as pd
from pathlib import Path
from datetime import date

# Import all monthly modules
from monthly_data_collector import collect_all_monthly_data
from monthly_chart_builder import build_all_monthly_charts
from monthly_ai_analyst import build_unified_bullets
from monthly_dashboard_generator import generate_monthly_dashboard
from seo_utils import get_monthly_date_windows
from pdf_report_formatter import format_pct_change

# Monday.com and Google Sheets integration
from google_sheets_db import append_to_sheet
import requests as _requests

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_MONTHLY_ITEM_ID = os.getenv("MONDAY_MONTHLY_ITEM_ID")  # New item for monthly reports

# ══════════════════════════════════════════════════════════════════════════════
# KPI AGGREGATION
# ══════════════════════════════════════════════════════════════════════════════

def aggregate_monthly_kpis(data):
    """
    Aggregate KPIs from collected data for dashboard display.
    
    Args:
        data: Dictionary containing all collected DataFrames
    
    Returns:
        dict: Dictionary of KPI values with current and previous periods
    """
    print("=" * 80)
    print("KPI AGGREGATION - STARTING")
    print("=" * 80)
    
    kpis = {
        "sessions": {"curr": 0, "prev": 0},
        "users": {"curr": 0, "prev": 0},
        "engagement_rate": {"curr": 0, "prev": 0},
        "avg_duration": {"curr": 0, "prev": 0},
        "bounce_rate": {"curr": 0, "prev": 0},
        "events_per_session": {"curr": 0, "prev": 0},
        "clicks": {"curr": 0, "prev": 0},
        "impressions": {"curr": 0, "prev": 0},
        "ctr": {"curr": 0, "prev": 0},
        "avg_position": {"curr": 0, "prev": 0},
        "mobile_score": {"curr": 0, "prev": 0},
        "cwv_pass_rate": {"curr": 0, "prev": 0},
        "broken_links": {"curr": 0, "prev": 0},
        "internal_link_pages": {"curr": 0, "prev": 0},
        "ai_readiness_avg": {"curr": 0, "prev": 0},
        "content_refresh_candidates": {"curr": 0, "prev": 0},
    }
    
    # GA4 metrics
    ga4_summary = data.get("ga4_summary", pd.DataFrame())
    if not ga4_summary.empty and "metric" in ga4_summary.columns:
        metrics_map = {row["metric"]: row for _, row in ga4_summary.iterrows()}
        
        # Sessions
        if "sessions" in metrics_map:
            kpis["sessions"] = {
                "curr": float(metrics_map["sessions"].get("current", 0)),
                "prev": float(metrics_map["sessions"].get("previous", 0))
            }
        
        # Active Users
        if "activeUsers" in metrics_map:
            kpis["users"] = {
                "curr": float(metrics_map["activeUsers"].get("current", 0)),
                "prev": float(metrics_map["activeUsers"].get("previous", 0))
            }
        
        # Engagement Rate
        if "engagementRate" in metrics_map:
            kpis["engagement_rate"] = {
                "curr": float(metrics_map["engagementRate"].get("current", 0)),
                "prev": float(metrics_map["engagementRate"].get("previous", 0))
            }
        
        # Average Session Duration
        if "averageSessionDuration" in metrics_map:
            kpis["avg_duration"] = {
                "curr": float(metrics_map["averageSessionDuration"].get("current", 0)),
                "prev": float(metrics_map["averageSessionDuration"].get("previous", 0))
            }
        
        # Bounce Rate
        if "bounceRate" in metrics_map:
            kpis["bounce_rate"] = {
                "curr": float(metrics_map["bounceRate"].get("current", 0)),
                "prev": float(metrics_map["bounceRate"].get("previous", 0))
            }
        
        # Events per Session
        if "sessions" in metrics_map and "eventCount" in metrics_map:
            curr_sessions = float(metrics_map["sessions"].get("current", 0))
            prev_sessions = float(metrics_map["sessions"].get("previous", 0))
            curr_events = float(metrics_map["eventCount"].get("current", 0))
            prev_events = float(metrics_map["eventCount"].get("previous", 0))
            
            kpis["events_per_session"] = {
                "curr": (curr_events / curr_sessions) if curr_sessions > 0 else 0,
                "prev": (prev_events / prev_sessions) if prev_sessions > 0 else 0
            }
    
    # GSC metrics
    gsc_queries = data.get("gsc_queries", pd.DataFrame())
    if not gsc_queries.empty:
        # Ensure numeric columns
        for col in ["clicks_current", "clicks_previous", "impressions_current", 
                    "impressions_previous", "ctr_current", "ctr_previous",
                    "position_current", "position_previous"]:
            if col in gsc_queries.columns:
                gsc_queries[col] = pd.to_numeric(gsc_queries[col], errors="coerce").fillna(0)
        
        # Clicks
        kpis["clicks"] = {
            "curr": gsc_queries["clicks_current"].sum() if "clicks_current" in gsc_queries.columns else 0,
            "prev": gsc_queries["clicks_previous"].sum() if "clicks_previous" in gsc_queries.columns else 0
        }
        
        # Impressions
        kpis["impressions"] = {
            "curr": gsc_queries["impressions_current"].sum() if "impressions_current" in gsc_queries.columns else 0,
            "prev": gsc_queries["impressions_previous"].sum() if "impressions_previous" in gsc_queries.columns else 0
        }
        
        # CTR (weighted average)
        if "ctr_current" in gsc_queries.columns and "impressions_current" in gsc_queries.columns:
            total_impr_curr = gsc_queries["impressions_current"].sum()
            if total_impr_curr > 0:
                weighted_ctr_curr = (gsc_queries["ctr_current"] * gsc_queries["impressions_current"]).sum() / total_impr_curr
                kpis["ctr"]["curr"] = weighted_ctr_curr
        
        if "ctr_previous" in gsc_queries.columns and "impressions_previous" in gsc_queries.columns:
            total_impr_prev = gsc_queries["impressions_previous"].sum()
            if total_impr_prev > 0:
                weighted_ctr_prev = (gsc_queries["ctr_previous"] * gsc_queries["impressions_previous"]).sum() / total_impr_prev
                kpis["ctr"]["prev"] = weighted_ctr_prev
        
        # Average Position (weighted average)
        if "position_current" in gsc_queries.columns and "impressions_current" in gsc_queries.columns:
            valid_curr = gsc_queries[gsc_queries["position_current"] > 0]
            if not valid_curr.empty:
                total_impr = valid_curr["impressions_current"].sum()
                if total_impr > 0:
                    weighted_pos_curr = (valid_curr["position_current"] * valid_curr["impressions_current"]).sum() / total_impr
                    kpis["avg_position"]["curr"] = round(weighted_pos_curr, 1)
        
        if "position_previous" in gsc_queries.columns and "impressions_previous" in gsc_queries.columns:
            valid_prev = gsc_queries[gsc_queries["position_previous"] > 0]
            if not valid_prev.empty:
                total_impr = valid_prev["impressions_previous"].sum()
                if total_impr > 0:
                    weighted_pos_prev = (valid_prev["position_previous"] * valid_prev["impressions_previous"]).sum() / total_impr
                    kpis["avg_position"]["prev"] = round(weighted_pos_prev, 1)
    
    # PageSpeed / Core Web Vitals KPIs — derived from site_speed_latest_snapshot.csv
    pagespeed_data = data.get("pagespeed", pd.DataFrame())
    if not pagespeed_data.empty:
        mobile = pagespeed_data[pagespeed_data["strategy"] == "mobile"].copy()
        if not mobile.empty:
            scored = mobile[pd.to_numeric(mobile["performance_score"], errors="coerce").notna()]
            if not scored.empty:
                kpis["mobile_score"]["curr"] = round(
                    pd.to_numeric(scored["performance_score"], errors="coerce").mean(), 1
                )
            cwv_known = mobile[mobile["cwv_pass"].notna()]
            if not cwv_known.empty:
                cwv_known = cwv_known.copy()
                cwv_known["cwv_pass"] = cwv_known["cwv_pass"].map(
                    {"True": True, "False": False, True: True, False: False,
                     1: True, 0: False, 1.0: True, 0.0: False}
                )
                passing = cwv_known["cwv_pass"].sum()
                kpis["cwv_pass_rate"]["curr"] = round(passing / len(cwv_known), 3)

    # Broken link KPIs — derived from broken_link_results.csv
    broken_link_data = data.get("broken_links", pd.DataFrame())
    if not broken_link_data.empty and "issue_type" in broken_link_data.columns:
        kpis["broken_links"]["curr"] = int((broken_link_data["issue_type"] == "broken").sum())

    # Internal linking KPIs — derived from internal_linking_page_summary.csv
    internal_link_data = data.get("internal_links", pd.DataFrame())
    if not internal_link_data.empty:
        kpis["internal_link_pages"]["curr"] = int(len(internal_link_data))

    # AI readiness KPIs — derived from ai_snippet_verification.csv
    ai_snippet_data = data.get("ai_snippet", pd.DataFrame())
    if not ai_snippet_data.empty:
        score_cols = [c for c in ["access_score", "summary_score", "cta_score"] if c in ai_snippet_data.columns]
        if score_cols:
            for col in score_cols:
                ai_snippet_data[col] = pd.to_numeric(ai_snippet_data[col], errors="coerce").fillna(0)
            ai_snippet_data["_overall"] = ai_snippet_data[score_cols].mean(axis=1)
            kpis["ai_readiness_avg"]["curr"] = round(ai_snippet_data["_overall"].mean(), 2)

    # Content audit KPIs — derived from content_audit_candidates.csv
    content_audit_data = data.get("content_audit", pd.DataFrame())
    if not content_audit_data.empty and "recommended_action" in content_audit_data.columns:
        kpis["content_refresh_candidates"]["curr"] = int(
            (content_audit_data["recommended_action"].str.lower() == "refresh").sum()
        )
    
    print("\n✓ KPI aggregation complete")
    print(f"  Sessions:      {kpis['sessions']['curr']:,.0f} (prev: {kpis['sessions']['prev']:,.0f})")
    print(f"  Clicks:        {kpis['clicks']['curr']:,.0f} (prev: {kpis['clicks']['prev']:,.0f})")
    print(f"  Impressions:   {kpis['impressions']['curr']:,.0f} (prev: {kpis['impressions']['prev']:,.0f})")
    print(f"  Avg Position:  {kpis['avg_position']['curr']:.1f} (prev: {kpis['avg_position']['prev']:.1f})")
    print(f"  Mobile Score:  {kpis['mobile_score']['curr']:.1f}")
    print(f"  CWV Pass Rate: {kpis['cwv_pass_rate']['curr']:.1%}")
    print(f"  Broken Links:  {kpis['broken_links']['curr']:,}")
    print(f"  AI Readiness:  {kpis['ai_readiness_avg']['curr']:.2f}/5")
    
    print("\n" + "=" * 80)
    print("KPI AGGREGATION - COMPLETE")
    print("=" * 80)
    
    return kpis


# ══════════════════════════════════════════════════════════════════════════════
# MONDAY.COM UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_monday(html_path, bullets, date_range, run_id=None):
    """Post executive summary update and attach the self-contained HTML to Monday.com."""
    if not MONDAY_API_TOKEN or not MONDAY_MONTHLY_ITEM_ID:
        print("⚠ Monday.com upload skipped: MONDAY_API_TOKEN or MONDAY_MONTHLY_ITEM_ID not set")
        return

    print("=" * 80)
    print("MONDAY.COM UPLOAD - STARTING")
    print("=" * 80)

    current_month = date_range["current_start"].strftime("%B %Y")
    bullet_html = "".join(f"<li>{b}</li>" for b in bullets[:5])
    body_text = (
        f"<h2>Monthly SEO Master Report — {current_month}</h2>"
        f"<p><strong>Executive Summary:</strong></p>"
        f"<ul>{bullet_html}</ul>"
        f"<p><em>Dashboard generated on {date.today().strftime('%B %d, %Y')}</em></p>"
    )

    MONDAY_API_URL      = "https://api.monday.com/v2"
    MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"

    try:
        # Step 1 — create text update
        update_query = """
        mutation ($item_id: ID!, $body: String!) {
          create_update(item_id: $item_id, body: $body) { id }
        }
        """
        resp = _requests.post(
            MONDAY_API_URL,
            headers={"Authorization": MONDAY_API_TOKEN, "Content-Type": "application/json"},
            json={"query": update_query, "variables": {
                "item_id": str(MONDAY_MONTHLY_ITEM_ID), "body": body_text
            }},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"Monday update failed: {data['errors']}")
        update_id = data["data"]["create_update"]["id"]
        print(f"✓ Posted monthly summary to Monday.com item {MONDAY_MONTHLY_ITEM_ID}")

        # Step 2 — attach self-contained HTML file
        file_query = """
        mutation ($update_id: ID!, $file: File!) {
          add_file_to_update(update_id: $update_id, file: $file) { id }
        }
        """
        html_file = Path(html_path)
        if not html_file.exists():
            print(f"⚠ HTML file not found at {html_path}, skipping attachment")
            return

        with open(html_file, "rb") as f:
            file_resp = _requests.post(
                MONDAY_FILE_API_URL,
                headers={"Authorization": MONDAY_API_TOKEN},
                data={
                    "query": file_query,
                    "variables": '{"update_id": "' + str(update_id) + '", "file": null}',
                    "map": '{"file": ["variables.file"]}',
                },
                files={"file": ("monthly-seo-dashboard.html", f, "text/html")},
                timeout=120,
            )
        file_resp.raise_for_status()
        file_data = file_resp.json()
        if "errors" in file_data:
            raise RuntimeError(f"Monday file attach failed: {file_data['errors']}")
        print("✓ Attached monthly-seo-dashboard.html to Monday.com update")

    except Exception as e:
        print(f"✗ Monday.com upload failed: {e}")

    print("\n" + "=" * 80)
    print("MONDAY.COM UPLOAD - COMPLETE")
    print("=" * 80)


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS LOGGING
# ══════════════════════════════════════════════════════════════════════════════

def log_to_google_sheets(kpis, date_range):
    """
    Append KPIs to Google Sheets for historical tracking.
    
    Args:
        kpis: Dictionary of KPI values
        date_range: Dict with date information
    """
    print("=" * 80)
    print("GOOGLE SHEETS LOGGING - STARTING")
    print("=" * 80)
    
    current_month = date_range["current_start"].strftime("%Y-%m")
    
    # Build KPI summary DataFrame
    kpi_data = {
        "month": [current_month],
        "sessions": [kpis["sessions"]["curr"]],
        "users": [kpis["users"]["curr"]],
        "engagement_rate": [kpis["engagement_rate"]["curr"]],
        "avg_duration": [kpis["avg_duration"]["curr"]],
        "bounce_rate": [kpis["bounce_rate"]["curr"]],
        "events_per_session": [kpis["events_per_session"]["curr"]],
        "clicks": [kpis["clicks"]["curr"]],
        "impressions": [kpis["impressions"]["curr"]],
        "ctr": [kpis["ctr"]["curr"]],
        "avg_position": [kpis["avg_position"]["curr"]],
        "mobile_score": [kpis["mobile_score"]["curr"]],
        "cwv_pass_rate": [kpis["cwv_pass_rate"]["curr"]],
        "broken_links": [kpis["broken_links"]["curr"]],
        "internal_link_pages": [kpis["internal_link_pages"]["curr"]],
        "ai_readiness_avg": [kpis["ai_readiness_avg"]["curr"]],
        "content_refresh_candidates": [kpis["content_refresh_candidates"]["curr"]],
    }
    
    df = pd.DataFrame(kpi_data)
    
    try:
        append_to_sheet(df, "monthly_kpis")
        print(f"✓ Appended KPIs to Google Sheets (month: {current_month})")
    except Exception as e:
        print(f"✗ Google Sheets logging failed: {e}")
    
    print("\n" + "=" * 80)
    print("GOOGLE SHEETS LOGGING - COMPLETE")
    print("=" * 80)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """Main orchestration function."""
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 20 + "MONTHLY SEO MASTER REPORT" + " " * 33 + "║")
    print("║" + " " * 78 + "║")
    
    # Get date windows
    current_start, current_end, previous_start, previous_end = get_monthly_date_windows()
    current_month = current_start.strftime("%B %Y")
    previous_month = previous_start.strftime("%B %Y")
    
    print("║  Current Period:  " + f"{current_start} to {current_end}".ljust(57) + "║")
    print("║  Previous Period: " + f"{previous_start} to {previous_end}".ljust(57) + "║")
    print("║  Report Month:    " + current_month.ljust(57) + "║")
    print("╚" + "═" * 78 + "╝")
    print("\n")
    
    # Phase 1: Data Collection
    print("PHASE 1: DATA COLLECTION")
    print("-" * 80)
    data = collect_all_monthly_data()
    date_range = data.pop("date_range")  # Extract date_range from data dict
    print()
    
    # Phase 2: KPI Aggregation
    print("PHASE 2: KPI AGGREGATION")
    print("-" * 80)
    kpis = aggregate_monthly_kpis(data)
    print()
    
    # Phase 3: Chart Generation
    print("PHASE 3: CHART GENERATION")
    print("-" * 80)
    chart_paths = build_all_monthly_charts(data)
    print()
    
    # Phase 4: AI Analysis
    print("PHASE 4: AI ANALYSIS")
    print("-" * 80)
    bullets = build_unified_bullets(data, kpis, date_range)
    print()
    
    # Phase 5: HTML Dashboard Generation
    print("PHASE 5: HTML DASHBOARD GENERATION")
    print("-" * 80)
    html_path = generate_monthly_dashboard(bullets, chart_paths, data, kpis, date_range)
    print()
    
    # Phase 6: Monday.com Upload
    print("PHASE 6: MONDAY.COM UPLOAD")
    print("-" * 80)
    github_run_id = os.getenv("GITHUB_RUN_ID")  # Available in GitHub Actions
    upload_to_monday(html_path, bullets, date_range, github_run_id)
    print()
    
    # Phase 7: Google Sheets Logging
    print("PHASE 7: GOOGLE SHEETS LOGGING")
    print("-" * 80)
    log_to_google_sheets(kpis, date_range)
    print()
    
    # Final Summary
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 25 + "REPORT COMPLETE" + " " * 38 + "║")
    print("║" + " " * 78 + "║")
    print("║  Dashboard:       " + str(html_path).ljust(57) + "║")
    print("║  Charts:          " + f"{len(chart_paths)} charts generated".ljust(57) + "║")
    print("║  Insights:        " + f"{len(bullets)} executive bullets".ljust(57) + "║")
    print("║  Report Month:    " + current_month.ljust(57) + "║")
    print("╚" + "═" * 78 + "╝")
    print("\n")


if __name__ == "__main__":
    main()
