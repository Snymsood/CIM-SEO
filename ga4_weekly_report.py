# ══════════════════════════════════════════════════════════════════════════════
# ga4_weekly_report.py
# CIM SEO — GA4 Weekly Performance Report
# Redesigned per report_design_principles.md
# ══════════════════════════════════════════════════════════════════════════════

from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from pathlib import Path
import pandas as pd
import requests
import os
import html
import math
import base64
import re
import json
from html_report_utils import (
    mm_html_shell, mm_section, mm_kpi_card, mm_kpi_grid,
    mm_apex_chart, mm_report_section, mm_col_header, mm_exec_bullets
)

from google_sheets_db import append_to_sheet
from pdf_report_formatter import format_pct_change, format_num
from seo_utils import get_weekly_date_windows, short_url
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest,
)

# ── Auth / config ──────────────────────────────────────────────────────────────
SCOPES      = ["https://www.googleapis.com/auth/analytics.readonly"]
KEY_FILE    = "gsc-key.json"
PROPERTY_ID = os.environ["GA4_PROPERTY_ID"]

GROQ_API_KEY     = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID   = os.getenv("MONDAY_ITEM_ID")

MONDAY_API_URL      = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"
CHARTS_DIR          = Path("charts")

# ── Brand palette ──────────────────────────────────────────────────────────────
C_NAVY   = "#212878"
C_TEAL   = "#2A9D8F"
C_CORAL  = "#E76F51"
C_SLATE  = "#6C757D"
C_GREEN  = "#059669"
C_RED    = "#DC2626"
C_AMBER  = "#D97706"
C_BORDER = "#E2E8F0"
C_LIGHT  = "#F1F5F9"



# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def get_credentials():
    return service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)


def get_ga4_client():
    return BetaAnalyticsDataClient(credentials=get_credentials())


def _run_report(client, dimensions, metrics, start_date, end_date, limit=1000):
    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        limit=limit,
    )
    return client.run_report(request)


def _response_to_df(response, dimensions, metrics):
    rows = []
    for row in response.rows:
        record = {}
        for i, dim in enumerate(dimensions):
            record[dim] = row.dimension_values[i].value
        for i, met in enumerate(metrics):
            record[met] = row.metric_values[i].value
        rows.append(record)
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=dimensions + metrics)


def _fetch_summary(client, start_date, end_date):
    metrics = ["activeUsers", "sessions", "engagedSessions", "engagementRate",
               "averageSessionDuration", "eventCount", "bounceRate"]
    resp = _run_report(client, [], metrics, start_date, end_date, limit=1)
    if not resp.rows:
        return {m: 0 for m in metrics}
    row = resp.rows[0]
    return {m: float(row.metric_values[i].value) for i, m in enumerate(metrics)}


def _fetch_landing_pages(client, start_date, end_date):
    dims = ["landingPage"]
    mets = ["sessions", "activeUsers", "engagementRate", "averageSessionDuration", "eventCount"]
    return _response_to_df(_run_report(client, dims, mets, start_date, end_date, 25), dims, mets)


def _fetch_channels(client, start_date, end_date):
    dims = ["sessionDefaultChannelGroup"]
    mets = ["sessions", "activeUsers", "engagementRate", "bounceRate"]
    return _response_to_df(_run_report(client, dims, mets, start_date, end_date, 50), dims, mets)


def _fetch_devices(client, start_date, end_date):
    dims = ["deviceCategory"]
    mets = ["sessions", "activeUsers", "engagementRate"]
    return _response_to_df(_run_report(client, dims, mets, start_date, end_date, 10), dims, mets)


def _fetch_countries(client, start_date, end_date):
    dims = ["country"]
    mets = ["sessions", "activeUsers", "engagementRate"]
    return _response_to_df(_run_report(client, dims, mets, start_date, end_date, 50), dims, mets)


def _load_conversion_config(path: str = "tracked_conversions.csv") -> pd.DataFrame:
    """Load conversion event config. Returns empty DataFrame if file missing."""
    import os
    if not os.path.exists(path):
        print(f"  ⚠ tracked_conversions.csv not found at {path}. Conversion tracking disabled.")
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
        df["conversion_event"] = df["conversion_event"].astype(str).str.strip().str.lower()
        return df
    except Exception as e:
        print(f"  ⚠ Could not load tracked_conversions.csv: {e}")
        return pd.DataFrame()


def _fetch_conversions_by_event(client, start_date: str, end_date: str,
                                 event_names: list) -> pd.DataFrame:
    """
    Fetch event counts for configured conversion events.
    Uses eventName dimension + eventCount metric.
    Returns empty DataFrame if no events configured or API fails.
    """
    if not event_names:
        return pd.DataFrame()
    dims = ["eventName"]
    mets = ["eventCount", "sessions"]
    try:
        df = _response_to_df(
            _run_report(client, dims, mets, start_date, end_date, limit=500),
            dims, mets
        )
        if df.empty:
            return df
        df["eventName"] = df["eventName"].str.lower()
        df["eventCount"] = pd.to_numeric(df["eventCount"], errors="coerce").fillna(0)
        df["sessions"]   = pd.to_numeric(df["sessions"],   errors="coerce").fillna(0)
        # Filter to configured events only
        filtered = df[df["eventName"].isin([e.lower() for e in event_names])].copy()
        return filtered
    except Exception as e:
        print(f"  ⚠ Conversion event fetch failed: {e}")
        return pd.DataFrame()


