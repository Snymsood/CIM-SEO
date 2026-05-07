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
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

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
    return _response_to_df(_run_report(client, dims, mets, start_date, end_date, 15), dims, mets)


def _fetch_devices(client, start_date, end_date):
    dims = ["deviceCategory"]
    mets = ["sessions", "activeUsers", "engagementRate"]
    return _response_to_df(_run_report(client, dims, mets, start_date, end_date, 10), dims, mets)


def _fetch_countries(client, start_date, end_date):
    dims = ["country"]
    mets = ["sessions", "activeUsers", "engagementRate"]
    return _response_to_df(_run_report(client, dims, mets, start_date, end_date, 15), dims, mets)


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


def _delta_html(val, decimals=0, lower_is_better=False):
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "-"
    if math.isclose(v, 0, abs_tol=0.05):  # treat |Δ| < 0.05 as zero (avoids "+0" / "-0")
        return '<span class="chg neu">—</span>'
    positive_good = (v > 0 and not lower_is_better) or (v < 0 and lower_is_better)
    cls  = "pos" if positive_good else "neg"
    sign = "+" if v > 0 else ""
    return f'<span class="chg {cls}">{sign}{v:.{decimals}f}</span>'


def _bar_cell(value, max_value, color=C_NAVY):
    if max_value <= 0:
        return f"<td>{_fmt(value)}</td>"
    pct = min(value / max_value * 100, 100)
    return (
        f'<td><div style="display:flex;align-items:center;gap:6px;">'
        f'<div style="width:{pct:.1f}%;max-width:80px;height:8px;'
        f'background:{color};border-radius:0;flex-shrink:0;"></div>'
        f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:9px;color:#374151;">'
        f'{_fmt(value)}</span></div></td>'
    )




# ══════════════════════════════════════════════════════════════════════════════
# CHART GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _style_ax(ax, title="", xlabel="", ylabel=""):
    ax.set_title(title, fontsize=10, fontweight="600", color="#1A1A1A", pad=8, loc="left")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=8, color="#64748B", labelpad=4)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=8, color="#64748B", labelpad=4)
    ax.tick_params(labelsize=8, colors="#64748B", length=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(C_BORDER)
    ax.spines["bottom"].set_color(C_BORDER)
    ax.set_facecolor("#FAFAFA")


def _save(fig, filename):
    CHARTS_DIR.mkdir(exist_ok=True)
    path = CHARTS_DIR / filename
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _placeholder(filename):
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    ax.text(0.5, 0.5, "No data available for this period.",
            ha="center", va="center", fontsize=12, color="#94A3B8",
            transform=ax.transAxes)
    ax.set_axis_off()
    return _save(fig, filename)


def plot_kpi_bars(kpis):
    """Paired bar: current vs previous for 4 KPIs."""
    panels = [
        ("Sessions",        kpis["sessions"]["curr"],        kpis["sessions"]["prev"],        False),
        ("Active Users",    kpis["users"]["curr"],           kpis["users"]["prev"],           False),
        ("Engagement Rate", kpis["engagement_rate"]["curr"], kpis["engagement_rate"]["prev"], True),
        ("Avg Duration (s)",kpis["avg_duration"]["curr"],    kpis["avg_duration"]["prev"],    False),
    ]
    fig, axes = plt.subplots(1, 4, figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    for ax, (label, curr, prev, is_pct) in zip(axes, panels):
        good_color = C_NAVY if curr >= prev else C_CORAL
        bars = ax.bar(["Prev", "Curr"], [prev, curr], color=[C_SLATE, good_color], width=0.45, zorder=2)
        for bar, v in zip(bars, [prev, curr]):
            label_str = f"{v:.1%}" if is_pct else f"{v:,.0f}"
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.03,
                    label_str, ha="center", va="bottom", fontsize=9, color="#374151", fontweight="600")
        _style_ax(ax, title=label)
        ax.grid(axis="y", linestyle="--", alpha=0.35, color=C_BORDER, zorder=1)
        ax.set_ylim(0, max(curr, prev) * 1.30 if max(curr, prev) > 0 else 1)
    fig.tight_layout(pad=2.0)
    return _save(fig, "ga4_kpi_bars.png")


def plot_trend(trend_curr, trend_prev):
    """7-day sessions trend with previous period overlay."""
    if trend_curr.empty:
        return _placeholder("ga4_trend.png")
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    x = range(len(trend_curr))
    day_labels = [d.strftime("%a %d") for d in trend_curr["date"]]
    ax.plot(list(x), trend_curr["sessions"].tolist(), color=C_NAVY, linewidth=2,
            marker="o", markersize=4, label="Sessions (curr)", zorder=3)
    if not trend_prev.empty and len(trend_prev) == len(trend_curr):
        ax.plot(list(x), trend_prev["sessions"].tolist(), color=C_NAVY, linewidth=1.2,
                linestyle="--", alpha=0.45, marker="o", markersize=3,
                label="Sessions (prev)", zorder=2)
    ax.fill_between(list(x), trend_curr["sessions"].tolist(), alpha=0.08, color=C_NAVY)
    ax2 = ax.twinx()
    ax2.plot(list(x), trend_curr["engagedSessions"].tolist(), color=C_TEAL, linewidth=2,
             marker="s", markersize=4, label="Engaged (curr)", zorder=3)
    ax.set_xticks(list(x))
    ax.set_xticklabels(day_labels, fontsize=8, color="#64748B")
    ax.tick_params(axis="y", labelsize=8, colors=C_NAVY, length=0)
    ax2.tick_params(axis="y", labelsize=8, colors=C_TEAL, length=0)
    ax.set_ylabel("Sessions", fontsize=8, color=C_NAVY)
    ax2.set_ylabel("Engaged Sessions", fontsize=8, color=C_TEAL)
    ax.set_facecolor("#FAFAFA")
    for spine in ["top"]:
        ax.spines[spine].set_visible(False)
        ax2.spines[spine].set_visible(False)
    ax.spines["left"].set_color(C_BORDER)
    ax.spines["bottom"].set_color(C_BORDER)
    ax2.spines["right"].set_color(C_BORDER)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER)
    ax.set_title("7-Day Daily Trend — Sessions & Engaged Sessions", fontsize=10,
                 fontweight="600", color="#1A1A1A", pad=8, loc="left")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=7.5, frameon=False,
              loc="upper right", ncol=3)
    fig.tight_layout(pad=1.5)
    return _save(fig, "ga4_trend.png")


