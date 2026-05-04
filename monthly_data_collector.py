#!/usr/bin/env python3
"""
Monthly Data Collector

Fetches all data sources for the monthly master dashboard:
- Google Analytics 4 (GA4)
- Google Search Console (GSC)
- PageSpeed Insights
- Content Category Performance
- Technical Health Metrics

Runs on the 1st of each month to collect previous month's data.
Example: On May 1st, collects April data (vs March comparison).
"""

import asyncio
import os
import pandas as pd
from datetime import date
from pathlib import Path

from seo_utils import get_monthly_date_windows
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
from googleapiclient.discovery import build
import google_auth_httplib2
import httplib2

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

KEY_FILE = "gsc-key.json"
GSC_PROPERTY = os.environ.get("GSC_PROPERTY", "https://www.cim.org/")
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "341629008")

OUTPUT_DIR = Path("monthly_data")
OUTPUT_DIR.mkdir(exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# GA4 DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def get_ga4_client():
    """Build GA4 client."""
    credentials = service_account.Credentials.from_service_account_file(
        KEY_FILE,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    return BetaAnalyticsDataClient(credentials=credentials)


def fetch_ga4_summary(client, start_date, end_date):
    """Fetch GA4 summary metrics for a date range."""
    metrics = [
        "activeUsers",
        "sessions",
        "engagedSessions",
        "engagementRate",
        "averageSessionDuration",
        "eventCount",
        "bounceRate",
    ]
    
    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())],
        limit=1,
    )
    
    try:
        response = client.run_report(request)
        if not response.rows:
            return {m: 0 for m in metrics}
        
        row = response.rows[0]
        values = {}
        for i, metric in enumerate(metrics):
            values[metric] = float(row.metric_values[i].value)
        return values
    except Exception as e:
        print(f"GA4 summary fetch failed: {e}")
        return {m: 0 for m in metrics}


def fetch_ga4_daily_trend(client, start_date, end_date):
    """Fetch GA4 daily sessions and users for trend chart."""
    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name="date")],
        metrics=[Metric(name="sessions"), Metric(name="activeUsers"), Metric(name="engagementRate")],
        date_ranges=[DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())],
        limit=100,
    )
    
    try:
        response = client.run_report(request)
        data = []
        for row in response.rows:
            data.append({
                "date": row.dimension_values[0].value,
                "sessions": float(row.metric_values[0].value),
                "activeUsers": float(row.metric_values[1].value),
                "engagementRate": float(row.metric_values[2].value),
            })
        return pd.DataFrame(data)
    except Exception as e:
        print(f"GA4 daily trend fetch failed: {e}")
        return pd.DataFrame()


def fetch_ga4_landing_pages(client, start_date, end_date):
    """Fetch top landing pages from GA4."""
    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name="landingPage")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="engagementRate"),
            Metric(name="averageSessionDuration"),
        ],
        date_ranges=[DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())],
        limit=100,
    )
    
    try:
        response = client.run_report(request)
        data = []
        for row in response.rows:
            data.append({
                "landingPage": row.dimension_values[0].value,
                "sessions": float(row.metric_values[0].value),
                "activeUsers": float(row.metric_values[1].value),
                "engagementRate": float(row.metric_values[2].value),
                "averageSessionDuration": float(row.metric_values[3].value),
            })
        return pd.DataFrame(data)
    except Exception as e:
        print(f"GA4 landing pages fetch failed: {e}")
        return pd.DataFrame()


def fetch_ga4_channels(client, start_date, end_date):
    """Fetch channel performance from GA4."""
    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name="sessionDefaultChannelGroup")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="engagementRate"),
        ],
        date_ranges=[DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())],
        limit=20,
    )
    
    try:
        response = client.run_report(request)
        data = []
        for row in response.rows:
            data.append({
                "channel": row.dimension_values[0].value,
                "sessions": float(row.metric_values[0].value),
                "activeUsers": float(row.metric_values[1].value),
                "engagementRate": float(row.metric_values[2].value),
            })
        return pd.DataFrame(data)
    except Exception as e:
        print(f"GA4 channels fetch failed: {e}")
        return pd.DataFrame()