def _fetch_conversions_by_page(client, start_date: str, end_date: str,
                                event_names: list) -> pd.DataFrame:
    """
    Fetch conversion events broken down by landing page.
    Returns top 50 pages by conversion count.
    """
    if not event_names:
        return pd.DataFrame()
    dims = ["landingPage", "eventName"]
    mets = ["eventCount", "sessions"]
    try:
        df = _response_to_df(
            _run_report(client, dims, mets, start_date, end_date, limit=1000),
            dims, mets
        )
        if df.empty:
            return df
        df["eventName"] = df["eventName"].str.lower()
        df["eventCount"] = pd.to_numeric(df["eventCount"], errors="coerce").fillna(0)
        df["sessions"]   = pd.to_numeric(df["sessions"],   errors="coerce").fillna(0)
        filtered = df[df["eventName"].isin([e.lower() for e in event_names])].copy()
        if filtered.empty:
            return filtered
        # Aggregate by page
        page_agg = (
            filtered.groupby("landingPage")
            .agg(total_conversions=("eventCount", "sum"), sessions=("sessions", "max"))
            .reset_index()
            .sort_values("total_conversions", ascending=False)
            .head(50)
        )
        return page_agg
    except Exception as e:
        print(f"  ⚠ Conversion by page fetch failed: {e}")
        return pd.DataFrame()


def _fetch_conversions_by_channel(client, start_date: str, end_date: str,
                                   event_names: list) -> pd.DataFrame:
    """Fetch conversion events broken down by channel group."""
    if not event_names:
        return pd.DataFrame()
    dims = ["sessionDefaultChannelGroup", "eventName"]
    mets = ["eventCount", "sessions"]
    try:
        df = _response_to_df(
            _run_report(client, dims, mets, start_date, end_date, limit=200),
            dims, mets
        )
        if df.empty:
            return df
        df["eventName"] = df["eventName"].str.lower()
        df["eventCount"] = pd.to_numeric(df["eventCount"], errors="coerce").fillna(0)
        df["sessions"]   = pd.to_numeric(df["sessions"],   errors="coerce").fillna(0)
        filtered = df[df["eventName"].isin([e.lower() for e in event_names])].copy()
        if filtered.empty:
            return filtered
        channel_agg = (
            filtered.groupby("sessionDefaultChannelGroup")
            .agg(total_conversions=("eventCount", "sum"), sessions=("sessions", "max"))
            .reset_index()
            .sort_values("total_conversions", ascending=False)
        )
        return channel_agg
    except Exception as e:
        print(f"  ⚠ Conversion by channel fetch failed: {e}")
        return pd.DataFrame()


def fetch_conversion_data(current_start: str, current_end: str,
                          previous_start: str, previous_end: str) -> dict:
    """
    Fetch all conversion data for current and previous periods.
    Returns a dict with keys: config, curr_events, prev_events, curr_pages, curr_channels.
    All values are DataFrames; empty DataFrames on failure.
    """
    config_df = _load_conversion_config()
    if config_df.empty:
        return {
            "config": config_df,
            "curr_events": pd.DataFrame(),
            "prev_events": pd.DataFrame(),
            "curr_pages":  pd.DataFrame(),
            "curr_channels": pd.DataFrame(),
            "warning": "No conversion events configured in tracked_conversions.csv",
        }

    event_names = config_df["conversion_event"].tolist()
    print(f"  Fetching conversions for {len(event_names)} configured events…", flush=True)

    def _run(fn, *args):
        c = get_ga4_client()
        return fn(c, *args)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    tasks = {
        "curr_events":   (_fetch_conversions_by_event,   current_start,  current_end,  event_names),
        "prev_events":   (_fetch_conversions_by_event,   previous_start, previous_end, event_names),
        "curr_pages":    (_fetch_conversions_by_page,    current_start,  current_end,  event_names),
        "curr_channels": (_fetch_conversions_by_channel, current_start,  current_end,  event_names),
    }
    results = {"config": config_df, "warning": None}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {executor.submit(_run, fn, *fn_args): key
                      for key, (fn, *fn_args) in tasks.items()}
        for future in as_completed(future_map):
            key = future_map[future]
            try:
                results[key] = future.result()
                count = len(results[key]) if not results[key].empty else 0
                print(f"  ✓ conversions/{key} ({count} rows)", flush=True)
            except Exception as e:
                print(f"  ✗ conversions/{key}: {e}", flush=True)
                results[key] = pd.DataFrame()

    # Compute summary
    curr_total = results["curr_events"]["eventCount"].sum() if not results["curr_events"].empty else 0
    prev_total = results["prev_events"]["eventCount"].sum() if not results["prev_events"].empty else 0
    results["curr_total"] = curr_total
    results["prev_total"] = prev_total
    return results


