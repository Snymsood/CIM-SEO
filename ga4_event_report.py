# ══════════════════════════════════════════════════════════════════════════════
# ga4_event_report.py
# CIM SEO — GA4 Custom Event Weekly Report
# Pulls grouped custom events from GA4, builds a styled HTML email report,
# and delivers it via SMTP.
# ══════════════════════════════════════════════════════════════════════════════

import os
import html as _html
import math
import logging
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from collections import defaultdict

import pandas as pd
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest, FilterExpression,
    Filter, FilterExpressionList,
)

from email_utils import send_html_email, get_recipients, get_smtp_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Auth / config ──────────────────────────────────────────────────────────────
SCOPES      = ["https://www.googleapis.com/auth/analytics.readonly"]
KEY_FILE    = os.getenv("GA4_KEY_FILE", "gsc-key.json")
PROPERTY_ID = os.environ["GA4_PROPERTY_ID"]
CONFIG_PATH = os.getenv("EVENT_CONFIG_PATH", "event_tracking_config.csv")

# ── Brand palette (matches existing CIM reports) ───────────────────────────────
C_NAVY      = "#212878"
C_TEAL      = "#2A9D8F"
C_CORAL     = "#E76F51"
C_GREEN     = "#059669"
C_RED       = "#DC2626"
C_AMBER     = "#D97706"
C_SLATE     = "#64748B"
C_BORDER    = "#E2E8F0"
C_LIGHT     = "#F8FAFC"
C_BLACK     = "#0F172A"
C_WHITE     = "#FFFFFF"

METRIC_HELP = {
    "eventCount":          "Total number of times this event was fired during the week.",
    "eventCountPerUser":   "Average number of times each user triggered this event.",
    "totalUsers":          "Distinct users who triggered this event at least once.",
    "sessions":            "Number of sessions in which this event occurred at least once.",
}


# ══════════════════════════════════════════════════════════════════════════════
# DATE WINDOWS
# ══════════════════════════════════════════════════════════════════════════════

def get_weekly_windows():
    """
    Returns (curr_start, curr_end, prev_start, prev_end) as YYYY-MM-DD strings.
    Current week = the 7 days ending yesterday.
    Previous week = the 7 days before that.
    """
    today      = date.today()
    curr_end   = today - timedelta(days=1)
    curr_start = curr_end - timedelta(days=6)
    prev_end   = curr_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    fmt = lambda d: d.strftime("%Y-%m-%d")
    return fmt(curr_start), fmt(curr_end), fmt(prev_start), fmt(prev_end)


# ══════════════════════════════════════════════════════════════════════════════
# GA4 CLIENT & HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_ga4_client() -> BetaAnalyticsDataClient:
    creds = service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)
    return BetaAnalyticsDataClient(credentials=creds)


def _run_report(client, dimensions, metrics, start_date, end_date,
                event_names=None, limit=1000) -> pd.DataFrame:
    """
    Run a GA4 Data API report, optionally filtered to specific event names.
    Returns a DataFrame.
    """
    dim_objs = [Dimension(name=d) for d in dimensions]
    met_objs = [Metric(name=m) for m in metrics]
    date_range = DateRange(start_date=start_date, end_date=end_date)

    # Build an eventName filter if event_names provided
    dim_filter = None
    if event_names:
        if len(event_names) == 1:
            dim_filter = FilterExpression(
                filter=Filter(
                    field_name="eventName",
                    string_filter=Filter.StringFilter(value=event_names[0])
                )
            )
        else:
            dim_filter = FilterExpression(
                or_group=FilterExpressionList(
                    expressions=[
                        FilterExpression(
                            filter=Filter(
                                field_name="eventName",
                                string_filter=Filter.StringFilter(value=n)
                            )
                        )
                        for n in event_names
                    ]
                )
            )

    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=dim_objs,
        metrics=met_objs,
        date_ranges=[date_range],
        limit=limit,
        dimension_filter=dim_filter,
    )
    response = client.run_report(request)

    rows = []
    for row in response.rows:
        record = {}
        for i, d in enumerate(dimensions):
            record[d] = row.dimension_values[i].value
        for i, m in enumerate(metrics):
            record[m] = row.metric_values[i].value
        rows.append(record)
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=dimensions + metrics)