def fetch_ga4_devices(client, start_date, end_date):
    """Fetch device split from GA4."""
    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name="deviceCategory")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="engagementRate"),
        ],
        date_ranges=[DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())],
        limit=10,
    )
    
    try:
        response = client.run_report(request)
        data = []
        for row in response.rows:
            data.append({
                "device": row.dimension_values[0].value,
                "sessions": float(row.metric_values[0].value),
                "activeUsers": float(row.metric_values[1].value),
                "engagementRate": float(row.metric_values[2].value),
            })
        return pd.DataFrame(data)
    except Exception as e:
        print(f"GA4 devices fetch failed: {e}")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# GSC DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def get_gsc_service():
    """Build GSC service."""
    credentials = service_account.Credentials.from_service_account_file(
        KEY_FILE,
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    authed_http = google_auth_httplib2.AuthorizedHttp(
        credentials, http=httplib2.Http(timeout=120)
    )
    return build("searchconsole", "v1", http=authed_http, cache_discovery=False)


def fetch_gsc_queries(service, start_date, end_date):
    """Fetch top queries from GSC."""
    body = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["query"],
        "rowLimit": 1000,
    }
    
    try:
        response = service.searchanalytics().query(siteUrl=GSC_PROPERTY, body=body).execute()
        rows = response.get("rows", [])
        data = []
        for row in rows:
            data.append({
                "query": row["keys"][0],
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0),
                "position": row.get("position", 0),
            })
        return pd.DataFrame(data)
    except Exception as e:
        print(f"GSC queries fetch failed: {e}")
        return pd.DataFrame()


def fetch_gsc_pages(service, start_date, end_date):
    """Fetch top pages from GSC."""
    body = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["page"],
        "rowLimit": 1000,
    }
    
    try:
        response = service.searchanalytics().query(siteUrl=GSC_PROPERTY, body=body).execute()
        rows = response.get("rows", [])
        data = []
        for row in rows:
            data.append({
                "page": row["keys"][0],
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0),
                "position": row.get("position", 0),
            })
        return pd.DataFrame(data)
    except Exception as e:
        print(f"GSC pages fetch failed: {e}")
        return pd.DataFrame()


def fetch_gsc_daily_trend(service, start_date, end_date):
    """Fetch GSC daily clicks and impressions for trend chart."""
    body = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["date"],
        "rowLimit": 100,
    }
    
    try:
        response = service.searchanalytics().query(siteUrl=GSC_PROPERTY, body=body).execute()
        rows = response.get("rows", [])
        data = []
        for row in rows:
            data.append({
                "date": row["keys"][0],
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0),
                "position": row.get("position", 0),
            })
        df = pd.DataFrame(data)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")
        return df
    except Exception as e:
        print(f"GSC daily trend fetch failed: {e}")
        return pd.DataFrame()


def fetch_gsc_devices(service, start_date, end_date):
    """Fetch device split from GSC."""
    body = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["device"],
        "rowLimit": 10,
    }
    
    try:
        response = service.searchanalytics().query(siteUrl=GSC_PROPERTY, body=body).execute()
        rows = response.get("rows", [])
        data = []
        for row in rows:
            data.append({
                "device": row["keys"][0],
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0),
                "position": row.get("position", 0),
            })
        return pd.DataFrame(data)
    except Exception as e:
        print(f"GSC devices fetch failed: {e}")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# DATA AGGREGATION & COMPARISON
# ══════════════════════════════════════════════════════════════════════════════

def prepare_summary_comparison(current_summary, previous_summary):
    """Prepare month-over-month comparison for summary metrics."""
    rows = []
    for metric in current_summary.keys():
        current_value = float(current_summary.get(metric, 0))
        previous_value = float(previous_summary.get(metric, 0))
        change = current_value - previous_value
        pct_change = (change / previous_value * 100) if previous_value > 0 else 0
        
        rows.append({
            "metric": metric,
            "current": current_value,
            "previous": previous_value,
            "change": change,
            "pct_change": pct_change,
        })
    return pd.DataFrame(rows)