def build_conversion_summary(conv_data: dict) -> pd.DataFrame:
    """
    Build a summary DataFrame from conversion fetch results.
    Merges current and previous event counts with config metadata.
    """
    config_df   = conv_data.get("config", pd.DataFrame())
    curr_events = conv_data.get("curr_events", pd.DataFrame())
    prev_events = conv_data.get("prev_events", pd.DataFrame())

    if config_df.empty:
        return pd.DataFrame()

    summary_rows = []
    for _, cfg_row in config_df.iterrows():
        event = cfg_row["conversion_event"].lower()
        curr_count = 0.0
        prev_count = 0.0
        if not curr_events.empty and "eventName" in curr_events.columns:
            match = curr_events[curr_events["eventName"] == event]
            curr_count = float(match["eventCount"].sum()) if not match.empty else 0.0
        if not prev_events.empty and "eventName" in prev_events.columns:
            match = prev_events[prev_events["eventName"] == event]
            prev_count = float(match["eventCount"].sum()) if not match.empty else 0.0

        from seo_utils import safe_pct_change as _spc
        pct_chg = _spc(curr_count, prev_count)
        summary_rows.append({
            "conversion_event":    event,
            "display_name":        cfg_row.get("display_name", event),
            "category":            cfg_row.get("category", ""),
            "priority":            cfg_row.get("priority", "medium"),
            "business_value_proxy":cfg_row.get("business_value_proxy", 0),
            "current_count":       curr_count,
            "previous_count":      prev_count,
            "pct_change":          pct_chg,
            "configured":          True,
            "has_data":            curr_count > 0 or prev_count > 0,
        })

    return pd.DataFrame(summary_rows)


def _fetch_daily_trend(client, start_date, end_date):
    dims = ["date"]
    mets = ["sessions", "activeUsers", "engagedSessions"]
    df = _response_to_df(_run_report(client, dims, mets, start_date, end_date, 7), dims, mets)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        for m in mets[1:]:
            df[m] = pd.to_numeric(df[m], errors="coerce").fillna(0)
        df["sessions"] = pd.to_numeric(df["sessions"], errors="coerce").fillna(0)
        df = df.sort_values("date")
    return df


def fetch_all_data_parallel(current_start, current_end, previous_start, previous_end):
    """Run all GA4 API calls in parallel — each thread gets its own client."""
    def _run(fn, *args):
        c = get_ga4_client()
        return fn(c, *args)

    tasks = {
        "curr_summary":  (_fetch_summary,       current_start,  current_end),
        "prev_summary":  (_fetch_summary,       previous_start, previous_end),
        "curr_pages":    (_fetch_landing_pages, current_start,  current_end),
        "prev_pages":    (_fetch_landing_pages, previous_start, previous_end),
        "curr_channels": (_fetch_channels,      current_start,  current_end),
        "prev_channels": (_fetch_channels,      previous_start, previous_end),
        "curr_devices":  (_fetch_devices,       current_start,  current_end),
        "curr_countries":(_fetch_countries,     current_start,  current_end),
        "curr_trend":    (_fetch_daily_trend,   current_start,  current_end),
        "prev_trend":    (_fetch_daily_trend,   previous_start, previous_end),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {
            executor.submit(_run, fn, *fn_args): key
            for key, (fn, *fn_args) in tasks.items()
        }
        for future in as_completed(future_map):
            key = future_map[future]
            try:
                results[key] = future.result()
                print(f"  ✓ {key}")
            except Exception as e:
                print(f"  ✗ {key}: {e}")
                results[key] = pd.DataFrame() if key not in ("curr_summary", "prev_summary") else {}
    return results


# ══════════════════════════════════════════════════════════════════════════════
# DATA PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

def prepare_summary_comparison(current_summary, previous_summary):
    rows = []
    for metric in current_summary.keys():
        curr = float(current_summary.get(metric, 0))
        prev = float(previous_summary.get(metric, 0))
        rows.append({"metric": metric, "current": curr, "previous": prev,
                     "change": curr - prev})
    return pd.DataFrame(rows)


def prepare_pages_comparison(curr_df, prev_df):
    """Merge current and previous landing page data with WoW deltas."""
    if curr_df.empty:
        return curr_df
    for df in [curr_df, prev_df]:
        for col in ["sessions", "activeUsers", "engagementRate", "averageSessionDuration", "eventCount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    curr = curr_df.rename(columns={c: f"{c}_current" for c in
                                    ["sessions", "activeUsers", "engagementRate",
                                     "averageSessionDuration", "eventCount"]})
    prev = prev_df.rename(columns={c: f"{c}_previous" for c in
                                    ["sessions", "activeUsers", "engagementRate",
                                     "averageSessionDuration", "eventCount"]})
    merged = pd.merge(curr, prev, on="landingPage", how="outer").fillna(0)
    merged["sessions_change"] = merged["sessions_current"] - merged["sessions_previous"]
    return merged.sort_values("sessions_current", ascending=False)


def calculate_kpis(curr_summary, prev_summary):
    def _f(key):
        return float(curr_summary.get(key, 0)), float(prev_summary.get(key, 0))

    sessions_c, sessions_p = _f("sessions")
    users_c, users_p       = _f("activeUsers")
    eng_c, eng_p           = _f("engagementRate")
    dur_c, dur_p           = _f("averageSessionDuration")
    bounce_c, bounce_p     = _f("bounceRate")
    return {
        "sessions":        {"curr": sessions_c, "prev": sessions_p},
        "users":           {"curr": users_c,    "prev": users_p},
        "engagement_rate": {"curr": eng_c,      "prev": eng_p},
        "avg_duration":    {"curr": dur_c,       "prev": dur_p},
        "bounce_rate":     {"curr": bounce_c,    "prev": bounce_p},
    }


def _fmt(val, decimals=0, pct=False):
    try:
        v = float(val)
        if math.isnan(v) or v == 0:
            return "-"
        if pct:
            return f"{v:.2%}"
        if decimals == 0:
            return f"{v:,.0f}"
        return f"{v:,.{min(decimals, 2)}f}"
    except (TypeError, ValueError):
        s = str(val)
        return s[:57] + "..." if len(s) > 60 else s


def build_all_charts(*args, **kwargs):
    """Legacy helper (now using direct data injection into HTML)."""
    return {}