def plot_channel_bars(curr_df, prev_df):
    """Grouped bar: sessions by channel, current vs previous."""
    if curr_df.empty:
        return _placeholder("ga4_channels.png")
    for df in [curr_df, prev_df]:
        df["sessions"] = pd.to_numeric(df["sessions"], errors="coerce").fillna(0)
    merged = pd.merge(
        curr_df[["sessionDefaultChannelGroup", "sessions"]].rename(columns={"sessions": "curr"}),
        prev_df[["sessionDefaultChannelGroup", "sessions"]].rename(columns={"sessions": "prev"}),
        on="sessionDefaultChannelGroup", how="outer"
    ).fillna(0).sort_values("curr", ascending=False).head(8)
    labels = [short_url(str(c), 20) for c in merged["sessionDefaultChannelGroup"]]
    x = np.arange(len(labels))
    width = 0.38
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars_p = ax.bar(x - width / 2, merged["prev"], width=width, color=C_SLATE, label="Previous", zorder=2)
    bars_c = ax.bar(x + width / 2, merged["curr"], width=width, color=C_NAVY, label="Current", zorder=2)
    max_v = max(merged["curr"].max(), merged["prev"].max(), 1)
    for bar, v in zip(list(bars_p) + list(bars_c), list(merged["prev"]) + list(merged["curr"])):
        if v > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.03,
                    f"{int(v):,}", ha="center", va="bottom", fontsize=8, color="#374151", fontweight="600")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8, rotation=15, ha="right")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.set_ylim(0, max_v * 1.25)
    _style_ax(ax, title="Sessions by Channel — Current vs Previous Week")
    fig.tight_layout(pad=2.0)
    return _save(fig, "ga4_channels.png")


def plot_device_split(device_df):
    """Horizontal stacked bar: sessions by device."""
    if device_df.empty:
        return _placeholder("ga4_devices.png")
    device_df = device_df.copy()
    device_df["sessions"] = pd.to_numeric(device_df["sessions"], errors="coerce").fillna(0)
    device_df["deviceCategory"] = device_df["deviceCategory"].str.capitalize()
    total = device_df["sessions"].sum()
    if total == 0:
        return _placeholder("ga4_devices.png")
    device_df["pct"] = device_df["sessions"] / total * 100
    colors = {"Mobile": C_NAVY, "Desktop": C_TEAL, "Tablet": C_AMBER}
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    left = 0
    for _, row in device_df.iterrows():
        dev = row["deviceCategory"]
        c = colors.get(dev, C_SLATE)
        ax.barh(0, row["pct"], left=left, color=c, height=0.55)
        if row["pct"] > 5:
            ax.text(left + row["pct"] / 2, 0, f"{dev}\n{row['pct']:.1f}%",
                    ha="center", va="center", fontsize=10, color="white", fontweight="600")
        left += row["pct"]
    ax.set_xlim(0, 100)
    ax.set_yticks([])
    _style_ax(ax, title="Sessions by Device (%)")
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    fig.tight_layout(pad=2.0)
    return _save(fig, "ga4_devices.png")