def prepare_query_comparison(current_queries, previous_queries):
    """Prepare month-over-month comparison for queries."""
    if current_queries.empty and previous_queries.empty:
        return pd.DataFrame()
    
    # Rename columns
    current = current_queries.copy()
    previous = previous_queries.copy()
    
    for col in ["clicks", "impressions", "ctr", "position"]:
        if col in current.columns:
            current = current.rename(columns={col: f"{col}_current"})
        if col in previous.columns:
            previous = previous.rename(columns={col: f"{col}_previous"})
    
    # Merge
    merged = pd.merge(current, previous, on="query", how="outer").fillna(0)
    
    # Calculate changes
    for col in ["clicks", "impressions", "ctr", "position"]:
        if f"{col}_current" in merged.columns and f"{col}_previous" in merged.columns:
            merged[f"{col}_change"] = merged[f"{col}_current"] - merged[f"{col}_previous"]
            merged[f"{col}_pct_change"] = merged.apply(
                lambda row: (row[f"{col}_change"] / row[f"{col}_previous"] * 100) 
                if row[f"{col}_previous"] > 0 else 0,
                axis=1
            )
    
    # Sort by current clicks descending
    if "clicks_current" in merged.columns:
        merged = merged.sort_values("clicks_current", ascending=False)
    
    return merged


def prepare_page_comparison(current_pages, previous_pages):
    """Prepare month-over-month comparison for pages."""
    if current_pages.empty and previous_pages.empty:
        return pd.DataFrame()
    
    # Rename columns
    current = current_pages.copy()
    previous = previous_pages.copy()
    
    for col in ["clicks", "impressions", "ctr", "position"]:
        if col in current.columns:
            current = current.rename(columns={col: f"{col}_current"})
        if col in previous.columns:
            previous = previous.rename(columns={col: f"{col}_previous"})
    
    # Merge
    merged = pd.merge(current, previous, on="page", how="outer").fillna(0)
    
    # Calculate changes
    for col in ["clicks", "impressions", "ctr", "position"]:
        if f"{col}_current" in merged.columns and f"{col}_previous" in merged.columns:
            merged[f"{col}_change"] = merged[f"{col}_current"] - merged[f"{col}_previous"]
            merged[f"{col}_pct_change"] = merged.apply(
                lambda row: (row[f"{col}_change"] / row[f"{col}_previous"] * 100) 
                if row[f"{col}_previous"] > 0 else 0,
                axis=1
            )
    
    # Sort by current clicks descending
    if "clicks_current" in merged.columns:
        merged = merged.sort_values("clicks_current", ascending=False)
    
    return merged