# ══════════════════════════════════════════════════════════════════════════════
# AI ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def build_deterministic_bullets(kpis, pages_df, channels_df):
    """Hard metric facts — always present even if AI fails."""
    bullets = []
    s_c, s_p = kpis["sessions"]["curr"], kpis["sessions"]["prev"]
    u_c, u_p = kpis["users"]["curr"], kpis["users"]["prev"]
    e_c, e_p = kpis["engagement_rate"]["curr"], kpis["engagement_rate"]["prev"]
    d_c, d_p = kpis["avg_duration"]["curr"], kpis["avg_duration"]["prev"]

    from seo_utils import safe_pct_change
    pct_s = safe_pct_change(s_c, s_p)
    direction = "up" if s_c > s_p else ("down" if s_c < s_p else "flat")
    pct_str = f" ({pct_s:+.1%})" if pct_s is not None else ""
    bullets.append(f"Sessions are {direction} week over week: {s_c:,.0f} vs {s_p:,.0f}{pct_str}.")

    pct_u = safe_pct_change(u_c, u_p)
    direction_u = "up" if u_c > u_p else ("down" if u_c < u_p else "flat")
    pct_u_str = f" ({pct_u:+.1%})" if pct_u is not None else ""
    bullets.append(f"Active users are {direction_u}: {u_c:,.0f} vs {u_p:,.0f}{pct_u_str}.")

    if e_c > e_p:
        bullets.append(f"Engagement rate improved to {e_c:.2%} (from {e_p:.2%}).")
    elif e_c < e_p:
        bullets.append(f"Engagement rate declined to {e_c:.2%} (from {e_p:.2%}).")
    else:
        bullets.append(f"Engagement rate was flat at {e_c:.2%}.")

    if not channels_df.empty:
        channels_df = channels_df.copy()
        channels_df["sessions"] = channels_df["sessions"].apply(lambda x: float(x) if x else 0)
        top_ch = channels_df.nlargest(1, "sessions")
        if not top_ch.empty:
            ch_name = top_ch.iloc[0]["sessionDefaultChannelGroup"]
            ch_sess = top_ch.iloc[0]["sessions"]
            total   = channels_df["sessions"].sum()
            share   = ch_sess / total * 100 if total > 0 else 0
            bullets.append(f"{ch_name} is the top channel with {ch_sess:,.0f} sessions ({share:.0f}% of total).")

    if not pages_df.empty and "sessions_change" in pages_df.columns:
        gainers = int((pages_df["sessions_change"] > 0).sum())
        losers  = int((pages_df["sessions_change"] < 0).sum())
        if gainers > losers:
            bullets.append(f"{gainers} landing pages gained sessions WoW vs {losers} that declined.")
        elif losers > gainers:
            bullets.append(f"{losers} landing pages lost sessions WoW vs {gainers} that gained.")

    return bullets


def build_ai_bullets(kpis, pages_df, channels_df, current_start, current_end,
                     previous_start, previous_end):
    if not GROQ_API_KEY:
        return []
    top_pages = pages_df.head(10) if not pages_df.empty else pd.DataFrame()
    top_ch    = channels_df.head(8) if not channels_df.empty else pd.DataFrame()
    prompt = f"""You are writing a concise executive GA4 weekly brief for SEO stakeholders.

Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.
Each bullet is one sentence. Maximum 8 bullets total.
Cover: traffic trends, channel mix, engagement quality, landing page performance, risks, actions.
Do not repeat raw numbers already obvious from the data. Professional corporate tone. Under 200 words.
Do not invent data.

Current period: {current_start} to {current_end}
Previous period: {previous_start} to {previous_end}

Overall metrics:
- Sessions: {kpis["sessions"]["curr"]:,.0f} vs {kpis["sessions"]["prev"]:,.0f}
- Active Users: {kpis["users"]["curr"]:,.0f} vs {kpis["users"]["prev"]:,.0f}
- Engagement Rate: {kpis["engagement_rate"]["curr"]:.2%} vs {kpis["engagement_rate"]["prev"]:.2%}
- Avg Duration: {kpis["avg_duration"]["curr"]:.0f}s vs {kpis["avg_duration"]["prev"]:.0f}s
- Bounce Rate: {kpis["bounce_rate"]["curr"]:.2%} vs {kpis["bounce_rate"]["prev"]:.2%}

Top channels:
{top_ch.to_csv(index=False) if not top_ch.empty else "No data"}

Top landing pages:
{top_pages.to_csv(index=False) if not top_pages.empty else "No data"}
"""
    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write polished weekly executive GA4 briefs as bullet points only."},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.2,
        )
        raw = resp.choices[0].message.content.strip()
        bullets = []
        for line in raw.splitlines():
            clean = line.strip().lstrip("-*+•·▪▸").replace("**","").replace("__","").replace("*","").strip()
            if clean:
                bullets.append(clean)
        return bullets
    except Exception as e:
        print(f"  AI analysis failed: {e}", flush=True)
        return []


def build_unified_bullets(kpis, pages_df, channels_df, current_start, current_end,
                          previous_start, previous_end):
    det = build_deterministic_bullets(kpis, pages_df, channels_df)
    ai  = build_ai_bullets(kpis, pages_df, channels_df, current_start, current_end,
                           previous_start, previous_end)
    return det + ai