def plot_top_pages(pages_df):
    """Horizontal bar: top landing pages by sessions."""
    if pages_df.empty:
        return _placeholder("ga4_top_pages.png")
    pages_df = pages_df.copy()
    pages_df["sessions_current"] = pd.to_numeric(pages_df.get("sessions_current", pages_df.get("sessions", 0)),
                                                   errors="coerce").fillna(0)
    work = pages_df.nlargest(10, "sessions_current").iloc[::-1]
    labels = [short_url(str(u), 45) for u in work["landingPage"]]
    vals = work["sessions_current"].tolist()
    max_v = max(vals) if vals else 1
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars = ax.barh(labels, vals, color=C_NAVY, height=0.55, zorder=2)
    for bar, v in zip(bars, vals):
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}", va="center", fontsize=9, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Landing Pages by Sessions")
    fig.tight_layout(pad=2.0)
    return _save(fig, "ga4_top_pages.png")


def plot_page_movers(pages_df):
    """Lollipop: landing page session winners and losers WoW."""
    if pages_df.empty or "sessions_change" not in pages_df.columns:
        return _placeholder("ga4_page_movers.png")
    gainers = pages_df.nlargest(6, "sessions_change")
    losers  = pages_df.nsmallest(6, "sessions_change")
    merged  = pd.concat([losers, gainers], ignore_index=True)
    if merged.empty:
        return _placeholder("ga4_page_movers.png")
    labels = [short_url(str(u), 45) for u in merged["landingPage"]]
    values = merged["sessions_change"].tolist()
    colors = [C_CORAL if v < 0 else C_TEAL for v in values]
    max_abs = max(abs(v) for v in values) if values else 1
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    for i, (v, c) in enumerate(zip(values, colors)):
        ax.plot([0, v], [i, i], color=c, linewidth=2.0, zorder=2, solid_capstyle="round")
        ax.scatter([v], [i], color=c, s=70, zorder=3, edgecolors="white", linewidths=0.8)
        sign = "+" if v >= 0 else ""
        ha = "left" if v >= 0 else "right"
        ax.text(v + (max_abs * 0.025 if v >= 0 else -max_abs * 0.025), i,
                f"{sign}{int(v)}", va="center", ha=ha, fontsize=9, color=c, fontweight="600")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.axvline(0, color="#374151", linewidth=1.2, zorder=1)
    ax.axvspan(0, ax.get_xlim()[1] if ax.get_xlim()[1] > 0 else max_abs, alpha=0.03, color=C_TEAL)
    ax.axvspan(ax.get_xlim()[0] if ax.get_xlim()[0] < 0 else -max_abs, 0, alpha=0.03, color=C_CORAL)
    _style_ax(ax, title="Landing Page Session Winners & Losers (WoW)", xlabel="Session Change")
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=0)
    fig.tight_layout(pad=2.0)
    return _save(fig, "ga4_page_movers.png")