def _to_num(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """Coerce columns to numeric, fill NaN with 0."""
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df


# ══════════════════════════════════════════════════════════════════════════════
# CONFIG LOADING
# ══════════════════════════════════════════════════════════════════════════════

def load_event_config(path: str = CONFIG_PATH) -> dict:
    """
    Load event_tracking_config.csv.
    Returns a dict: { group_name: [ {event_name, display_name, description}, ... ] }
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Event config not found at '{path}'. "
            "Create event_tracking_config.csv based on the example in .env.example."
        )
    df = pd.read_csv(path)
    required = {"group_name", "event_name", "display_name", "description"}
    missing  = required - set(df.columns)
    if missing:
        raise ValueError(f"event_tracking_config.csv is missing columns: {missing}")

    groups = defaultdict(list)
    for _, row in df.iterrows():
        groups[row["group_name"].strip()].append({
            "event_name":   row["event_name"].strip(),
            "display_name": row["display_name"].strip(),
            "description":  row["description"].strip(),
        })
    # Preserve order of first appearance
    return dict(groups)


# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def fetch_event_summary(client, event_names: list, start: str, end: str) -> pd.DataFrame:
    """
    Fetch headline metrics (eventCount, eventCountPerUser, totalUsers, sessions)
    broken down by eventName.
    """
    dims = ["eventName"]
    mets = ["eventCount", "eventCountPerUser", "totalUsers", "sessions"]
    df   = _run_report(client, dims, mets, start, end, event_names=event_names)
    return _to_num(df, mets) if not df.empty else pd.DataFrame(columns=dims + mets)


def fetch_event_by_page(client, event_names: list, start: str, end: str,
                        top_n: int = 10) -> pd.DataFrame:
    """
    Fetch eventCount per landingPage per eventName. Returns top N pages per event.
    """
    dims = ["eventName", "landingPage"]
    mets = ["eventCount", "sessions"]
    df   = _run_report(client, dims, mets, start, end, event_names=event_names, limit=2000)
    if df.empty:
        return df
    df = _to_num(df, mets)
    # Keep top N pages per event
    df = (df.sort_values("eventCount", ascending=False)
            .groupby("eventName", group_keys=False)
            .head(top_n)
            .reset_index(drop=True))
    return df


def fetch_event_by_device(client, event_names: list, start: str, end: str) -> pd.DataFrame:
    """Fetch eventCount broken down by deviceCategory per event."""
    dims = ["eventName", "deviceCategory"]
    mets = ["eventCount", "totalUsers"]
    df   = _run_report(client, dims, mets, start, end, event_names=event_names)
    return _to_num(df, mets) if not df.empty else df


def fetch_event_by_channel(client, event_names: list, start: str, end: str) -> pd.DataFrame:
    """Fetch eventCount broken down by sessionDefaultChannelGroup per event."""
    dims = ["eventName", "sessionDefaultChannelGroup"]
    mets = ["eventCount", "sessions"]
    df   = _run_report(client, dims, mets, start, end, event_names=event_names)
    return _to_num(df, mets) if not df.empty else df


def fetch_all_data(all_event_names: list,
                   curr_start: str, curr_end: str,
                   prev_start: str, prev_end: str) -> dict:
    """
    Fetch all required data for current and previous periods using parallel threads.
    Returns dict of DataFrames.
    """
    def _run(fn, *args):
        c = get_ga4_client()
        return fn(c, *args)

    tasks = {
        "curr_summary": (fetch_event_summary,  all_event_names, curr_start, curr_end),
        "prev_summary": (fetch_event_summary,  all_event_names, prev_start, prev_end),
        "curr_pages":   (fetch_event_by_page,  all_event_names, curr_start, curr_end),
        "curr_device":  (fetch_event_by_device,all_event_names, curr_start, curr_end),
        "curr_channel": (fetch_event_by_channel,all_event_names, curr_start, curr_end),
    }

    results = {}
    print("  Fetching GA4 event data…", flush=True)
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_map = {executor.submit(_run, fn, *fn_args): key
                      for key, (fn, *fn_args) in tasks.items()}
        for future in as_completed(future_map):
            key = future_map[future]
            try:
                results[key] = future.result()
                n = len(results[key]) if not results[key].empty else 0
                print(f"  ✓ {key} ({n} rows)", flush=True)
            except Exception as e:
                print(f"  ✗ {key}: {e}", flush=True)
                results[key] = pd.DataFrame()
    return results


# ══════════════════════════════════════════════════════════════════════════════
# METRIC HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_event_row(df: pd.DataFrame, event_name: str) -> dict:
    """Extract a single event's metrics from a summary DataFrame."""
    if df.empty or "eventName" not in df.columns:
        return {}
    row = df[df["eventName"].str.lower() == event_name.lower()]
    if row.empty:
        return {}
    return row.iloc[0].to_dict()


def pct_change(curr: float, prev: float) -> float:
    """Safe percentage change calculation."""
    if prev == 0:
        return 100.0 if curr > 0 else 0.0
    return ((curr - prev) / prev) * 100


def fmt_num(n) -> str:
    """Format a number with thousands separator."""
    try:
        n = float(n)
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n:,.0f}"
        if n == int(n):
            return str(int(n))
        return f"{n:.2f}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(n: float) -> str:
    """Format a percentage with sign."""
    try:
        n = float(n)
        sign = "+" if n > 0 else ""
        return f"{sign}{n:.1f}%"
    except (TypeError, ValueError):
        return "—"