# ══════════════════════════════════════════════════════════════════════════════
# PAGESPEED DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def load_pagespeed_data():
    """Load latest PageSpeed snapshot data if available."""
    snapshot_file = Path("site_speed_latest_snapshot.csv")
    if snapshot_file.exists():
        try:
            df = pd.read_csv(snapshot_file)
            print("  ✓ Loaded PageSpeed snapshot data")
            return df
        except Exception as e:
            print(f"  ⚠ Failed to load PageSpeed data: {e}")
            return pd.DataFrame()
    else:
        print("  ⚠ No PageSpeed snapshot found (run site_speed_monitoring.py first)")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# AI SNIPPET DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def load_ai_snippet_data():
    """Load latest AI snippet verification data if available."""
    report_file = Path("reports/ai_snippet_verification.csv")
    if report_file.exists():
        try:
            df = pd.read_csv(report_file)
            print("  ✓ Loaded AI snippet verification data")
            return df
        except Exception as e:
            print(f"  ⚠ Failed to load AI snippet data: {e}")
            return pd.DataFrame()
    else:
        print("  ⚠ No AI snippet data found (run ai_snippet_verification.py first)")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# CONTENT AUDIT DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def load_content_audit_data():
    """Load latest content audit data if available."""
    candidates_file = Path("content_audit_candidates.csv")
    if candidates_file.exists():
        try:
            df = pd.read_csv(candidates_file)
            print("  ✓ Loaded content audit data")
            return df
        except Exception as e:
            print(f"  ⚠ Failed to load content audit data: {e}")
            return pd.DataFrame()
    else:
        print("  ⚠ No content audit data found (run content_audit_schedule_report.py first)")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# BROKEN LINK DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def load_broken_link_data():
    """Load latest broken link results if available."""
    results_file = Path("broken_link_results.csv")
    if results_file.exists():
        try:
            df = pd.read_csv(results_file)
            print("  ✓ Loaded broken link results data")
            return df
        except Exception as e:
            print(f"  ⚠ Failed to load broken link data: {e}")
            return pd.DataFrame()
    else:
        print("  ⚠ No broken link data found (run broken_link_check.py first)")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL LINKING DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def load_internal_linking_data():
    """Load latest internal linking page summary if available."""
    summary_file = Path("internal_linking_page_summary.csv")
    if summary_file.exists():
        try:
            df = pd.read_csv(summary_file)
            print("  ✓ Loaded internal linking page summary")
            return df
        except Exception as e:
            print(f"  ⚠ Failed to load internal linking data: {e}")
            return pd.DataFrame()
    else:
        print("  ⚠ No internal linking data found (run internal_linking_audit.py first)")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# CONTENT CATEGORY DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def load_content_category_data():
    """Load latest content category performance data if available."""
    cat_file = Path("content_category_performance.csv")
    if cat_file.exists():
        try:
            df = pd.read_csv(cat_file)
            print("  ✓ Loaded content category performance data")
            return df
        except Exception as e:
            print(f"  ⚠ Failed to load content category data: {e}")
            return pd.DataFrame()
    else:
        print("  ⚠ No content category data found (run content_category_performance.py first)")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN COLLECTION FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def collect_all_monthly_data():
    """
    Collect all data sources for monthly dashboard.
    
    Returns:
        dict: Dictionary containing all collected data
    """
    print("=" * 80)
    print("MONTHLY DATA COLLECTION - STARTING")
    print("=" * 80)
    
    # Get date windows
    current_start, current_end, previous_start, previous_end = get_monthly_date_windows()
    
    print(f"\nCurrent period:  {current_start} to {current_end}")
    print(f"Previous period: {previous_start} to {previous_end}")
    print()
    
    # Initialize clients
    print("[1/4] Initializing API clients...")
    ga4_client = get_ga4_client()
    gsc_service = get_gsc_service()
    print("✓ Clients initialized")
    
    # Fetch GA4 data
    print("\n[2/4] Fetching GA4 & GSC data...")
    print("  → GA4 summary (current)...")
    ga4_summary_current = fetch_ga4_summary(ga4_client, current_start, current_end)
    print("  → GA4 summary (previous)...")
    ga4_summary_previous = fetch_ga4_summary(ga4_client, previous_start, previous_end)
    print("  → GA4 daily trend (current)...")
    ga4_daily_current = fetch_ga4_daily_trend(ga4_client, current_start, current_end)
    print("  → GA4 landing pages (current)...")
    ga4_pages_current = fetch_ga4_landing_pages(ga4_client, current_start, current_end)
    print("  → GA4 landing pages (previous)...")
    ga4_pages_previous = fetch_ga4_landing_pages(ga4_client, previous_start, previous_end)
    print("  → GA4 channels (current)...")
    ga4_channels_current = fetch_ga4_channels(ga4_client, current_start, current_end)
    print("  → GA4 channels (previous)...")
    ga4_channels_previous = fetch_ga4_channels(ga4_client, previous_start, previous_end)
    print("  → GA4 devices (current)...")
    ga4_devices_current = fetch_ga4_devices(ga4_client, current_start, current_end)
    
    # Fetch GSC data
    print("  → GSC queries (current)...")
    gsc_queries_current = fetch_gsc_queries(gsc_service, current_start, current_end)
    print("  → GSC queries (previous)...")
    gsc_queries_previous = fetch_gsc_queries(gsc_service, previous_start, previous_end)
    print("  → GSC pages (current)...")
    gsc_pages_current = fetch_gsc_pages(gsc_service, current_start, current_end)
    print("  → GSC pages (previous)...")
    gsc_pages_previous = fetch_gsc_pages(gsc_service, previous_start, previous_end)
    print("  → GSC daily trend (current)...")
    gsc_daily_current = fetch_gsc_daily_trend(gsc_service, current_start, current_end)
    print("  → GSC devices (current)...")
    gsc_devices_current = fetch_gsc_devices(gsc_service, current_start, current_end)
    
    print("✓ GA4 & GSC data fetching complete")
    
    # Load additional data sources
    print("\n[3/4] Loading additional data sources...")
    pagespeed_data       = load_pagespeed_data()
    ai_snippet_data      = load_ai_snippet_data()
    content_audit_data   = load_content_audit_data()
    broken_link_data     = load_broken_link_data()
    internal_link_data   = load_internal_linking_data()
    content_category_data = load_content_category_data()
    
    # Prepare comparisons
    print("\n[4/4] Preparing comparisons...")
    ga4_summary_comparison = prepare_summary_comparison(ga4_summary_current, ga4_summary_previous)
    gsc_queries_comparison = prepare_query_comparison(gsc_queries_current, gsc_queries_previous)
    gsc_pages_comparison = prepare_page_comparison(gsc_pages_current, gsc_pages_previous)
    print("✓ Comparisons prepared")
    
    # Save to CSV
    print("\n[5/5] Saving data to CSV...")
    ga4_summary_comparison.to_csv(OUTPUT_DIR / "monthly_ga4_summary.csv", index=False)
    ga4_daily_current.to_csv(OUTPUT_DIR / "monthly_ga4_daily.csv", index=False)
    ga4_pages_current.to_csv(OUTPUT_DIR / "monthly_ga4_pages_current.csv", index=False)
    ga4_channels_current.to_csv(OUTPUT_DIR / "monthly_ga4_channels_current.csv", index=False)
    ga4_channels_previous.to_csv(OUTPUT_DIR / "monthly_ga4_channels_previous.csv", index=False)
    ga4_devices_current.to_csv(OUTPUT_DIR / "monthly_ga4_devices.csv", index=False)
    
    gsc_queries_comparison.to_csv(OUTPUT_DIR / "monthly_gsc_queries.csv", index=False)
    gsc_pages_comparison.to_csv(OUTPUT_DIR / "monthly_gsc_pages.csv", index=False)
    gsc_daily_current.to_csv(OUTPUT_DIR / "monthly_gsc_daily.csv", index=False)
    gsc_devices_current.to_csv(OUTPUT_DIR / "monthly_gsc_devices.csv", index=False)
    
    # Save additional data sources
    if not pagespeed_data.empty:
        pagespeed_data.to_csv(OUTPUT_DIR / "monthly_pagespeed.csv", index=False)
    if not ai_snippet_data.empty:
        ai_snippet_data.to_csv(OUTPUT_DIR / "monthly_ai_snippet.csv", index=False)
    if not content_audit_data.empty:
        content_audit_data.to_csv(OUTPUT_DIR / "monthly_content_audit.csv", index=False)
    if not broken_link_data.empty:
        broken_link_data.to_csv(OUTPUT_DIR / "monthly_broken_links.csv", index=False)
    if not internal_link_data.empty:
        internal_link_data.to_csv(OUTPUT_DIR / "monthly_internal_links.csv", index=False)
    if not content_category_data.empty:
        content_category_data.to_csv(OUTPUT_DIR / "monthly_content_categories.csv", index=False)
    
    print("✓ Data saved to monthly_data/")
    
    print("\n" + "=" * 80)
    print("MONTHLY DATA COLLECTION - COMPLETE")
    print("=" * 80)
    
    return {
        "ga4_summary": ga4_summary_comparison,
        "ga4_daily": ga4_daily_current,
        "ga4_pages": ga4_pages_current,
        "ga4_channels_current": ga4_channels_current,
        "ga4_channels_previous": ga4_channels_previous,
        "ga4_devices": ga4_devices_current,
        "gsc_queries": gsc_queries_comparison,
        "gsc_pages": gsc_pages_comparison,
        "gsc_daily": gsc_daily_current,
        "gsc_devices": gsc_devices_current,
        "pagespeed": pagespeed_data,
        "ai_snippet": ai_snippet_data,
        "content_audit": content_audit_data,
        "broken_links": broken_link_data,
        "internal_links": internal_link_data,
        "content_categories": content_category_data,
        "date_range": {
            "current_start": current_start,
            "current_end": current_end,
            "previous_start": previous_start,
            "previous_end": previous_end,
        }
    }


if __name__ == "__main__":
    collect_all_monthly_data()