def plot_channel_quality(channels_df):
    """
    Scatter: sessions (x) vs engagement rate (y), bubble = active users.
    Identifies high-volume / low-quality channels and vice versa.
    """
    if channels_df.empty:
        return _placeholder("ga4_channel_quality.png")

    df = channels_df.copy()
    for col in ["sessions", "activeUsers", "engagementRate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df = df[df["sessions"] > 0]
    if df.empty:
        return _placeholder("ga4_channel_quality.png")

    df["engPct"] = df["engagementRate"] * 100
    max_users = df["activeUsers"].max() or 1
    sizes = (df["activeUsers"] / max_users * 800).clip(lower=60)

    colors = [C_GREEN if e >= 60 else C_AMBER if e >= 40 else C_CORAL for e in df["engPct"]]

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")

    ax.scatter(df["sessions"], df["engPct"], s=sizes, c=colors,
               alpha=0.75, edgecolors="white", linewidths=1.2, zorder=3)

    # Quadrant lines
    med_x = df["sessions"].median()
    med_y = df["engPct"].median()
    ax.axvline(med_x, color=C_BORDER, linestyle="--", linewidth=1, zorder=1)
    ax.axhline(med_y, color=C_BORDER, linestyle="--", linewidth=1, zorder=1)

    # Quadrant labels
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    ax.text(xlim[1] * 0.98, ylim[1] * 0.98, "High Volume\nHigh Quality",
            ha="right", va="top", fontsize=7, color=C_GREEN, fontweight="700")
    ax.text(xlim[0] + (xlim[1] - xlim[0]) * 0.02, ylim[1] * 0.98, "Low Volume\nHigh Quality",
            ha="left", va="top", fontsize=7, color=C_TEAL, fontweight="700")
    ax.text(xlim[1] * 0.98, ylim[0] + (ylim[1] - ylim[0]) * 0.02, "High Volume\nLow Quality",
            ha="right", va="bottom", fontsize=7, color=C_AMBER, fontweight="700")

    # Label each channel
    for _, row in df.iterrows():
        ax.annotate(str(row["sessionDefaultChannelGroup"])[:20],
                    xy=(row["sessions"], row["engPct"]),
                    xytext=(5, 4), textcoords="offset points",
                    fontsize=7, color="#374151",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=C_BORDER, alpha=0.85))

    ax.grid(linestyle="--", alpha=0.25, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Channel Quality Matrix  ·  bubble = active users  ·  colour = engagement tier",
              xlabel="Sessions", ylabel="Engagement Rate (%)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "ga4_channel_quality.png")


def build_all_charts(kpis, trend_curr, trend_prev, curr_channels, prev_channels,
                     device_df, pages_comparison):
    print("  Generating charts…", flush=True)
    return {
        "kpi_bars":         plot_kpi_bars(kpis),
        "trend":            plot_trend(trend_curr, trend_prev),
        "channels":         plot_channel_bars(curr_channels, prev_channels),
        "devices":          plot_device_split(device_df),
        "top_pages":        plot_top_pages(pages_comparison),
        "page_movers":      plot_page_movers(pages_comparison),
        "channel_quality":  plot_channel_quality(curr_channels),
    }


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

def build_pages_table(pages_df, n=20):
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
                       previous_start, previous_end):
    bullet_items = "".join(f"<li>{html.escape(b)}</li>" for b in exec_bullets)
    kpi_grid = "".join([
        _kpi_card("Sessions",        kpis["sessions"]["curr"],        kpis["sessions"]["prev"]),
        _kpi_card("Active Users",    kpis["users"]["curr"],           kpis["users"]["prev"]),
        _kpi_card("Engagement Rate", kpis["engagement_rate"]["curr"], kpis["engagement_rate"]["prev"]),
        _kpi_card("Avg Duration",    kpis["avg_duration"]["curr"],    kpis["avg_duration"]["prev"]),
        _kpi_card("Bounce Rate",     kpis["bounce_rate"]["curr"],     kpis["bounce_rate"]["prev"], lower_better=True),
    ])
    pages_tbl    = build_pages_table(pages_df)
    channels_tbl = build_channels_table(channels_df)
    today = date.today().strftime("%B %d, %Y")

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GA4 Weekly Performance Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=Source+Serif+4:ital,wght@0,300;0,400;0,600;1,400&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ background: #fff; background-image: repeating-linear-gradient(0deg,transparent,transparent 1px,#000 1px,#000 2px); background-size: 100% 4px; background-attachment: fixed; }}
html::before {{ content: ''; position: fixed; inset: 0; background: rgba(255,255,255,0.97); pointer-events: none; z-index: 0; }}
body {{ font-family: 'Source Serif 4', Georgia, serif; font-size: 14px; color: #000; background: transparent; line-height: 1.625; max-width: 1200px; margin: 0 auto; padding: 0 40px 80px; position: relative; z-index: 1; }}
.site-header {{ background: #000; color: #fff; padding: 40px 48px; margin: 0 -40px 0; position: relative; overflow: hidden; }}
.site-header::before {{ content: ''; position: absolute; inset: 0; background-image: repeating-linear-gradient(90deg,transparent,transparent 1px,#fff 1px,#fff 2px); background-size: 4px 100%; opacity: 0.03; pointer-events: none; }}
.site-header__eyebrow {{ font-family: 'JetBrains Mono', monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.2em; color: #999; margin-bottom: 12px; }}
.site-header__title {{ font-family: 'Playfair Display', Georgia, serif; font-size: clamp(32px, 5vw, 64px); font-weight: 900; line-height: 1; letter-spacing: -0.02em; color: #fff; margin-bottom: 16px; }}
.site-header__meta {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #666; letter-spacing: 0.05em; display: flex; align-items: center; gap: 16px; }}
.site-header__meta::before {{ content: ''; display: inline-block; width: 24px; height: 2px; background: #fff; flex-shrink: 0; }}
.section {{ padding: 40px 0; }}
.section-title {{ font-family: 'Playfair Display', Georgia, serif; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.15em; color: #000; margin-bottom: 24px; display: flex; align-items: center; gap: 16px; }}
.section-title::before {{ content: ''; display: inline-block; width: 8px; height: 8px; background: #000; flex-shrink: 0; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 2px; border: 2px solid #000; }}
.kpi-grid > div {{ border-right: 2px solid #000; }}
.kpi-grid > div:last-child {{ border-right: none; }}
.report-section {{ background: #fff; border: 2px solid #000; padding: 28px 32px; }}
.rule-thick {{ border: none; border-top: 4px solid #000; margin: 0; }}
{get_extra_css()}
@media (max-width: 768px) {{ body {{ padding: 0 20px 60px; }} .site-header {{ padding: 28px 24px; margin: 0 -20px 0; }} .kpi-grid {{ grid-template-columns: repeat(3, 1fr); }} .chart-row-2 {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<header class="site-header">
  <div class="site-header__eyebrow">Google Analytics 4</div>
  <h1 class="site-header__title">Weekly Performance<br>Report</h1>
  <div class="site-header__meta">{current_start} &rarr; {current_end} &nbsp;/&nbsp; prev {previous_start} &rarr; {previous_end}</div>
</header>
<hr class="rule-thick">
<div class="section">
  <div class="section-title">Executive Summary</div>
  <div class="exec-panel"><ul class="exec-bullets">{bullet_items}</ul></div>
</div>
<hr class="rule-thick">
<div class="section" style="padding-top:0;">
  <div class="kpi-grid">{kpi_grid}</div>
</div>
<hr class="rule-thick">
<div class="section">
  <div class="section-title">Performance Overview</div>
  <div class="report-section">
    <div class="col-header">KPI Comparison — Current vs Previous Week</div>
    {_chart_wrap(chart_paths.get("kpi_bars"), "KPI bars")}
    <div class="col-header">7-Day Daily Trend</div>
    {_chart_wrap(chart_paths.get("trend"), "Daily trend")}
  </div>
</div>
<hr class="rule-thick">
<div class="section">
  <div class="section-title">Channel &amp; Device Mix</div>
  <div class="report-section">
    <div class="col-header">Sessions by Channel</div>
    {_chart_wrap(chart_paths.get("channels"), "Channel performance")}
    <div class="col-header">Sessions by Device</div>
    {_chart_wrap(chart_paths.get("devices"), "Device split")}
  </div>
</div>
<hr class="rule-thick">
<div class="section">
  <div class="section-title">Channel Quality Matrix</div>
  <div class="report-section">
    {_chart_wrap(chart_paths.get("channel_quality"), "Channel quality matrix")}
  </div>
</div>
<hr class="rule-thick">
<div class="section">
  <div class="section-title">Landing Page Performance</div>
  <div class="report-section">
    <div class="col-header">Top Landing Pages by Sessions</div>
    {_chart_wrap(chart_paths.get("top_pages"), "Top landing pages")}
    <div class="col-header">Session Winners &amp; Losers (WoW)</div>
    {_chart_wrap(chart_paths.get("page_movers"), "Page movers")}
  </div>
</div>
<hr class="rule-thick">
<div class="section">
  <div class="section-title">Top Landing Pages</div>
  <div class="report-section">{pages_tbl}</div>
</div>
<hr class="rule-thick">
<div class="section">
  <div class="section-title">Channel Breakdown</div>
  <div class="report-section">{channels_tbl}</div>
</div>
<hr class="rule-thick">
<footer style="padding:32px 0;display:flex;justify-content:space-between;align-items:center;">
  <span style="font-family:'Playfair Display',Georgia,serif;font-size:13px;font-weight:700;letter-spacing:0.05em;">CIM SEO Intelligence</span>
  <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#525252;text-transform:uppercase;letter-spacing:0.12em;">Generated {today}</span>
</footer>
</body>
</html>"""

    with open("ga4_weekly_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("  Saved ga4_weekly_summary.html", flush=True)


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

    # HTML report
    write_html_summary(kpis, exec_bullets, chart_paths, pages_df, curr_channels,
                       curr_devices, curr_countries,
                       current_start, current_end, previous_start, previous_end)
    generate_self_contained()

    try:
        upload_to_monday()
    except Exception as e:
        print(f"  Monday upload failed: {e}", flush=True)

    print("GA4 Weekly Report — complete", flush=True)


if __name__ == "__main__":
    main()