def delta_color(n: float) -> str:
    """Return green/red/amber based on direction."""
    if n > 1:  return C_GREEN
    if n < -1: return C_RED
    return C_AMBER


# ══════════════════════════════════════════════════════════════════════════════
# HTML BUILDING BLOCKS
# ══════════════════════════════════════════════════════════════════════════════

EMAIL_CSS = f"""
  /* Reset */
  body, table, td, p, a, li, blockquote {{
    -webkit-text-size-adjust: 100%;
    -ms-text-size-adjust: 100%;
    margin: 0; padding: 0; border: 0;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
    font-size: 14px;
    color: {C_BLACK};
    background: #F1F5F9;
    line-height: 1.6;
  }}
  .wrapper {{
    max-width: 700px;
    margin: 0 auto;
    background: {C_WHITE};
  }}
  /* Header */
  .header {{
    background: {C_NAVY};
    padding: 36px 40px;
    border-bottom: 4px solid {C_TEAL};
  }}
  .header-eyebrow {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: rgba(255,255,255,0.55);
    margin-bottom: 10px;
    font-family: 'Courier New', monospace;
  }}
  .header-title {{
    font-size: 28px;
    font-weight: 800;
    color: {C_WHITE};
    letter-spacing: -0.02em;
    line-height: 1.15;
    margin-bottom: 10px;
  }}
  .header-subtitle {{
    font-size: 12px;
    color: rgba(255,255,255,0.6);
    font-family: 'Courier New', monospace;
    letter-spacing: 0.05em;
  }}
  /* Outer container */
  .body-pad {{
    padding: 32px 40px;
  }}
  /* Section label */
  .section-label {{
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: {C_SLATE};
    margin-bottom: 6px;
    font-family: 'Courier New', monospace;
  }}
  /* Group heading */
  .group-heading {{
    font-size: 18px;
    font-weight: 800;
    color: {C_NAVY};
    letter-spacing: -0.01em;
    padding: 0 0 10px 0;
    border-bottom: 3px solid {C_NAVY};
    margin-bottom: 20px;
    margin-top: 36px;
  }}
  .group-heading:first-of-type {{
    margin-top: 0;
  }}
  /* Event card */
  .event-card {{
    background: {C_LIGHT};
    border: 1px solid {C_BORDER};
    border-radius: 8px;
    padding: 20px 24px;
    margin-bottom: 16px;
  }}
  .event-name {{
    font-size: 13px;
    font-weight: 700;
    color: {C_NAVY};
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 2px;
  }}
  .event-desc {{
    font-size: 12px;
    color: {C_SLATE};
    margin-bottom: 18px;
  }}
  /* KPI row */
  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-bottom: 24px;
  }}
  .kpi-box {{
    background: {C_WHITE};
    border: 1px solid {C_BORDER};
    border-radius: 6px;
    padding: 14px 12px;
    text-align: center;
  }}
  .kpi-label {{
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: {C_SLATE};
    margin-bottom: 6px;
    font-family: 'Courier New', monospace;
  }}
  .kpi-value {{
    font-size: 22px;
    font-weight: 800;
    color: {C_NAVY};
    line-height: 1;
    margin-bottom: 6px;
  }}
  .kpi-delta {{
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 99px;
    font-family: 'Courier New', monospace;
  }}
  .kpi-help {{
    font-size: 10px;
    color: {C_SLATE};
    margin-top: 5px;
    line-height: 1.4;
  }}
  /* Sub-tables */
  .breakdown-title {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: {C_BLACK};
    margin-bottom: 8px;
    margin-top: 18px;
    font-family: 'Courier New', monospace;
    border-left: 3px solid {C_TEAL};
    padding-left: 8px;
  }}
  table.data-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    margin-bottom: 4px;
  }}
  table.data-table th {{
    background: {C_NAVY};
    color: {C_WHITE};
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    padding: 8px 10px;
    text-align: left;
    font-family: 'Courier New', monospace;
  }}
  table.data-table th.num {{
    text-align: right;
  }}
  table.data-table td {{
    padding: 7px 10px;
    border-bottom: 1px solid {C_BORDER};
    color: {C_BLACK};
    vertical-align: top;
  }}
  table.data-table td.num {{
    text-align: right;
    font-family: 'Courier New', monospace;
    font-weight: 600;
  }}
  table.data-table tr:last-child td {{
    border-bottom: none;
  }}
  table.data-table tr:nth-child(even) td {{
    background: {C_LIGHT};
  }}
  /* Divider */
  .divider {{
    height: 1px;
    background: {C_BORDER};
    margin: 32px 0;
  }}
  /* Footer */
  .footer {{
    background: {C_LIGHT};
    border-top: 1px solid {C_BORDER};
    padding: 20px 40px;
    font-size: 11px;
    color: {C_SLATE};
    text-align: center;
    line-height: 1.7;
  }}
  .no-data {{
    font-size: 12px;
    color: {C_SLATE};
    font-style: italic;
    padding: 8px 0;
  }}
"""