# ══════════════════════════════════════════════════════════════════════════════
# HTML TABLE BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def _delta_html(val, decimals=0, lower_is_better=False):
    """Return a coloured delta span (monochrome border style)."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "-"
    if math.isclose(v, 0, abs_tol=1e-5):
        return '<span class="chg neu">—</span>'
    positive_good = (v > 0 and not lower_is_better) or (v < 0 and lower_is_better)
    cls  = "pos" if positive_good else "neg"
    sign = "+" if v > 0 else ""
    return f'<span class="chg {cls}">{sign}{v:.{decimals}f}</span>'


def _bar_cell(value, max_value, color=C_NAVY):
    """Return a table cell containing an inline proportional bar."""
    if max_value <= 0:
        return f"<td>{_fmt(value)}</td>"
    pct = min(value / max_value * 100, 100)
    return (
        f'<td><div style="display:flex;align-items:center;gap:6px;">'
        f'<div style="width:{pct:.1f}%;max-width:80px;height:8px;'
        f'background:{color};border-radius:3px;flex-shrink:0;"></div>'
        f'<span style="font-size:9px;color:#374151;">{_fmt(value)}</span>'
        f"</div></td>"
    )

def build_pages_table(pages_df, n=50):
    if pages_df.empty:
        return "<p style=\"font-family:'JetBrains Mono',monospace;font-size:10px;color:#94A3B8;\">No data.</p>"
    work = pages_df.head(n).copy()
    max_s = work["sessions_current"].max() if "sessions_current" in work.columns else 1
    headers = ["#", "Landing Page", "Sessions", "Users", "Eng Rate", "Avg Dur", "WoW"]
    th = "".join(f"<th>{h}</th>" for h in headers)
    rows_html = []
    for i, (_, row) in enumerate(work.iterrows(), 1):
        page  = html.escape(short_url(str(row.get("landingPage", "")), 45))
        sess  = row.get("sessions_current", row.get("sessions", 0))
        users = row.get("activeUsers_current", row.get("activeUsers", 0))
        eng   = row.get("engagementRate_current", row.get("engagementRate", 0))
        dur   = row.get("averageSessionDuration_current", row.get("averageSessionDuration", 0))
        chg   = row.get("sessions_change", 0)
        sess_bar = _bar_cell(float(sess), float(max_s), C_NAVY)
        rows_html.append(
            f"<tr>"
            f"<td style=\"color:#94A3B8;font-size:9px;width:18px;\">{i}</td>"
            f"<td class=\"url-cell\">{page}</td>"
            f"{sess_bar}"
            f"<td style=\"white-space:nowrap;\">{_fmt(users)}</td>"
            f"<td style=\"white-space:nowrap;\">{_fmt(float(eng), pct=True)}</td>"
            f"<td style=\"white-space:nowrap;\">{_fmt(float(dur), decimals=0)}s</td>"
            f"<td style=\"white-space:nowrap;\">{_delta_html(chg)}</td>"
            f"</tr>"
        )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"


def build_channels_table(channels_df):
    if channels_df.empty:
        return "<p style=\"font-family:'JetBrains Mono',monospace;font-size:10px;color:#94A3B8;\">No data.</p>"
    channels_df = channels_df.copy()
    for col in ["sessions", "activeUsers", "engagementRate", "bounceRate"]:
        if col in channels_df.columns:
            channels_df[col] = pd.to_numeric(channels_df[col], errors="coerce").fillna(0)
    max_s = channels_df["sessions"].max()
    headers = ["Channel", "Sessions", "Users", "Eng Rate", "Bounce Rate"]
    th = "".join(f"<th>{h}</th>" for h in headers)
    rows_html = []
    for _, row in channels_df.iterrows():
        ch = html.escape(str(row.get("sessionDefaultChannelGroup", "")))
        rows_html.append(
            f"<tr>"
            f"<td class=\"url-cell\">{ch}</td>"
            f"{_bar_cell(row.get('sessions', 0), max_s, C_NAVY)}"
            f"<td style=\"white-space:nowrap;\">{_fmt(row.get('activeUsers', 0))}</td>"
            f"<td style=\"white-space:nowrap;\">{_fmt(row.get('engagementRate', 0), pct=True)}</td>"
            f"<td style=\"white-space:nowrap;\">{_fmt(row.get('bounceRate', 0), pct=True)}</td>"
            f"</tr>"
        )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(rows_html)}</tbody></table>"


# ══════════════════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════════════════

def get_extra_css():
    return """
    body::before {
        content: \'\';
        position: fixed;
        inset: 0;
        background-image: url("data:image/svg+xml,%3Csvg viewBox=\'0 0 256 256\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'noise\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.8\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100%25\' height=\'100%25\' filter=\'url(%23noise)\'/%3E%3C/svg%3E");
        opacity: 0.018;
        pointer-events: none;
        z-index: 9999;
    }
    .exec-panel { border: none; padding: 0; margin: 0; background: transparent; }
    .panel-label { font-family: \'JetBrains Mono\', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.15em; color: #525252; margin-bottom: 16px; display: flex; align-items: center; gap: 12px; }
    .panel-label::after { content: \'\'; flex: 1; height: 1px; background: #E5E5E5; }
    .exec-bullets { margin: 0; padding: 0; list-style: none; }
    .exec-bullets li { font-family: \'Source Serif 4\', Georgia, serif; font-size: 14px; color: #000; line-height: 1.7; padding: 10px 0 10px 20px; border-bottom: 1px solid #E5E5E5; position: relative; }
    .exec-bullets li::before { content: \'—\'; position: absolute; left: 0; color: #525252; font-family: \'JetBrains Mono\', monospace; }
    .exec-bullets li:last-child { border-bottom: none; }
    .chg { font-family: \'JetBrains Mono\', monospace; font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 0; display: inline-block; border: 1px solid #000; }
    .chg.pos { background: #000; color: #fff; }
    .chg.neg { background: #fff; color: #000; }
    .chg.neu { background: #fff; color: #525252; border-color: #E5E5E5; }
    .chart-wrap { width: 100%; margin-bottom: 24px; }
    .chart-wrap img { width: 100%; display: block; border: 2px solid #000; border-radius: 0; }
    .chart-row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
    .chart-row-2 img { width: 100%; display: block; border: 2px solid #000; border-radius: 0; }
    .col-header { font-family: \'Playfair Display\', Georgia, serif; font-size: 13px; font-weight: 700; color: #000; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 28px; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 2px solid #000; }
    .col-header:first-child { margin-top: 0; }
    table { font-family: \'JetBrains Mono\', monospace; font-size: 10px; width: 100%; border-collapse: collapse; }
    th { font-family: \'JetBrains Mono\', monospace; font-size: 8px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em; padding: 10px 12px; text-align: left; background: #000; color: #fff; border: none; }
    td { padding: 9px 12px; border-bottom: 1px solid #E5E5E5; color: #000; }
    td.url-cell { max-width: 220px; overflow-wrap: break-word; word-break: break-word; font-family: \'Source Serif 4\', Georgia, serif; font-size: 11px; }
    tr:hover td { background: #F5F5F5; }
    """


# ══════════════════════════════════════════════════════════════════════════════
# HTML REPORT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _img_tag(path, alt="chart"):
    if not path:
        return ""
    return f'<img src="{html.escape(str(path))}" alt="{html.escape(alt)}" style="width:100%;display:block;border:2px solid #000;">'

def _chart_wrap(path, alt="chart"):
    if not path:
        return ""
    return f'<div class="chart-wrap">{_img_tag(path, alt)}</div>'

def _chart_row_2(path_a, alt_a, path_b, alt_b):
    a = _img_tag(path_a, alt_a) if path_a else ""
    b = _img_tag(path_b, alt_b) if path_b else ""
    if not a and not b:
        return ""
    return f'<div class="chart-row-2"><div>{a}</div><div>{b}</div></div>'

def embed_images_as_base64(html_content):
    import re as _re, base64 as _b64
    from pathlib import Path as _Path
    def replace_src(match):
        src = match.group(1)
        img_path = _Path(src)
        if img_path.exists():
            ext  = img_path.suffix.lstrip(".").lower()
            mime = "image/png" if ext == "png" else f"image/{ext}"
            b64  = _b64.b64encode(img_path.read_bytes()).decode()
            return f'src="data:{mime};base64,{b64}"'
        return match.group(0)
    return _re.sub(r'src="([^"]+\.(png|jpg|jpeg|svg|gif))"', replace_src, html_content)

def _kpi_card(label, curr_val, prev_val=None, lower_better=False):
    curr_str = f"{curr_val:,.0f}" if isinstance(curr_val, (int, float)) else str(curr_val)
    if prev_val is not None:
        delta_str = format_pct_change(curr_val, prev_val)
        prev_str  = f"{prev_val:,.0f}" if isinstance(prev_val, (int, float)) else str(prev_val)
    else:
        delta_str, prev_str = "-", "—"
    if delta_str == "-":
        delta_html_str = '<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">—</span>'
    else:
        is_pos = delta_str.startswith("+")
        good   = (is_pos and not lower_better) or (not is_pos and lower_better)
        d_bg, d_color = ("#000", "#fff") if good else ("#fff", "#000")
        delta_html_str = (
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;font-weight:700;'
            f'padding:2px 8px;background:{d_bg};color:{d_color};border:1px solid #000;">'
            f'{delta_str}</span>'
        )
    return f"""
<div style="background:#000;color:#fff;padding:24px 20px;border:2px solid #000;position:relative;overflow:hidden;">
  <div style="position:absolute;inset:0;background-image:repeating-linear-gradient(90deg,transparent,transparent 1px,#fff 1px,#fff 2px);background-size:4px 100%;opacity:0.03;pointer-events:none;"></div>
  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.15em;color:#999;margin-bottom:12px;">{html.escape(label)}</div>
  <div style="font-family:'Playfair Display',Georgia,serif;font-size:36px;font-weight:700;color:#fff;line-height:1;margin-bottom:10px;">{html.escape(curr_str)}</div>
  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#999;margin-bottom:8px;">prev {html.escape(prev_str)}</div>
  {delta_html_str}
</div>"""

def write_html_summary(kpis, exec_bullets, chart_paths, pages_df, channels_df,
                       device_df, country_df, current_start, current_end,
                       previous_start, previous_end, trend_curr, trend_prev):
    """Build the final GA4 report with ApexCharts integration."""
    today = date.today().strftime("%B %d, %Y")

    # 1. KPI Grid
    kpi_cards = (
        mm_kpi_card("Sessions",        kpis["sessions"]["curr"],        kpis["sessions"]["prev"]) +
        mm_kpi_card("Active Users",    kpis["users"]["curr"],           kpis["users"]["prev"]) +
        mm_kpi_card("Engagement Rate", kpis["engagement_rate"]["curr"], kpis["engagement_rate"]["prev"], is_pct=True) +
        mm_kpi_card("Avg Duration",    kpis["avg_duration"]["curr"],    kpis["avg_duration"]["prev"]) +
        mm_kpi_card("Bounce Rate",     kpis["bounce_rate"]["curr"],     kpis["bounce_rate"]["prev"], lower_better=True, is_pct=True)
    )
    kpi_grid = mm_kpi_grid(kpi_cards)

    # 2. Charts (ApexCharts)
    
    # 7-Day Trend (Area)
    trend_chart = ""
    if not trend_curr.empty:
        trend_chart = mm_apex_chart("ga4_trend", {
            "chart": {"type": "area", "height": 350, "zoom": {"enabled": False}},
            "series": [
                {"name": "Current Sessions", "data": [float(x) for x in trend_curr["sessions"].tolist()]},
                {"name": "Previous Sessions", "data": [float(x) for x in trend_prev["sessions"].tolist()] if not trend_prev.empty else []}
            ],
            "xaxis": {"categories": [d.strftime("%a %d") for d in trend_curr["date"]]},
            "title": {"text": "7-Day Traffic Trend"},
            "colors": ["#212878", "#94A3B8"],
            "stroke": {"curve": "smooth", "width": [3, 2]}
        })

    # Channel Mix (Donut)
    channel_chart = ""
    if not channels_df.empty:
        top_channels = channels_df.head(12)
        channel_chart = mm_apex_chart("channel_mix", {
            "chart": {"type": "donut", "height": 380},
            "series": [float(x) for x in top_channels["sessions"].tolist()],
            "labels": top_channels["sessionDefaultChannelGroup"].tolist(),
            "title": {"text": "Traffic Source Mix"},
            "legend": {"position": "bottom"}
        })

    # Page Movers (Horizontal Bar)
    movers_chart = ""
    if not pages_df.empty and "sessions_change" in pages_df.columns:
        movers = pd.concat([
            pages_df.nsmallest(25, "sessions_change"),
            pages_df.nlargest(25, "sessions_change")
        ]).sort_values("sessions_change")
        movers_chart = mm_apex_chart("page_movers", {
            "chart": {"type": "bar", "height": 400},
            "series": [{"name": "Session Change", "data": [float(x) for x in movers["sessions_change"].tolist()]}],
            "xaxis": {"categories": movers["landingPage"].apply(lambda x: short_url(str(x), 35)).tolist()},
            "plotOptions": {"bar": {"horizontal": True, "colors": {"ranges": [{"from": -9999, "to": -0.1, "color": "#E76F51"}, {"from": 0.1, "to": 9999, "color": "#2A9D8F"}]}}},
            "title": {"text": "Top WoW Page Movers (Session Δ)"}
        })

    # 3. Tables
    pages_tbl    = build_pages_table(pages_df)
    channels_tbl = build_channels_table(channels_df)

    # 4. Assemble
    body_content = (
        mm_section("Executive Summary", 
            mm_report_section(mm_exec_bullets(exec_bullets))
        ) +
        '<div class="section" style="padding-top:0;">' + kpi_grid + '</div>'
        '<hr class="rule-thick">' +
        mm_section("Performance Deep-Dive",
            mm_report_section(
                '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#64748B;margin-bottom:16px;">\u24d8 <b>How to read:</b> Compares this week against the previous. Hover over data points for specific numbers. High density peaks indicate successful campaign launches or organic spikes.</p>' +
                trend_chart + "<br>" + channel_chart
            )
        ) +
        mm_section("Content Strategy: Movers & Shakers",
            mm_report_section(
                '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#64748B;margin-bottom:16px;">\u24d8 <b>How to read:</b> Green bars are pages growing in traffic. Red bars show declining sessions. Focus optimizations on high-value pages in the red.</p>' +
                movers_chart + "<br>" + mm_col_header("Top Landing Pages Detailed") + pages_tbl
            )
        ) +
        mm_section("Acquisition Breakdown",
            mm_report_section(channels_tbl)
        )
    )

    doc = mm_html_shell(
        title=f"GA4 Weekly Report — {today}",
        eyebrow="Google Analytics 4 Intelligence",
        headline="Weekly Performance\nReport",
        meta_line=f"{current_start} &rarr; {current_end} / prev {previous_start} &rarr; {previous_end}",
        body_content=body_content
    )

    with open("ga4_weekly_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("  Saved ga4_weekly_summary.html with ApexCharts", flush=True)


def generate_self_contained():
    raw   = Path("ga4_weekly_summary.html").read_text(encoding="utf-8")
    final = embed_images_as_base64(raw)
    Path("ga4_weekly_summary_final.html").write_text(final, encoding="utf-8")
    size_kb = len(final.encode()) // 1024
    print(f"  Saved ga4_weekly_summary_final.html ({size_kb} KB, self-contained)", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# MONDAY UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_monday():
    api_token = MONDAY_API_TOKEN
    item_id   = MONDAY_ITEM_ID
    if not api_token or not item_id:
        print("  Monday upload skipped: credentials not configured.", flush=True)
        return
    body_text = ("GA4 Weekly Performance Report attached as a self-contained HTML file. "
                 "Open in any browser — all charts are embedded inline.")
    update_query = """
    mutation ($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) { id }
    }
    """
    resp = requests.post(
        MONDAY_API_URL,
        headers={"Authorization": api_token, "Content-Type": "application/json"},
        json={"query": update_query, "variables": {"item_id": str(item_id), "body": body_text}},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday update failed: {data['errors']}")
    update_id = data["data"]["create_update"]["id"]
    file_query = """
    mutation ($update_id: ID!, $file: File!) {
      add_file_to_update(update_id: $update_id, file: $file) { id }
    }
    """
    html_path = Path("ga4_weekly_summary_final.html")
    if not html_path.exists():
        print("  Monday file attach skipped: file not found.", flush=True)
        return
    with open(html_path, "rb") as f:
        file_resp = requests.post(
            MONDAY_FILE_API_URL,
            headers={"Authorization": api_token},
            data={
                "query": file_query,
                "variables": '{"update_id": "' + str(update_id) + '", "file": null}',
                "map": '{"file": ["variables.file"]}',
            },
            files={"file": ("ga4-weekly-report.html", f, "text/html")},
            timeout=120,
        )
    file_resp.raise_for_status()
    file_data = file_resp.json()
    if "errors" in file_data:
        raise RuntimeError(f"Monday file attach failed: {file_data['errors']}")
    print("  Uploaded ga4-weekly-report.html to Monday.com successfully.", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("GA4 Weekly Report — starting", flush=True)
    current_start, current_end, previous_start, previous_end = get_weekly_date_windows()
    print(f"Current:  {current_start} -> {current_end}")
    print(f"Previous: {previous_start} -> {previous_end}")

    print("Fetching GA4 data (parallel)...")
    raw = fetch_all_data_parallel(
        current_start.isoformat(), current_end.isoformat(),
        previous_start.isoformat(), previous_end.isoformat()
    )

    curr_summary  = raw.get("curr_summary",  {})
    prev_summary  = raw.get("prev_summary",  {})
    curr_pages    = raw.get("curr_pages",    pd.DataFrame())
    prev_pages    = raw.get("prev_pages",    pd.DataFrame())
    curr_channels = raw.get("curr_channels", pd.DataFrame())
    prev_channels = raw.get("prev_channels", pd.DataFrame())
    curr_devices  = raw.get("curr_devices",  pd.DataFrame())
    curr_countries= raw.get("curr_countries",pd.DataFrame())
    trend_curr    = raw.get("curr_trend",    pd.DataFrame())
    trend_prev    = raw.get("prev_trend",    pd.DataFrame())

    summary_df    = prepare_summary_comparison(curr_summary, prev_summary)
    pages_df      = prepare_pages_comparison(curr_pages, prev_pages)
    kpis          = calculate_kpis(curr_summary, prev_summary)

    # Conversion data
    print("Fetching conversion data...")
    conv_data = fetch_conversion_data(
        current_start.isoformat(), current_end.isoformat(),
        previous_start.isoformat(), previous_end.isoformat()
    )
    conv_summary_df = build_conversion_summary(conv_data)
    conv_pages_df   = conv_data.get("curr_pages",    pd.DataFrame())
    conv_channels_df= conv_data.get("curr_channels", pd.DataFrame())

    # Save conversion CSVs
    conv_summary_df.to_csv("ga4_conversion_summary.csv", index=False)
    conv_pages_df.to_csv("ga4_conversion_pages.csv", index=False)
    conv_channels_df.to_csv("ga4_conversion_channels.csv", index=False)
    if not conv_data.get("curr_events", pd.DataFrame()).empty:
        conv_data["curr_events"].to_csv("ga4_conversions_current.csv", index=False)
    if not conv_data.get("prev_events", pd.DataFrame()).empty:
        conv_data["prev_events"].to_csv("ga4_conversions_previous.csv", index=False)

    # Append conversion summary to Google Sheets
    if not conv_summary_df.empty:
        append_to_sheet(conv_summary_df, "GA4_Conversions")

    if conv_data.get("warning"):
        print(f"  ⚠ Conversion warning: {conv_data['warning']}", flush=True)
    else:
        curr_total = conv_data.get("curr_total", 0)
        prev_total = conv_data.get("prev_total", 0)
        print(f"  Conversions: {curr_total:,.0f} (curr) vs {prev_total:,.0f} (prev)", flush=True)

    # Save CSVs
    summary_df.to_csv("ga4_summary_comparison.csv", index=False)
    curr_pages.to_csv("ga4_top_landing_pages.csv", index=False)
    pages_df.to_csv("ga4_pages_comparison.csv", index=False)
    curr_channels.to_csv("ga4_top_channels.csv", index=False)
    curr_devices.to_csv("ga4_device_split.csv", index=False)
    curr_countries.to_csv("ga4_country_split.csv", index=False)

    # Google Sheets
    append_to_sheet(summary_df,    "GA4_Summary")
    append_to_sheet(pages_df,      "GA4_Top_Pages")
    append_to_sheet(curr_channels, "GA4_Top_Channels")
    append_to_sheet(curr_devices,  "GA4_Device_Split")
    append_to_sheet(curr_countries,"GA4_Country_Split")

    # Charts
    print("Generating charts...")
    chart_paths = build_all_charts(kpis, trend_curr, trend_prev,
                                   curr_channels, prev_channels,
                                   curr_devices, pages_df)

    # Executive bullets
    print("Building executive summary...")
    exec_bullets = build_unified_bullets(
        kpis, pages_df, curr_channels,
        current_start, current_end, previous_start, previous_end
    )

    # HTML report (Now passing trend data directly)
    write_html_summary(kpis, exec_bullets, chart_paths, pages_df, curr_channels,
                       curr_devices, curr_countries,
                       current_start, current_end, previous_start, previous_end,
                       trend_curr, trend_prev)
    generate_self_contained()

    try:
        upload_to_monday()
    except Exception as e:
        print(f"  Monday upload failed: {e}", flush=True)

    print("GA4 Weekly Report — complete", flush=True)


if __name__ == "__main__":
    main()