def _delta_badge(curr: float, prev: float) -> str:
    """Render a coloured WoW delta badge."""
    pct = pct_change(curr, prev)
    col = delta_color(pct)
    bg  = "#DCFCE7" if pct > 1 else ("#FEE2E2" if pct < -1 else "#FEF3C7")
    return (
        f'<span class="kpi-delta" style="background:{bg};color:{col};">'
        f'{fmt_pct(pct)} WoW</span>'
    )


def _kpi_box(label: str, curr_val: float, prev_val: float, help_text: str) -> str:
    delta = _delta_badge(curr_val, prev_val)
    return f"""
    <div class="kpi-box">
      <div class="kpi-label">{_html.escape(label)}</div>
      <div class="kpi-value">{fmt_num(curr_val)}</div>
      {delta}
      <div class="kpi-help">{_html.escape(help_text)}</div>
    </div>"""


def _page_table(df_pages: pd.DataFrame, event_name: str) -> str:
    """Render a top-pages breakdown table for one event."""
    sub = df_pages[df_pages["eventName"].str.lower() == event_name.lower()]
    if sub.empty:
        return '<p class="no-data">No page-level data available for this period.</p>'

    rows_html = ""
    for i, (_, r) in enumerate(sub.iterrows(), 1):
        page  = _html.escape(str(r.get("landingPage", "—")))
        count = fmt_num(r.get("eventCount", 0))
        sess  = fmt_num(r.get("sessions", 0))
        rows_html += f"""
        <tr>
          <td style="color:{C_SLATE};font-family:'Courier New',monospace;font-size:11px;">
            {i}
          </td>
          <td style="word-break:break-all;">{page}</td>
          <td class="num">{count}</td>
          <td class="num">{sess}</td>
        </tr>"""

    return f"""
    <table class="data-table">
      <thead>
        <tr>
          <th style="width:32px;">#</th>
          <th>Landing Page</th>
          <th class="num">Event Count</th>
          <th class="num">Sessions</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    <p style="font-size:10px;color:{C_SLATE};margin-top:4px;font-style:italic;">
      Event Count = total times this event fired on this page.
      Sessions = number of sessions where the page was the entry point.
    </p>"""


def _device_table(df_device: pd.DataFrame, event_name: str) -> str:
    """Render a device breakdown table for one event."""
    sub = df_device[df_device["eventName"].str.lower() == event_name.lower()]
    if sub.empty:
        return '<p class="no-data">No device data available.</p>'

    total = sub["eventCount"].sum()
    rows_html = ""
    for _, r in sub.sort_values("eventCount", ascending=False).iterrows():
        dev   = _html.escape(str(r.get("deviceCategory", "—")).title())
        count = float(r.get("eventCount", 0))
        users = fmt_num(r.get("totalUsers", 0))
        share = f"{(count/total*100):.0f}%" if total > 0 else "—"

        # Mini bar (inline style, email-safe)
        bar_w = int((count / total * 100)) if total > 0 else 0
        bar   = (
            f'<div style="height:6px;background:{C_BORDER};border-radius:3px;margin-top:4px;">'
            f'<div style="height:6px;width:{bar_w}%;background:{C_TEAL};border-radius:3px;"></div>'
            f'</div>'
        )
        rows_html += f"""
        <tr>
          <td>{dev}{bar}</td>
          <td class="num">{fmt_num(count)}</td>
          <td class="num">{share}</td>
          <td class="num">{users}</td>
        </tr>"""

    return f"""
    <table class="data-table">
      <thead>
        <tr>
          <th>Device</th>
          <th class="num">Event Count</th>
          <th class="num">Share</th>
          <th class="num">Users</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    <p style="font-size:10px;color:{C_SLATE};margin-top:4px;font-style:italic;">
      Share = proportion of this event's total count from this device type.
    </p>"""


def _channel_table(df_channel: pd.DataFrame, event_name: str) -> str:
    """Render a traffic channel breakdown table for one event."""
    sub = df_channel[df_channel["eventName"].str.lower() == event_name.lower()]
    if sub.empty:
        return '<p class="no-data">No channel data available.</p>'

    total = sub["eventCount"].sum()
    rows_html = ""
    for _, r in sub.sort_values("eventCount", ascending=False).iterrows():
        ch    = _html.escape(str(r.get("sessionDefaultChannelGroup", "—")))
        count = float(r.get("eventCount", 0))
        sess  = fmt_num(r.get("sessions", 0))
        share = f"{(count/total*100):.0f}%" if total > 0 else "—"
        rows_html += f"""
        <tr>
          <td>{ch}</td>
          <td class="num">{fmt_num(count)}</td>
          <td class="num">{share}</td>
          <td class="num">{sess}</td>
        </tr>"""

    return f"""
    <table class="data-table">
      <thead>
        <tr>
          <th>Traffic Channel</th>
          <th class="num">Event Count</th>
          <th class="num">Share</th>
          <th class="num">Sessions</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    <p style="font-size:10px;color:{C_SLATE};margin-top:4px;font-style:italic;">
      Channel = the default channel group Google Analytics assigned to the user's session
      (e.g. Organic Search, Direct, Referral, Email, Paid Search).
      Sessions = sessions from this channel where the event occurred.
    </p>"""


def _render_event_card(event: dict, data: dict) -> str:
    """Render the full event card for a single event (KPIs + all breakdowns)."""
    ename        = event["event_name"]
    display_name = event["display_name"]
    description  = event["description"]

    curr_row = get_event_row(data["curr_summary"], ename)
    prev_row = get_event_row(data["prev_summary"], ename)

    curr_count  = float(curr_row.get("eventCount", 0))
    prev_count  = float(prev_row.get("eventCount", 0))
    curr_cpu    = float(curr_row.get("eventCountPerUser", 0))
    prev_cpu    = float(prev_row.get("eventCountPerUser", 0))
    curr_users  = float(curr_row.get("totalUsers", 0))
    prev_users  = float(prev_row.get("totalUsers", 0))
    curr_sess   = float(curr_row.get("sessions", 0))
    prev_sess   = float(prev_row.get("sessions", 0))

    kpi_row = f"""
    <div class="kpi-row">
      {_kpi_box("Event Count",       curr_count, prev_count, METRIC_HELP["eventCount"])}
      {_kpi_box("Events / User",     curr_cpu,   prev_cpu,   METRIC_HELP["eventCountPerUser"])}
      {_kpi_box("Unique Users",      curr_users, prev_users, METRIC_HELP["totalUsers"])}
      {_kpi_box("Sessions",          curr_sess,  prev_sess,  METRIC_HELP["sessions"])}
    </div>"""

    page_tbl    = _page_table(data["curr_pages"],   ename)
    device_tbl  = _device_table(data["curr_device"], ename)
    channel_tbl = _channel_table(data["curr_channel"], ename)

    return f"""
    <div class="event-card">
      <div class="event-name">{_html.escape(display_name)}</div>
      <div class="event-desc">{_html.escape(description)}
        <span style="font-family:'Courier New',monospace;font-size:10px;
                     color:{C_SLATE};margin-left:8px;">({_html.escape(ename)})</span>
      </div>
      {kpi_row}

      <div class="breakdown-title">▸ Top Landing Pages</div>
      {page_tbl}

      <div class="breakdown-title">▸ Device Breakdown</div>
      {device_tbl}

      <div class="breakdown-title">▸ Traffic Channel Breakdown</div>
      {channel_tbl}
    </div>"""


def _render_group_summary_bar(group_name: str, events: list, data: dict) -> str:
    """Render a compact group-level summary row above the event cards."""
    total_curr = sum(
        float(get_event_row(data["curr_summary"], e["event_name"]).get("eventCount", 0))
        for e in events
    )
    total_prev = sum(
        float(get_event_row(data["prev_summary"], e["event_name"]).get("eventCount", 0))
        for e in events
    )
    pct  = pct_change(total_curr, total_prev)
    col  = delta_color(pct)
    bg   = "#DCFCE7" if pct > 1 else ("#FEE2E2" if pct < -1 else "#FEF3C7")

    return f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;
                background:{C_LIGHT};border:1px solid {C_BORDER};
                border-radius:6px;padding:12px 18px;">
      <div>
        <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.1em;
                    color:{C_SLATE};font-family:'Courier New',monospace;">
          Group Total Events This Week
        </div>
        <div style="font-size:24px;font-weight:800;color:{C_NAVY};">
          {fmt_num(total_curr)}
        </div>
      </div>
      <span style="background:{bg};color:{col};font-size:11px;font-weight:700;
                   padding:3px 10px;border-radius:99px;font-family:'Courier New',monospace;">
        {fmt_pct(pct)} vs last week
      </span>
      <span style="font-size:11px;color:{C_SLATE};margin-left:auto;">
        {len(events)} event{"s" if len(events) != 1 else ""} tracked
      </span>
    </div>"""


# ══════════════════════════════════════════════════════════════════════════════
# FULL REPORT HTML
# ══════════════════════════════════════════════════════════════════════════════

def build_report_html(groups: dict, data: dict,
                      curr_start: str, curr_end: str,
                      prev_start: str, prev_end: str) -> str:
    """Assemble the complete inline-CSS HTML email body."""

    # Format dates nicely
    def _fmt(d: str) -> str:
        return date.fromisoformat(d).strftime("%-d %b %Y")

    date_range_label = f"{_fmt(curr_start)} – {_fmt(curr_end)}"
    prev_range_label = f"{_fmt(prev_start)} – {_fmt(prev_end)}"
    generated_on     = date.today().strftime("%-d %B %Y")

    # Build group sections
    group_sections = ""
    for group_name, events in groups.items():
        event_cards = "".join(_render_event_card(e, data) for e in events)
        summary_bar = _render_group_summary_bar(group_name, events, data)

        group_sections += f"""
        <div class="section-label">Homepage Events</div>
        <div class="group-heading">{_html.escape(group_name)}</div>
        {summary_bar}
        {event_cards}
        <div class="divider"></div>"""

    # Metrics glossary
    glossary_rows = "".join(
        f"<tr><td style='font-weight:700;white-space:nowrap;padding:5px 10px 5px 0;'>"
        f"{_html.escape(k.replace('eventCount','Event Count').replace('eventCountPerUser','Events / User').replace('totalUsers','Unique Users').replace('sessions','Sessions'))}</td>"
        f"<td style='padding:5px 0;color:{C_SLATE};'>{_html.escape(v)}</td></tr>"
        for k, v in METRIC_HELP.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>CIM GA4 Event Report — {date_range_label}</title>
  <style>{EMAIL_CSS}</style>
</head>
<body>
<div class="wrapper">

  <!-- HEADER -->
  <div class="header">
    <div class="header-eyebrow">CIM SEO Platform · Weekly Event Intelligence</div>
    <div class="header-title">GA4 Homepage Event Report</div>
    <div class="header-subtitle">
      {date_range_label} &nbsp;·&nbsp; vs. {prev_range_label}
    </div>
  </div>

  <!-- INTRO NOTE -->
  <div class="body-pad" style="padding-bottom:0;">
    <p style="font-size:13px;color:{C_SLATE};line-height:1.7;margin-bottom:8px;">
      This report tracks the performance of <strong>homepage interaction events</strong>
      in GA4 for the week of <strong>{date_range_label}</strong>.
      All week-over-week (WoW) comparisons are against the prior week
      ({prev_range_label}).
    </p>
    <p style="font-size:12px;color:{C_SLATE};line-height:1.7;">
      Events are grouped by homepage section. Each card shows four headline metrics
      plus breakdowns by landing page, device, and traffic channel.
      Metric definitions are listed at the foot of this email.
    </p>
  </div>

  <!-- REPORT BODY -->
  <div class="body-pad">
    {group_sections}

    <!-- GLOSSARY -->
    <div style="background:{C_LIGHT};border:1px solid {C_BORDER};border-radius:8px;
                padding:20px 24px;margin-top:8px;">
      <div class="section-label" style="margin-bottom:10px;">Metric Definitions</div>
      <table style="border-collapse:collapse;width:100%;font-size:12px;">
        <tbody>{glossary_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- FOOTER -->
  <div class="footer">
    Automatically generated by the CIM SEO Platform on {generated_on}.<br>
    Data source: Google Analytics 4 property {_html.escape(PROPERTY_ID)}.<br>
    WoW = week-over-week change. All metrics reflect the date range shown above.
  </div>

</div>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70, flush=True)
    print("GA4 CUSTOM EVENT WEEKLY REPORT", flush=True)
    print("=" * 70, flush=True)

    # 1. Load event configuration
    print("\n[1/4] Loading event configuration…", flush=True)
    groups = load_event_config(CONFIG_PATH)
    all_event_names = [e["event_name"] for evts in groups.values() for e in evts]
    print(f"  ✓ {len(groups)} groups, {len(all_event_names)} events loaded", flush=True)
    for g, evts in groups.items():
        print(f"      [{g}] " + ", ".join(e["event_name"] for e in evts), flush=True)

    # 2. Date windows
    print("\n[2/4] Computing date windows…", flush=True)
    curr_start, curr_end, prev_start, prev_end = get_weekly_windows()
    print(f"  ✓ Current : {curr_start} → {curr_end}", flush=True)
    print(f"  ✓ Previous: {prev_start} → {prev_end}", flush=True)

    # 3. Fetch data
    print("\n[3/4] Fetching GA4 data…", flush=True)
    data = fetch_all_data(all_event_names, curr_start, curr_end, prev_start, prev_end)

    # 4. Build + send report
    print("\n[4/4] Building HTML report and sending email…", flush=True)
    html_body = build_report_html(
        groups, data, curr_start, curr_end, prev_start, prev_end
    )

    # Save local copy for inspection
    out_path = Path("ga4_event_report_output.html")
    out_path.write_text(html_body, encoding="utf-8")
    print(f"  ✓ HTML saved to {out_path.resolve()}", flush=True)

    # Send email
    from datetime import date as _date
    _fmt = lambda d: _date.fromisoformat(d).strftime("%-d %b %Y")
    subject = (
        f"CIM GA4 Homepage Event Report — {_fmt(curr_start)} to {_fmt(curr_end)}"
    )
    success = send_html_email(subject=subject, html_body=html_body)

    if success:
        print("\n✅ Report sent successfully.", flush=True)
    else:
        print("\n⚠️  Report built but email delivery failed. Check SMTP config in .env.", flush=True)

    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
