#!/usr/bin/env python3
"""
Monthly Chart Builder

Generates all charts for the monthly master dashboard:
- 20+ charts covering GA4, GSC, PageSpeed, and content performance
- Follows REPORT_DESIGN_PRINCIPLES.md for styling and sizing
- Saves charts to charts/ directory as PNG files
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

from seo_utils import short_url

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

# Brand palette — REPORT_DESIGN_PRINCIPLES.md §1
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
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _style_ax(ax, title="", xlabel="", ylabel=""):
    """Shared axes styling — REPORT_DESIGN_PRINCIPLES.md §6."""
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


def _save(fig, name):
    """Save figure to charts directory."""
    path = CHARTS_DIR / name
    fig.patch.set_facecolor("white")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _placeholder(name, message="No data available for this period."):
    """Generate placeholder chart for empty data."""
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    ax.text(0.5, 0.5, message, ha="center", va="center", 
            fontsize=12, color="#94A3B8", transform=ax.transAxes)
    ax.set_axis_off()
    return _save(fig, name)


# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS - PAGE 1: EXECUTIVE OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

def chart_kpi_overview(ga4_summary):
    """
    Paired bar chart: Current vs Previous for Sessions, Users, Clicks, Impressions.
    Used in executive overview section.
    """
    if ga4_summary.empty:
        return _placeholder("monthly_kpi_overview.png")
    
    # Extract metrics
    metrics_map = {row["metric"]: row for _, row in ga4_summary.iterrows()}
    
    labels = ["Sessions", "Active Users", "Engaged Sessions", "Events"]
    metric_keys = ["sessions", "activeUsers", "engagedSessions", "eventCount"]
    
    curr_vals = []
    prev_vals = []
    
    for key in metric_keys:
        if key in metrics_map:
            curr_vals.append(metrics_map[key]["current"])
            prev_vals.append(metrics_map[key]["previous"])
        else:
            curr_vals.append(0)
            prev_vals.append(0)
    
    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    bars_p = ax.bar(x - 0.2, prev_vals, width=0.38, color=C_SLATE, label="Previous Month", zorder=2)
    bars_c = ax.bar(x + 0.2, curr_vals, width=0.38, color=C_NAVY, label="Current Month", zorder=2)
    
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    
    max_v = max(curr_vals + prev_vals, default=1)
    for bar in list(bars_p) + list(bars_c):
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, h * 1.03,
                    f"{h:,.0f}", ha="center", va="bottom", fontsize=7,
                    color="#374151", fontweight="600")
    
    ax.set_ylim(0, max_v * 1.22)
    _style_ax(ax, title="Monthly KPI Overview — Current vs Previous Month")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_kpi_overview.png")


# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS - PAGE 2: TRAFFIC TRENDS & PATTERNS
# ══════════════════════════════════════════════════════════════════════════════

def chart_monthly_traffic_trend(ga4_daily, gsc_daily):
    """
    Dual-axis line chart: Sessions (GA4) + Clicks (GSC) over 30 days.
    Shows daily traffic patterns throughout the month.
    """
    if ga4_daily.empty and gsc_daily.empty:
        return _placeholder("monthly_traffic_trend.png")
    
    # Merge data on date
    if not ga4_daily.empty and not gsc_daily.empty:
        ga4_daily["date"] = pd.to_datetime(ga4_daily["date"])
        gsc_daily["date"] = pd.to_datetime(gsc_daily["date"])
        df = pd.merge(ga4_daily, gsc_daily, on="date", how="outer", suffixes=("_ga4", "_gsc"))
        df = df.sort_values("date")
    elif not ga4_daily.empty:
        df = ga4_daily.copy()
        df["date"] = pd.to_datetime(df["date"])
        df["clicks"] = 0
    else:
        df = gsc_daily.copy()
        df["date"] = pd.to_datetime(df["date"])
        df["sessions"] = 0
    
    df = df.fillna(0)
    
    fig, ax1 = plt.subplots(figsize=(13, 4.8))
    
    # Left axis: Sessions
    if "sessions" in df.columns:
        ax1.plot(df["date"], df["sessions"], color=C_NAVY, linewidth=2, label="Sessions (GA4)")
        ax1.fill_between(df["date"], df["sessions"], alpha=0.2, color=C_NAVY)
    
    # Right axis: Clicks
    ax2 = ax1.twinx()
    if "clicks" in df.columns:
        ax2.plot(df["date"], df["clicks"], color=C_TEAL, linewidth=2, label="Clicks (GSC)")
        ax2.fill_between(df["date"], df["clicks"], alpha=0.2, color=C_TEAL)
    
    # Styling
    _style_ax(ax1, title="Monthly Traffic Trend — Daily Sessions & Clicks", xlabel="Date", ylabel="Sessions")
    ax2.set_ylabel("Clicks", fontsize=8, color="#64748B", labelpad=4)
    ax2.tick_params(labelsize=8, colors="#64748B", length=0)
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color(C_BORDER)
    
    # Legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, frameon=False, fontsize=8, loc="upper left")
    
    # Grid
    ax1.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_traffic_trend.png")


def chart_channel_performance(ga4_channels_current, ga4_channels_previous):
    """
    Grouped bar chart: Channel performance (current vs previous month).
    Shows sessions by traffic source.
    """
    if ga4_channels_current.empty and ga4_channels_previous.empty:
        return _placeholder("monthly_channel_performance.png")
    
    # Merge current and previous
    curr = ga4_channels_current.copy() if not ga4_channels_current.empty else pd.DataFrame()
    prev = ga4_channels_previous.copy() if not ga4_channels_previous.empty else pd.DataFrame()
    
    if not curr.empty:
        curr = curr.rename(columns={"sessions": "sessions_current"})
    if not prev.empty:
        prev = prev.rename(columns={"sessions": "sessions_previous"})
    
    if not curr.empty and not prev.empty:
        df = pd.merge(curr[["channel", "sessions_current"]], 
                     prev[["channel", "sessions_previous"]], 
                     on="channel", how="outer").fillna(0)
    elif not curr.empty:
        df = curr[["channel", "sessions_current"]].copy()
        df["sessions_previous"] = 0
    else:
        df = prev[["channel", "sessions_previous"]].copy()
        df["sessions_current"] = 0
    
    df = df.sort_values("sessions_current", ascending=False).head(10)
    
    x = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    bars_p = ax.bar(x - 0.2, df["sessions_previous"], width=0.38, color=C_SLATE, label="Previous Month", zorder=2)
    bars_c = ax.bar(x + 0.2, df["sessions_current"], width=0.38, color=C_TEAL, label="Current Month", zorder=2)
    
    ax.set_xticks(x)
    ax.set_xticklabels(df["channel"], rotation=45, ha="right")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    
    max_v = max(df["sessions_current"].max(), df["sessions_previous"].max(), 1)
    for bar in list(bars_c):
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, h * 1.03,
                    f"{h:,.0f}", ha="center", va="bottom", fontsize=7,
                    color="#374151", fontweight="600")
    
    ax.set_ylim(0, max_v * 1.22)
    _style_ax(ax, title="Channel Performance — Sessions by Traffic Source")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_channel_performance.png")


def chart_device_evolution(ga4_devices):
    """
    Horizontal bar chart: Device distribution (mobile, desktop, tablet).
    Shows current month device split.
    """
    if ga4_devices.empty:
        return _placeholder("monthly_device_distribution.png")
    
    df = ga4_devices.copy()
    df = df.sort_values("sessions", ascending=True)
    
    # Calculate percentages
    total = df["sessions"].sum()
    df["pct"] = (df["sessions"] / total * 100) if total > 0 else 0
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    colors = [C_NAVY if d == "mobile" else C_TEAL if d == "desktop" else C_SLATE 
              for d in df["device"]]
    
    bars = ax.barh(df["device"], df["sessions"], color=colors, zorder=2)
    
    max_v = df["sessions"].max() or 1
    for i, (bar, pct) in enumerate(zip(bars, df["pct"])):
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{v:,.0f} ({pct:.1f}%)", va="center", fontsize=9, 
                color="#374151", fontweight="600")
    
    ax.set_xlim(0, max_v * 1.25)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Device Distribution — Sessions by Device Type")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_device_distribution.png")


# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS - PAGE 3: SEARCH PERFORMANCE DEEP DIVE
# ══════════════════════════════════════════════════════════════════════════════

def chart_search_funnel(ga4_summary, gsc_queries):
    """
    Horizontal funnel chart: Impressions → Clicks → Sessions → Engaged Sessions.
    Shows conversion at each stage of the search-to-engagement funnel.
    """
    if ga4_summary.empty or gsc_queries.empty:
        return _placeholder("monthly_search_funnel.png")
    
    # Extract metrics
    metrics_map = {row["metric"]: row for _, row in ga4_summary.iterrows()}
    
    impressions = gsc_queries["impressions_current"].sum() if "impressions_current" in gsc_queries.columns else 0
    clicks = gsc_queries["clicks_current"].sum() if "clicks_current" in gsc_queries.columns else 0
    sessions = metrics_map.get("sessions", {}).get("current", 0)
    engaged = metrics_map.get("engagedSessions", {}).get("current", 0)
    
    stages = ["Impressions", "Clicks", "Sessions", "Engaged Sessions"]
    values = [impressions, clicks, sessions, engaged]
    
    # Calculate conversion rates
    conversions = []
    for i in range(len(values) - 1):
        if values[i] > 0:
            rate = values[i + 1] / values[i] * 100
            conversions.append(f"{rate:.1f}%")
        else:
            conversions.append("—")
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    # Normalize for visual funnel effect
    max_val = max(values) or 1
    normalized = [v / max_val for v in values]
    
    colors = [C_NAVY, C_TEAL, C_GREEN, C_AMBER]
    y_pos = np.arange(len(stages))
    
    bars = ax.barh(y_pos, normalized, color=colors, zorder=2)
    
    # Add labels
    for i, (bar, val, stage) in enumerate(zip(bars, values, stages)):
        # Value label
        ax.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height() / 2,
                f"{val:,.0f}", va="center", fontsize=10, 
                color="#374151", fontweight="600")
        
        # Conversion rate label
        if i < len(conversions):
            ax.text(bar.get_width() / 2, bar.get_y() + bar.get_height() / 2,
                    conversions[i], va="center", ha="center", fontsize=9,
                    color="white", fontweight="700")
    
    ax.set_yticks(y_pos)
    ax.set_yticklabels(stages)
    ax.set_xlim(0, 1.2)
    ax.set_xticks([])
    
    _style_ax(ax, title="Search Visibility Funnel — Conversion at Each Stage")
    ax.spines["bottom"].set_visible(False)
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_search_funnel.png")


def chart_top_movers_queries(gsc_queries):
    """
    Lollipop chart: Top 10 query movers (gainers and losers by position change).
    Shows which queries improved or declined in ranking.
    """
    if gsc_queries.empty or "position_change" not in gsc_queries.columns:
        return _placeholder("monthly_top_movers_queries.png")
    
    df = gsc_queries.copy()
    df["position_change"] = pd.to_numeric(df["position_change"], errors="coerce").fillna(0)
    
    # Position change is negative when improving (lower position number = better)
    gainers = df[df["position_change"] < 0].nsmallest(5, "position_change").copy()
    losers = df[df["position_change"] > 0].nlargest(5, "position_change").copy()
    
    if gainers.empty and losers.empty:
        return _placeholder("monthly_top_movers_queries.png", "No significant position changes this month.")
    
    gainers["delta"] = gainers["position_change"].abs()
    losers["delta"] = -losers["position_change"].abs()
    gainers["label"] = gainers["query"].apply(lambda q: short_url(str(q), 35))
    losers["label"] = losers["query"].apply(lambda q: short_url(str(q), 35))
    
    plot_df = pd.concat([gainers[["label", "delta"]], losers[["label", "delta"]]]).sort_values("delta")
    
    if plot_df.empty:
        return _placeholder("monthly_top_movers_queries.png", "No significant position changes this month.")
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    ax.axvline(0, color="#888", linewidth=0.8, zorder=1)
    
    for i, (_, row) in enumerate(plot_df.iterrows()):
        color = C_TEAL if row["delta"] > 0 else C_CORAL
        ax.plot([0, row["delta"]], [i, i], color=color, linewidth=1.5, zorder=2)
        ax.scatter([row["delta"]], [i], color=color, s=55, zorder=3)
    
    ax.set_yticks(range(len(plot_df)))
    ax.set_yticklabels(plot_df["label"], fontsize=8)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    
    gain_p = mpatches.Patch(color=C_TEAL, label="Improved Ranking")
    loss_p = mpatches.Patch(color=C_CORAL, label="Declined Ranking")
    ax.legend(handles=[gain_p, loss_p], frameon=False, fontsize=8, loc="lower right")
    
    _style_ax(ax, title="Top Query Movers — Position Changes (Lower is Better)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_top_movers_queries.png")


def chart_top_queries(gsc_queries):
    """
    Horizontal bar chart: Top 10 queries by clicks.
    Shows which queries drive the most traffic.
    """
    if gsc_queries.empty:
        return _placeholder("monthly_top_queries.png")
    
    df = gsc_queries.copy()
    click_col = "clicks_current" if "clicks_current" in df.columns else "clicks"
    df[click_col] = pd.to_numeric(df[click_col], errors="coerce").fillna(0)
    df = df.sort_values(click_col, ascending=True).tail(10)
    df["label"] = df["query"].apply(lambda q: short_url(str(q), 40))
    
    max_v = df[click_col].max() or 1
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["label"], df[click_col], color=C_TEAL, zorder=2)
    
    for bar in bars:
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}", va="center", fontsize=8, color="#374151")
    
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Search Queries — Clicks (Current Month)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_top_queries.png")


def chart_top_pages(gsc_pages):
    """
    Horizontal bar chart: Top 10 landing pages by clicks.
    Shows which pages receive the most search traffic.
    """
    if gsc_pages.empty:
        return _placeholder("monthly_top_pages.png")
    
    df = gsc_pages.copy()
    click_col = "clicks_current" if "clicks_current" in df.columns else "clicks"
    df[click_col] = pd.to_numeric(df[click_col], errors="coerce").fillna(0)
    df = df.sort_values(click_col, ascending=True).tail(10)
    df["label"] = df["page"].apply(lambda p: short_url(str(p), 45))
    
    max_v = df[click_col].max() or 1
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["label"], df[click_col], color=C_NAVY, zorder=2)
    
    for bar in bars:
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}", va="center", fontsize=8, color="#374151")
    
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Landing Pages — Clicks (Current Month)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_top_pages.png")


# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS - PAGE 4: CONTENT PERFORMANCE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def chart_ga4_landing_pages(ga4_pages):
    """
    Horizontal bar chart: Top 10 GA4 landing pages by sessions.
    Shows which pages drive the most traffic from all sources.
    """
    if ga4_pages.empty:
        return _placeholder("monthly_ga4_landing_pages.png")
    
    df = ga4_pages.copy()
    df["sessions"] = pd.to_numeric(df["sessions"], errors="coerce").fillna(0)
    df = df.sort_values("sessions", ascending=True).tail(10)
    df["label"] = df["landingPage"].apply(lambda p: short_url(str(p), 45))
    
    max_v = df["sessions"].max() or 1
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["label"], df["sessions"], color=C_NAVY, zorder=2)
    
    for bar in bars:
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}", va="center", fontsize=8, color="#374151")
    
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Landing Pages — Sessions (GA4)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_ga4_landing_pages.png")


def chart_engagement_by_channel(ga4_channels_current):
    """
    Horizontal bar chart: Engagement rate by channel.
    Shows which channels deliver the most engaged users.
    """
    if ga4_channels_current.empty or "engagementRate" not in ga4_channels_current.columns:
        return _placeholder("monthly_engagement_by_channel.png")
    
    df = ga4_channels_current.copy()
    df["engagementRate"] = pd.to_numeric(df["engagementRate"], errors="coerce").fillna(0)
    df = df.sort_values("engagementRate", ascending=True).tail(10)
    
    # Convert to percentage
    df["engagementPct"] = df["engagementRate"] * 100
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    # Color code by performance
    colors = [C_GREEN if e >= 0.6 else C_AMBER if e >= 0.4 else C_CORAL 
              for e in df["engagementRate"]]
    
    bars = ax.barh(df["channel"], df["engagementPct"], color=colors, zorder=2)
    
    for bar in bars:
        v = bar.get_width()
        ax.text(v + 1, bar.get_y() + bar.get_height() / 2,
                f"{v:.1f}%", va="center", fontsize=8, color="#374151")
    
    ax.set_xlim(0, 110)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Engagement Rate by Channel — Quality of Traffic")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_engagement_by_channel.png")


def chart_sessions_vs_clicks(ga4_pages, gsc_pages):
    """
    Scatter plot: GA4 sessions vs GSC clicks for landing pages.
    Identifies pages with high search visibility but low conversion.
    """
    if ga4_pages.empty or gsc_pages.empty:
        return _placeholder("monthly_sessions_vs_clicks.png")
    
    # Merge GA4 and GSC data
    ga4 = ga4_pages.copy()
    gsc = gsc_pages.copy()
    
    # Normalize URLs for matching
    ga4["url"] = ga4["landingPage"].str.lower().str.rstrip("/")
    gsc["url"] = gsc["page"].str.lower().str.rstrip("/")
    
    click_col = "clicks_current" if "clicks_current" in gsc.columns else "clicks"
    
    merged = pd.merge(
        ga4[["url", "sessions"]],
        gsc[["url", click_col]],
        on="url",
        how="inner"
    )
    
    if merged.empty:
        return _placeholder("monthly_sessions_vs_clicks.png", "No matching pages between GA4 and GSC data.")
    
    merged["sessions"] = pd.to_numeric(merged["sessions"], errors="coerce").fillna(0)
    merged[click_col] = pd.to_numeric(merged[click_col], errors="coerce").fillna(0)
    
    # Filter to pages with meaningful traffic
    merged = merged[(merged["sessions"] > 10) | (merged[click_col] > 10)]
    
    if merged.empty:
        return _placeholder("monthly_sessions_vs_clicks.png", "Insufficient traffic data for comparison.")
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    # Calculate conversion rate (sessions / clicks)
    merged["conversion"] = merged["sessions"] / merged[click_col].replace(0, 1)
    
    # Color by conversion rate
    colors = [C_GREEN if c >= 0.8 else C_AMBER if c >= 0.5 else C_CORAL 
              for c in merged["conversion"]]
    
    ax.scatter(merged[click_col], merged["sessions"], 
               s=80, alpha=0.6, c=colors, edgecolors="white", linewidth=1, zorder=2)
    
    # Add diagonal reference line (1:1 ratio)
    max_val = max(merged[click_col].max(), merged["sessions"].max())
    ax.plot([0, max_val], [0, max_val], 'k--', alpha=0.3, linewidth=1, zorder=1)
    
    ax.grid(True, linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Landing Page Efficiency — GSC Clicks vs GA4 Sessions", 
              xlabel="Clicks (GSC)", ylabel="Sessions (GA4)")
    
    # Add legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_GREEN, markersize=8, label='High Conversion (≥80%)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_AMBER, markersize=8, label='Medium Conversion (50-80%)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_CORAL, markersize=8, label='Low Conversion (<50%)'),
    ]
    ax.legend(handles=legend_elements, frameon=False, fontsize=7, loc="upper left")
    
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_sessions_vs_clicks.png")


# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS - PAGE 5: TECHNICAL HEALTH & SPEED
# ══════════════════════════════════════════════════════════════════════════════

def chart_core_web_vitals(pagespeed_data):
    """
    3-panel gauge chart: LCP, INP, CLS pass rates.
    Shows percentage of pages passing each Core Web Vital.
    """
    if pagespeed_data.empty:
        return _placeholder("monthly_core_web_vitals.png", "No PageSpeed data available.\nRun site_speed_monitoring.py first.")
    
    # Filter to mobile data only
    mobile = pagespeed_data[pagespeed_data["strategy"] == "mobile"].copy()
    
    if mobile.empty:
        return _placeholder("monthly_core_web_vitals.png", "No mobile PageSpeed data available.")
    
    # Calculate pass rates for each metric
    lcp_data = mobile[mobile["lcp_field_category"].notna()]
    inp_data = mobile[mobile["inp_field_category"].notna()]
    cls_data = mobile[mobile["cls_field_category"].notna()]
    
    lcp_pass = (lcp_data["lcp_field_category"] == "FAST").sum() / len(lcp_data) * 100 if len(lcp_data) > 0 else 0
    inp_pass = (inp_data["inp_field_category"] == "FAST").sum() / len(inp_data) * 100 if len(inp_data) > 0 else 0
    cls_pass = (cls_data["cls_field_category"] == "FAST").sum() / len(cls_data) * 100 if len(cls_data) > 0 else 0
    
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    
    metrics = [
        ("LCP", lcp_pass, len(lcp_data)),
        ("INP", inp_pass, len(inp_data)),
        ("CLS", cls_pass, len(cls_data))
    ]
    
    for ax, (label, pass_rate, count) in zip(axes, metrics):
        # Create donut chart
        sizes = [pass_rate, 100 - pass_rate]
        colors = [C_GREEN if pass_rate >= 75 else C_AMBER if pass_rate >= 50 else C_CORAL, C_LIGHT]
        
        wedges, texts = ax.pie(sizes, colors=colors, startangle=90, counterclock=False,
                               wedgeprops=dict(width=0.4, edgecolor='white', linewidth=2))
        
        # Add center text
        ax.text(0, 0, f"{pass_rate:.0f}%", ha="center", va="center",
                fontsize=24, fontweight="700", color="#1A1A1A")
        ax.text(0, -0.25, f"{label}\n({count} pages)", ha="center", va="top",
                fontsize=9, color="#64748B")
        
        ax.set_title(f"{label} Pass Rate", fontsize=10, fontweight="600", 
                    color="#1A1A1A", pad=12)
    
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_core_web_vitals.png")


def chart_performance_distribution(pagespeed_data):
    """
    Histogram: Distribution of performance scores by score band.
    Shows how many pages fall into each performance category.
    """
    if pagespeed_data.empty:
        return _placeholder("monthly_performance_distribution.png", "No PageSpeed data available.\nRun site_speed_monitoring.py first.")
    
    # Filter to mobile data with valid scores
    mobile = pagespeed_data[
        (pagespeed_data["strategy"] == "mobile") & 
        (pagespeed_data["performance_score"].notna())
    ].copy()
    
    if mobile.empty:
        return _placeholder("monthly_performance_distribution.png", "No mobile performance scores available.")
    
    # Define score bands
    bins = [0, 50, 90, 100]
    labels = ["Poor (0-49)", "Needs Improvement (50-89)", "Good (90-100)"]
    colors_map = {
        "Poor (0-49)": C_CORAL,
        "Needs Improvement (50-89)": C_AMBER,
        "Good (90-100)": C_GREEN
    }
    
    mobile["score_band"] = pd.cut(mobile["performance_score"], bins=bins, labels=labels, include_lowest=True)
    counts = mobile["score_band"].value_counts().reindex(labels).fillna(0)
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    
    colors = [colors_map[label] for label in labels]
    bars = ax.bar(labels, counts.values, color=colors, width=0.6, zorder=2)
    
    # Add value labels
    max_v = counts.max() or 1
    for bar, val in zip(bars, counts.values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max_v * 0.02,
                    f"{int(val)}", ha="center", va="bottom", fontsize=10,
                    color="#374151", fontweight="600")
    
    ax.set_ylim(0, max_v * 1.2)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Performance Score Distribution — Mobile Pages", ylabel="Number of Pages")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_performance_distribution.png")


def chart_speed_traffic_correlation(pagespeed_data, ga4_pages):
    """
    Scatter plot: Performance score vs sessions.
    Identifies high-traffic pages with poor performance.
    """
    if pagespeed_data.empty or ga4_pages.empty:
        return _placeholder("monthly_speed_traffic_correlation.png", "Insufficient data for correlation analysis.")
    
    # Get mobile performance scores
    mobile = pagespeed_data[
        (pagespeed_data["strategy"] == "mobile") & 
        (pagespeed_data["performance_score"].notna())
    ].copy()
    
    if mobile.empty:
        return _placeholder("monthly_speed_traffic_correlation.png", "No mobile performance data available.")
    
    # Normalize URLs for matching
    mobile["url"] = mobile["page"].str.lower().str.rstrip("/")
    ga4_pages["url"] = ga4_pages["landingPage"].str.lower().str.rstrip("/")
    
    # Merge data
    merged = pd.merge(
        mobile[["url", "performance_score"]],
        ga4_pages[["url", "sessions"]],
        on="url",
        how="inner"
    )
    
    if merged.empty or len(merged) < 3:
        return _placeholder("monthly_speed_traffic_correlation.png", "Insufficient matching pages for correlation.")
    
    merged["sessions"] = pd.to_numeric(merged["sessions"], errors="coerce").fillna(0)
    merged = merged[merged["sessions"] > 10]  # Filter to meaningful traffic
    
    if merged.empty:
        return _placeholder("monthly_speed_traffic_correlation.png", "No pages with sufficient traffic.")
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    
    # Color by performance score
    colors = []
    for score in merged["performance_score"]:
        if score >= 90:
            colors.append(C_GREEN)
        elif score >= 50:
            colors.append(C_AMBER)
        else:
            colors.append(C_CORAL)
    
    ax.scatter(merged["performance_score"], merged["sessions"],
               s=100, alpha=0.6, c=colors, edgecolors="white", linewidth=1.5, zorder=2)
    
    # Add reference line at score=90
    ax.axvline(90, color=C_BORDER, linestyle="--", linewidth=1, alpha=0.7, zorder=1)
    
    ax.grid(True, linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Performance vs Traffic — Identify High-Impact Optimization Targets",
              xlabel="Performance Score", ylabel="Sessions")
    
    # Add legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_GREEN, markersize=8, label='Good (≥90)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_AMBER, markersize=8, label='Needs Improvement (50-89)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_CORAL, markersize=8, label='Poor (<50)'),
    ]
    ax.legend(handles=legend_elements, frameon=False, fontsize=7, loc="upper right")
    
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_speed_traffic_correlation.png")


def chart_technical_issues(pagespeed_data):
    """
    Horizontal bar chart: Count of pages with technical issues.
    Shows pages failing each Core Web Vital.
    """
    if pagespeed_data.empty:
        return _placeholder("monthly_technical_issues.png", "No PageSpeed data available.\nRun site_speed_monitoring.py first.")
    
    mobile = pagespeed_data[pagespeed_data["strategy"] == "mobile"].copy()
    
    if mobile.empty:
        return _placeholder("monthly_technical_issues.png", "No mobile PageSpeed data available.")
    
    # Count issues
    issues = {
        "Poor LCP": (mobile["lcp_field_category"] == "SLOW").sum(),
        "Poor INP": (mobile["inp_field_category"] == "SLOW").sum(),
        "Poor CLS": (mobile["cls_field_category"] == "SLOW").sum(),
        "Low Performance Score": (mobile["performance_score"] < 50).sum(),
        "Failed CWV": (~mobile["cwv_pass"]).sum() if "cwv_pass" in mobile.columns else 0,
    }
    
    # Filter to non-zero issues
    issues = {k: v for k, v in issues.items() if v > 0}
    
    if not issues:
        return _placeholder("monthly_technical_issues.png", "No significant technical issues detected.\nAll pages performing well!")
    
    labels = list(issues.keys())
    values = list(issues.values())
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    
    bars = ax.barh(labels, values, color=C_CORAL, zorder=2)
    
    max_v = max(values) or 1
    for bar, val in zip(bars, values):
        ax.text(val + max_v * 0.02, bar.get_y() + bar.get_height() / 2,
                f"{int(val)}", va="center", fontsize=9, color="#374151", fontweight="600")
    
    ax.set_xlim(0, max_v * 1.2)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Technical Issues Summary — Pages Requiring Attention", xlabel="Number of Pages")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_technical_issues.png")


# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS - PAGE 6: AI & INNOVATION METRICS
# ══════════════════════════════════════════════════════════════════════════════

def chart_ai_readiness(ai_snippet_data):
    """
    Gauge + bar chart: AI readiness scores by page.
    Shows overall AI readiness and breakdown by page.
    """
    if ai_snippet_data.empty:
        return _placeholder("monthly_ai_readiness.png", "No AI snippet data available.\nRun ai_snippet_verification.py first.")
    
    # Calculate overall readiness score (average of all scores)
    df = ai_snippet_data.copy()
    
    # Ensure numeric columns
    for col in ["access_score", "summary_score", "cta_score"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    df["overall_score"] = (df["access_score"] + df["summary_score"] + df["cta_score"]) / 3
    
    overall_avg = df["overall_score"].mean()
    
    # Create figure with 2 subplots
    fig = plt.figure(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    gs = fig.add_gridspec(1, 2, width_ratios=[1, 2], wspace=0.3)
    
    # Left: Gauge chart for overall score
    ax1 = fig.add_subplot(gs[0])
    
    # Create donut chart as gauge
    score_pct = overall_avg / 5 * 100
    sizes = [score_pct, 100 - score_pct]
    colors = [C_GREEN if score_pct >= 80 else C_AMBER if score_pct >= 60 else C_CORAL, C_LIGHT]
    
    wedges, texts = ax1.pie(sizes, colors=colors, startangle=90, counterclock=False,
                            wedgeprops=dict(width=0.5, edgecolor='white', linewidth=2))
    
    ax1.text(0, 0, f"{overall_avg:.1f}/5", ha="center", va="center",
            fontsize=28, fontweight="700", color="#1A1A1A")
    ax1.text(0, -0.3, "Overall AI\nReadiness", ha="center", va="top",
            fontsize=9, color="#64748B")
    ax1.set_title("Average Score", fontsize=10, fontweight="600", color="#1A1A1A", pad=12)
    
    # Right: Bar chart by page
    ax2 = fig.add_subplot(gs[1])
    
    top_pages = df.nlargest(8, "overall_score")
    labels = [short_url(p, 35) for p in top_pages["page_name"]]
    values = top_pages["overall_score"].tolist()
    
    colors_bar = [C_GREEN if v >= 4 else C_AMBER if v >= 3 else C_CORAL for v in values]
    bars = ax2.barh(labels, values, color=colors_bar, zorder=2)
    
    ax2.invert_yaxis()
    ax2.set_xlim(0, 5.5)
    ax2.axvline(4, color=C_BORDER, linestyle="--", linewidth=1, alpha=0.5, zorder=1)
    ax2.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    
    for bar, val in zip(bars, values):
        ax2.text(val + 0.1, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}", va="center", fontsize=8, color="#374151", fontweight="600")
    
    _style_ax(ax2, title="Top Pages by AI Readiness", xlabel="Score (0-5)")
    
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_ai_readiness.png")


def chart_structured_data(ai_snippet_data):
    """
    Donut chart: Pages with vs without structured data coverage.
    Shows percentage of pages ready for AI extraction.
    """
    if ai_snippet_data.empty:
        return _placeholder("monthly_structured_data.png", "No AI snippet data available.\nRun ai_snippet_verification.py first.")
    
    df = ai_snippet_data.copy()
    
    # Use summary_score as proxy for structured data readiness
    # Score >= 4 = good structured data, < 4 = needs improvement
    if "summary_score" not in df.columns:
        return _placeholder("monthly_structured_data.png", "No summary score data available.")
    
    df["summary_score"] = pd.to_numeric(df["summary_score"], errors="coerce").fillna(0)
    
    good_structure = (df["summary_score"] >= 4).sum()
    needs_improvement = len(df) - good_structure
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    
    sizes = [good_structure, needs_improvement]
    labels = [f"Good Structure\n({good_structure} pages)", 
              f"Needs Improvement\n({needs_improvement} pages)"]
    colors = [C_GREEN, C_AMBER]
    
    wedges, texts, autotexts = ax.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%',
                                       startangle=90, textprops={'fontsize': 10, 'fontweight': '600'},
                                       wedgeprops=dict(width=0.5, edgecolor='white', linewidth=2))
    
    # Style percentage text
    for autotext in autotexts:
        autotext.set_color('white')
        autotext.set_fontsize(12)
        autotext.set_fontweight('700')
    
    ax.set_title("Structured Data Coverage — AI Extraction Readiness", 
                fontsize=10, fontweight="600", color="#1A1A1A", pad=12, loc="left")
    
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_structured_data.png")


def chart_content_freshness(content_audit_data):
    """
    Stacked bar chart: Pages by performance category.
    Shows distribution of content that needs refresh vs archive.
    """
    if content_audit_data.empty:
        return _placeholder("monthly_content_freshness.png", "No content audit data available.\nRun content_audit_schedule_report.py first.")
    
    df = content_audit_data.copy()
    
    if "recommended_action" not in df.columns:
        return _placeholder("monthly_content_freshness.png", "No recommendation data available.")
    
    # Count by action
    action_counts = df["recommended_action"].value_counts()
    
    # Define categories
    categories = ["Refresh", "Archive", "Monitor"]
    counts = []
    colors_map = {"Refresh": C_AMBER, "Archive": C_CORAL, "Monitor": C_GREEN}
    colors = []
    
    for cat in categories:
        count = action_counts.get(cat, 0)
        counts.append(count)
        colors.append(colors_map.get(cat, C_SLATE))
    
    # Filter to non-zero
    non_zero = [(cat, cnt, col) for cat, cnt, col in zip(categories, counts, colors) if cnt > 0]
    
    if not non_zero:
        return _placeholder("monthly_content_freshness.png", "No content audit recommendations available.")
    
    categories, counts, colors = zip(*non_zero)
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    
    bars = ax.bar(categories, counts, color=colors, width=0.5, zorder=2)
    
    max_v = max(counts) or 1
    for bar, val in zip(bars, counts):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max_v * 0.02,
                    f"{int(val)}", ha="center", va="bottom", fontsize=10,
                    color="#374151", fontweight="600")
    
    ax.set_ylim(0, max_v * 1.2)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Content Audit Recommendations — Pages by Action", ylabel="Number of Pages")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_content_freshness.png")


# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS - PAGE 7: CHANNEL & AUDIENCE INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════

def chart_device_comparison(ga4_devices, gsc_devices):
    """
    Grouped bar chart: Device performance comparison (GA4 vs GSC).
    Shows sessions (GA4) and clicks (GSC) by device type.
    """
    if ga4_devices.empty and gsc_devices.empty:
        return _placeholder("monthly_device_comparison.png")
    
    # Prepare data
    devices = ["mobile", "desktop", "tablet"]
    ga4_vals = []
    gsc_vals = []
    
    for device in devices:
        # GA4 sessions
        if not ga4_devices.empty:
            ga4_row = ga4_devices[ga4_devices["device"] == device]
            ga4_vals.append(ga4_row["sessions"].iloc[0] if not ga4_row.empty else 0)
        else:
            ga4_vals.append(0)
        
        # GSC clicks
        if not gsc_devices.empty:
            gsc_row = gsc_devices[gsc_devices["device"] == device]
            gsc_vals.append(gsc_row["clicks"].iloc[0] if not gsc_row.empty else 0)
        else:
            gsc_vals.append(0)
    
    x = np.arange(len(devices))
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    bars_ga4 = ax.bar(x - 0.2, ga4_vals, width=0.38, color=C_NAVY, label="Sessions (GA4)", zorder=2)
    bars_gsc = ax.bar(x + 0.2, gsc_vals, width=0.38, color=C_TEAL, label="Clicks (GSC)", zorder=2)
    
    ax.set_xticks(x)
    ax.set_xticklabels([d.capitalize() for d in devices])
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    
    max_v = max(ga4_vals + gsc_vals, default=1)
    for bar in list(bars_ga4) + list(bars_gsc):
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, h * 1.03,
                    f"{h:,.0f}", ha="center", va="bottom", fontsize=7,
                    color="#374151", fontweight="600")
    
    ax.set_ylim(0, max_v * 1.22)
    _style_ax(ax, title="Device Performance Comparison — Sessions vs Clicks")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_device_comparison.png")


def chart_channel_efficiency(ga4_channels_current):
    """
    Scatter plot: Channel efficiency (sessions vs engagement rate).
    Bubble size represents active users.
    """
    if ga4_channels_current.empty:
        return _placeholder("monthly_channel_efficiency.png")
    
    df = ga4_channels_current.copy()
    
    # Ensure numeric columns
    for col in ["sessions", "activeUsers", "engagementRate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    # Filter to channels with meaningful traffic
    df = df[df["sessions"] > 100]
    
    if df.empty:
        return _placeholder("monthly_channel_efficiency.png", "Insufficient channel data for analysis.")
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    # Convert engagement rate to percentage
    df["engagementPct"] = df["engagementRate"] * 100
    
    # Bubble size based on active users
    sizes = df["activeUsers"] / df["activeUsers"].max() * 1000 if df["activeUsers"].max() > 0 else 100
    
    # Color by engagement rate
    colors = [C_GREEN if e >= 0.6 else C_AMBER if e >= 0.4 else C_CORAL 
              for e in df["engagementRate"]]
    
    scatter = ax.scatter(df["sessions"], df["engagementPct"], 
                        s=sizes, alpha=0.6, c=colors, edgecolors="white", linewidth=1.5, zorder=2)
    
    # Add channel labels for top performers
    for _, row in df.nlargest(5, "sessions").iterrows():
        ax.annotate(row["channel"], 
                   xy=(row["sessions"], row["engagementPct"]),
                   xytext=(5, 5), textcoords="offset points",
                   fontsize=7, color="#374151", fontweight="600")
    
    ax.grid(True, linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Channel Efficiency Matrix — Volume vs Quality", 
              xlabel="Sessions", ylabel="Engagement Rate (%)")
    
    # Add legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_GREEN, markersize=8, label='High Engagement (≥60%)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_AMBER, markersize=8, label='Medium Engagement (40-60%)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_CORAL, markersize=8, label='Low Engagement (<40%)'),
    ]
    ax.legend(handles=legend_elements, frameon=False, fontsize=7, loc="upper right")
    
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_channel_efficiency.png")


def chart_engagement_trend(ga4_daily):
    """
    Line chart: Daily engagement rate trend over the month.
    Shows engagement rate fluctuations throughout the period.
    """
    if ga4_daily.empty or "engagementRate" not in ga4_daily.columns:
        return _placeholder("monthly_engagement_trend.png")
    
    df = ga4_daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["engagementRate"] = pd.to_numeric(df["engagementRate"], errors="coerce").fillna(0)
    df = df.sort_values("date")
    
    # Convert to percentage
    df["engagementPct"] = df["engagementRate"] * 100
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    ax.plot(df["date"], df["engagementPct"], color=C_NAVY, linewidth=2, zorder=2)
    ax.fill_between(df["date"], df["engagementPct"], alpha=0.2, color=C_NAVY)
    
    # Add average line
    avg = df["engagementPct"].mean()
    ax.axhline(avg, color=C_TEAL, linestyle="--", linewidth=1, alpha=0.7, 
               label=f"Average: {avg:.1f}%", zorder=1)
    
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Engagement Rate Trend — Daily Performance", 
              xlabel="Date", ylabel="Engagement Rate (%)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_engagement_trend.png")


# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS - ADDITIONAL INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════

def chart_ctr_by_position(gsc_queries):
    """
    Scatter plot: CTR vs average position for queries.
    Shows the relationship between ranking and click-through rate.
    """
    if gsc_queries.empty:
        return _placeholder("monthly_ctr_by_position.png")
    
    df = gsc_queries.copy()
    
    # Use current period data
    pos_col = "position_current" if "position_current" in df.columns else "position"
    ctr_col = "ctr_current" if "ctr_current" in df.columns else "ctr"
    clicks_col = "clicks_current" if "clicks_current" in df.columns else "clicks"
    
    for col in [pos_col, ctr_col, clicks_col]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    # Filter to queries with meaningful data
    df = df[(df[pos_col] > 0) & (df[pos_col] <= 50) & (df[clicks_col] > 5)]
    
    if df.empty:
        return _placeholder("monthly_ctr_by_position.png", "Insufficient query data for CTR analysis.")
    
    # Convert CTR to percentage
    df["ctrPct"] = df[ctr_col] * 100
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    # Bubble size based on clicks
    sizes = df[clicks_col] / df[clicks_col].max() * 500 if df[clicks_col].max() > 0 else 50
    
    # Color by position band
    colors = []
    for pos in df[pos_col]:
        if pos <= 3:
            colors.append(C_GREEN)
        elif pos <= 10:
            colors.append(C_NAVY)
        elif pos <= 20:
            colors.append(C_AMBER)
        else:
            colors.append(C_CORAL)
    
    ax.scatter(df[pos_col], df["ctrPct"], 
               s=sizes, alpha=0.6, c=colors, edgecolors="white", linewidth=1, zorder=2)
    
    # Invert x-axis (lower position = better)
    ax.invert_xaxis()
    
    ax.grid(True, linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="CTR vs Position — Click-Through Rate by Ranking", 
              xlabel="Average Position (lower is better)", ylabel="CTR (%)")
    
    # Add legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_GREEN, markersize=8, label='Top 3'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_NAVY, markersize=8, label='Page 1 (4-10)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_AMBER, markersize=8, label='Page 2 (11-20)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_CORAL, markersize=8, label='Page 3+ (21-50)'),
    ]
    ax.legend(handles=legend_elements, frameon=False, fontsize=7, loc="upper right")
    
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_ctr_by_position.png")


def chart_impressions_vs_clicks(gsc_queries):
    """
    Scatter plot: Impressions vs clicks for queries.
    Identifies queries with high visibility but low CTR.
    """
    if gsc_queries.empty:
        return _placeholder("monthly_impressions_vs_clicks.png")
    
    df = gsc_queries.copy()
    
    # Use current period data
    impr_col = "impressions_current" if "impressions_current" in df.columns else "impressions"
    clicks_col = "clicks_current" if "clicks_current" in df.columns else "clicks"
    ctr_col = "ctr_current" if "ctr_current" in df.columns else "ctr"
    
    for col in [impr_col, clicks_col, ctr_col]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    # Filter to queries with meaningful impressions
    df = df[df[impr_col] > 100]
    
    if df.empty:
        return _placeholder("monthly_impressions_vs_clicks.png", "Insufficient query data for analysis.")
    
    fig, ax = plt.subplots(figsize=(13, 4.8))
    
    # Color by CTR
    df["ctrPct"] = df[ctr_col] * 100
    colors = []
    for ctr in df["ctrPct"]:
        if ctr >= 5:
            colors.append(C_GREEN)
        elif ctr >= 2:
            colors.append(C_AMBER)
        else:
            colors.append(C_CORAL)
    
    ax.scatter(df[impr_col], df[clicks_col], 
               s=80, alpha=0.6, c=colors, edgecolors="white", linewidth=1, zorder=2)
    
    # Add reference lines for CTR bands
    max_impr = df[impr_col].max()
    ax.plot([0, max_impr], [0, max_impr * 0.05], 'g--', alpha=0.3, linewidth=1, label='5% CTR')
    ax.plot([0, max_impr], [0, max_impr * 0.02], 'orange', linestyle='--', alpha=0.3, linewidth=1, label='2% CTR')
    
    ax.grid(True, linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Impressions vs Clicks — CTR Opportunities", 
              xlabel="Impressions", ylabel="Clicks")
    
    # Add legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_GREEN, markersize=8, label='High CTR (≥5%)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_AMBER, markersize=8, label='Medium CTR (2-5%)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor=C_CORAL, markersize=8, label='Low CTR (<2%)'),
    ]
    ax.legend(handles=legend_elements, frameon=False, fontsize=7, loc="upper left")
    
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_impressions_vs_clicks.png")


# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS - PAGE 8: BROKEN LINKS & INTERNAL LINKING
# ══════════════════════════════════════════════════════════════════════════════

def chart_broken_link_domain_health(broken_link_data):
    """
    Grouped bar: broken / redirect / server-error counts per domain.
    """
    if broken_link_data.empty or "issue_type" not in broken_link_data.columns:
        return _placeholder("monthly_broken_link_domain_health.png",
                            "No broken link data available.\nRun broken_link_check.py first.")

    from urllib.parse import urlparse
    df = broken_link_data.copy()
    df["domain"] = df["source_url"].apply(
        lambda u: urlparse(str(u)).netloc.replace("www.", "")
    )

    pivot = (
        df[df["issue_type"] != "ok"]
        .groupby(["domain", "issue_type"])
        .size()
        .unstack(fill_value=0)
    )
    for col in ["broken", "redirect", "server_error", "client_error"]:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot = pivot[["broken", "redirect", "server_error", "client_error"]]
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("total", ascending=True).drop(columns="total")

    x = np.arange(len(pivot))
    width = 0.2
    bar_colors = [C_RED, C_TEAL, C_CORAL, C_AMBER]
    bar_labels = ["Broken", "Redirect", "5xx", "4xx Other"]

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    offsets = [-1.5, -0.5, 0.5, 1.5]
    for i, (col, color, label) in enumerate(zip(pivot.columns, bar_colors, bar_labels)):
        bars = ax.bar(x + offsets[i] * width, pivot[col], width=width,
                      color=color, label=label, zorder=2)
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, h + 0.2,
                        str(int(h)), ha="center", va="bottom", fontsize=7,
                        color="#374151", fontweight="600")

    ax.set_xticks(x)
    ax.set_xticklabels(pivot.index, fontsize=8, rotation=15, ha="right")
    ax.legend(frameon=False, fontsize=8, ncol=4)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Broken Link Issues by Domain", ylabel="Issue Count")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_broken_link_domain_health.png")


def chart_broken_link_issue_breakdown(broken_link_data):
    """
    Horizontal stacked bar: issue type distribution across all links.
    """
    if broken_link_data.empty or "issue_type" not in broken_link_data.columns:
        return _placeholder("monthly_broken_link_issue_breakdown.png",
                            "No broken link data available.\nRun broken_link_check.py first.")

    counts = broken_link_data["issue_type"].value_counts()
    order  = ["broken", "server_error", "client_error", "redirect", "error", "ok"]
    colors = {
        "broken": C_RED, "server_error": C_CORAL, "client_error": C_AMBER,
        "redirect": C_TEAL, "error": C_SLATE, "ok": C_GREEN,
    }
    labels_map = {
        "broken": "Broken (404/410)", "server_error": "5xx Server",
        "client_error": "4xx Other", "redirect": "Redirect",
        "error": "Timeout/Error", "ok": "OK",
    }
    total = len(broken_link_data)

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    left = 0
    for issue in order:
        val = counts.get(issue, 0)
        if val == 0:
            continue
        pct = val / total * 100
        ax.barh(0, pct, left=left, color=colors[issue], height=0.55,
                label=f"{labels_map[issue]} ({val:,})")
        if pct > 4:
            ax.text(left + pct / 2, 0, f"{labels_map[issue]}\n{pct:.1f}%",
                    ha="center", va="center", fontsize=8, color="white", fontweight="600")
        left += pct

    ax.set_xlim(0, 100)
    ax.set_yticks([])
    ax.legend(loc="lower right", frameon=False, fontsize=7, ncol=3)
    _style_ax(ax, title=f"Link Health Distribution — {total:,} total links checked")
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_broken_link_issue_breakdown.png")


def chart_internal_link_distribution(internal_link_data):
    """
    Horizontal bar: pages ranked by inbound internal link count.
    Highlights orphan pages (0 inlinks) and over-linked pages.
    """
    if internal_link_data.empty:
        return _placeholder("monthly_internal_link_distribution.png",
                            "No internal linking data available.\nRun internal_linking_audit.py first.")

    df = internal_link_data.copy()
    # Try common column names from internal_linking_audit.py
    inlink_col = next((c for c in ["inlink_count", "inlinks", "in_links", "inbound_links"]
                       if c in df.columns), None)
    page_col   = next((c for c in ["page", "url", "source_url"] if c in df.columns), None)

    if not inlink_col or not page_col:
        return _placeholder("monthly_internal_link_distribution.png",
                            "Internal link data missing expected columns.")

    df[inlink_col] = pd.to_numeric(df[inlink_col], errors="coerce").fillna(0)
    orphans = int((df[inlink_col] == 0).sum())

    work = df.sort_values(inlink_col, ascending=True).tail(15)
    labels = [short_url(str(u), 45) for u in work[page_col]]
    vals   = work[inlink_col].tolist()
    colors = [C_CORAL if v == 0 else C_NAVY for v in vals]
    max_v  = max(vals) if vals else 1

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars = ax.barh(labels, vals, color=colors, height=0.55, zorder=2)
    for bar, v in zip(bars, vals):
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                str(int(v)), va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title=f"Internal Link Distribution — Top 15 Pages by Inbound Links  ·  {orphans} orphan pages",
              xlabel="Inbound Internal Links")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_internal_link_distribution.png")


# ══════════════════════════════════════════════════════════════════════════════
# CHART FUNCTIONS - PAGE 9: CONTENT CATEGORY PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════

def chart_content_category_sessions(content_category_data):
    """
    Horizontal bar: sessions by content category (current month).
    """
    if content_category_data.empty or "sessions" not in content_category_data.columns:
        return _placeholder("monthly_content_category_sessions.png",
                            "No content category data available.\nRun content_category_performance.py first.")

    df = content_category_data.copy()
    df["sessions"] = pd.to_numeric(df["sessions"], errors="coerce").fillna(0)
    df = df[df["sessions"] > 0].sort_values("sessions", ascending=True)

    if df.empty:
        return _placeholder("monthly_content_category_sessions.png", "No session data by category.")

    CATEGORY_COLORS = [C_NAVY, C_TEAL, C_CORAL, C_AMBER, C_GREEN, C_SLATE,
                       C_RED, "#8B5CF6", "#F59E0B", "#10B981", "#6366F1", "#EC4899"]
    colors = [CATEGORY_COLORS[i % len(CATEGORY_COLORS)] for i in range(len(df))]
    total  = df["sessions"].sum()
    max_v  = df["sessions"].max()

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars = ax.barh(df["category"], df["sessions"], color=colors, height=0.55, zorder=2)
    for bar, v in zip(bars, df["sessions"]):
        pct = v / total * 100
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{v:,.0f} ({pct:.1f}%)", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.25)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Sessions by Content Category", xlabel="Sessions")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_content_category_sessions.png")


def chart_content_category_engagement(content_category_data):
    """
    Scatter: impressions vs engagement rate per category, sized by sessions.
    """
    if content_category_data.empty:
        return _placeholder("monthly_content_category_engagement.png",
                            "No content category data available.\nRun content_category_performance.py first.")

    df = content_category_data.copy()
    for col in ["impressions", "engagement_rate", "sessions"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "impressions" not in df.columns or "engagement_rate" not in df.columns:
        return _placeholder("monthly_content_category_engagement.png",
                            "Missing impressions or engagement_rate columns.")

    df = df[(df["impressions"] > 0) | (df["engagement_rate"] > 0)]
    if df.empty:
        return _placeholder("monthly_content_category_engagement.png", "No data to plot.")

    df["log_impr"] = np.log10(df["impressions"].clip(lower=1))
    max_sess = df["sessions"].max() if "sessions" in df.columns and df["sessions"].max() > 0 else 1
    sizes = (df["sessions"] / max_sess * 800).clip(lower=60) if "sessions" in df.columns else 100

    CATEGORY_COLORS = [C_NAVY, C_TEAL, C_CORAL, C_AMBER, C_GREEN, C_SLATE,
                       C_RED, "#8B5CF6", "#F59E0B", "#10B981", "#6366F1", "#EC4899"]
    colors = [CATEGORY_COLORS[i % len(CATEGORY_COLORS)] for i in range(len(df))]

    fig, ax = plt.subplots(figsize=(13, 6.5))
    fig.patch.set_facecolor("white")
    ax.scatter(df["log_impr"], df["engagement_rate"], s=sizes, c=colors,
               alpha=0.80, edgecolors="white", linewidths=0.8, zorder=3)

    # Quadrant reference lines
    mid_x = df["log_impr"].median()
    mid_y = df["engagement_rate"].median()
    ax.axvline(mid_x, color=C_BORDER, linewidth=1, linestyle="--", zorder=1)
    ax.axhline(mid_y, color=C_BORDER, linewidth=1, linestyle="--", zorder=1)

    for i, (_, row) in enumerate(df.iterrows()):
        ax.annotate(row["category"],
                    (row["log_impr"], row["engagement_rate"]),
                    textcoords="offset points", xytext=(6, 4),
                    fontsize=7, color="#374151")

    ax.grid(linestyle="--", alpha=0.2, color=C_BORDER, zorder=1)
    _style_ax(ax,
              title="Content Category Ecosystem  ·  bubble = sessions  ·  x = log impressions  ·  y = engagement rate",
              xlabel="Search Visibility (Log10 Impressions)",
              ylabel="Engagement Rate")
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_content_category_engagement.png")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN BUILD FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def build_all_monthly_charts(data):
    """
    Build all charts for the monthly dashboard.
    
    Args:
        data: Dictionary containing all data DataFrames
    
    Returns:
        dict: Dictionary mapping chart names to file paths
    """
    print("=" * 80)
    print("MONTHLY CHART GENERATION - STARTING")
    print("=" * 80)
    
    chart_paths = {}
    
    # Page 1: Executive Overview
    print("\n[1/8] Generating Executive Overview charts...")
    chart_paths["kpi_overview"] = chart_kpi_overview(data.get("ga4_summary", pd.DataFrame()))
    print("  ✓ KPI overview")
    
    # Page 2: Traffic Trends & Patterns
    print("\n[2/8] Generating Traffic Trends charts...")
    chart_paths["traffic_trend"] = chart_monthly_traffic_trend(
        data.get("ga4_daily", pd.DataFrame()),
        data.get("gsc_daily", pd.DataFrame())
    )
    print("  ✓ Monthly traffic trend")
    
    chart_paths["channel_performance"] = chart_channel_performance(
        data.get("ga4_channels_current", pd.DataFrame()),
        data.get("ga4_channels_previous", pd.DataFrame())
    )
    print("  ✓ Channel performance")
    
    chart_paths["device_distribution"] = chart_device_evolution(
        data.get("ga4_devices", pd.DataFrame())
    )
    print("  ✓ Device distribution")
    
    # Page 3: Search Performance Deep Dive
    print("\n[3/8] Generating Search Performance charts...")
    chart_paths["search_funnel"] = chart_search_funnel(
        data.get("ga4_summary", pd.DataFrame()),
        data.get("gsc_queries", pd.DataFrame())
    )
    print("  ✓ Search funnel")
    
    chart_paths["top_movers_queries"] = chart_top_movers_queries(
        data.get("gsc_queries", pd.DataFrame())
    )
    print("  ✓ Top movers (queries)")
    
    chart_paths["top_queries"] = chart_top_queries(
        data.get("gsc_queries", pd.DataFrame())
    )
    print("  ✓ Top queries")
    
    chart_paths["top_pages"] = chart_top_pages(
        data.get("gsc_pages", pd.DataFrame())
    )
    print("  ✓ Top pages")
    
    chart_paths["ctr_by_position"] = chart_ctr_by_position(
        data.get("gsc_queries", pd.DataFrame())
    )
    print("  ✓ CTR by position")
    
    chart_paths["impressions_vs_clicks"] = chart_impressions_vs_clicks(
        data.get("gsc_queries", pd.DataFrame())
    )
    print("  ✓ Impressions vs clicks")
    
    # Page 4: Content Performance Analysis
    print("\n[4/8] Generating Content Performance charts...")
    chart_paths["ga4_landing_pages"] = chart_ga4_landing_pages(
        data.get("ga4_pages", pd.DataFrame())
    )
    print("  ✓ GA4 landing pages")
    
    chart_paths["engagement_by_channel"] = chart_engagement_by_channel(
        data.get("ga4_channels_current", pd.DataFrame())
    )
    print("  ✓ Engagement by channel")
    
    chart_paths["sessions_vs_clicks"] = chart_sessions_vs_clicks(
        data.get("ga4_pages", pd.DataFrame()),
        data.get("gsc_pages", pd.DataFrame())
    )
    print("  ✓ Sessions vs clicks (landing page efficiency)")
    
    # Page 5: Technical Health & Speed
    print("\n[5/8] Generating Technical Health charts...")
    pagespeed_data = data.get("pagespeed", pd.DataFrame())
    
    chart_paths["core_web_vitals"] = chart_core_web_vitals(pagespeed_data)
    status = "✓" if not pagespeed_data.empty else "⚠"
    print(f"  {status} Core Web Vitals")
    
    chart_paths["performance_distribution"] = chart_performance_distribution(pagespeed_data)
    print(f"  {status} Performance distribution")
    
    chart_paths["speed_traffic_correlation"] = chart_speed_traffic_correlation(
        pagespeed_data,
        data.get("ga4_pages", pd.DataFrame())
    )
    print(f"  {status} Speed vs traffic")
    
    chart_paths["technical_issues"] = chart_technical_issues(pagespeed_data)
    print(f"  {status} Technical issues")
    
    # Page 6: AI & Innovation Metrics
    print("\n[6/8] Generating AI & Innovation charts...")
    ai_snippet_data = data.get("ai_snippet", pd.DataFrame())
    content_audit_data = data.get("content_audit", pd.DataFrame())
    
    chart_paths["ai_readiness"] = chart_ai_readiness(ai_snippet_data)
    status = "✓" if not ai_snippet_data.empty else "⚠"
    print(f"  {status} AI readiness")
    
    chart_paths["structured_data"] = chart_structured_data(ai_snippet_data)
    print(f"  {status} Structured data")
    
    chart_paths["content_freshness"] = chart_content_freshness(content_audit_data)
    status = "✓" if not content_audit_data.empty else "⚠"
    print(f"  {status} Content freshness")
    
    # Page 7: Channel & Audience Insights
    print("\n[7/8] Generating Channel & Audience charts...")
    chart_paths["device_comparison"] = chart_device_comparison(
        data.get("ga4_devices", pd.DataFrame()),
        data.get("gsc_devices", pd.DataFrame())
    )
    print("  ✓ Device comparison")
    
    chart_paths["channel_efficiency"] = chart_channel_efficiency(
        data.get("ga4_channels_current", pd.DataFrame())
    )
    print("  ✓ Channel efficiency matrix")
    
    chart_paths["engagement_trend"] = chart_engagement_trend(
        data.get("ga4_daily", pd.DataFrame())
    )
    print("  ✓ Engagement trend")
    
    # Page 8: Technical Health — Broken Links & Internal Linking
    print("\n[8/9] Generating Technical Health (Link Audit) charts...")
    broken_link_data   = data.get("broken_links",   pd.DataFrame())
    internal_link_data = data.get("internal_links", pd.DataFrame())

    chart_paths["broken_link_domain_health"] = chart_broken_link_domain_health(broken_link_data)
    status = "✓" if not broken_link_data.empty else "⚠"
    print(f"  {status} Broken link domain health")

    chart_paths["broken_link_issue_breakdown"] = chart_broken_link_issue_breakdown(broken_link_data)
    print(f"  {status} Broken link issue breakdown")

    chart_paths["internal_link_distribution"] = chart_internal_link_distribution(internal_link_data)
    status = "✓" if not internal_link_data.empty else "⚠"
    print(f"  {status} Internal link distribution")

    # Page 9: Content Category Performance
    print("\n[9/9] Generating Content Category charts...")
    content_category_data = data.get("content_categories", pd.DataFrame())

    chart_paths["content_category_sessions"] = chart_content_category_sessions(content_category_data)
    status = "✓" if not content_category_data.empty else "⚠"
    print(f"  {status} Content category sessions")

    chart_paths["content_category_engagement"] = chart_content_category_engagement(content_category_data)
    print(f"  {status} Content category engagement")

    print("\n" + "=" * 80)
    print(f"MONTHLY CHART GENERATION - COMPLETE ({len(chart_paths)} charts)")
    print("=" * 80)

    return chart_paths


if __name__ == "__main__":
    # Load data from monthly_data/ directory
    from pathlib import Path
    
    data_dir = Path("monthly_data")
    
    if not data_dir.exists():
        print("Error: monthly_data/ directory not found. Run monthly_data_collector.py first.")
        exit(1)
    
    print("Loading data from monthly_data/...")
    data = {
        "ga4_summary": pd.read_csv(data_dir / "monthly_ga4_summary.csv") if (data_dir / "monthly_ga4_summary.csv").exists() else pd.DataFrame(),
        "ga4_daily": pd.read_csv(data_dir / "monthly_ga4_daily.csv") if (data_dir / "monthly_ga4_daily.csv").exists() else pd.DataFrame(),
        "ga4_pages": pd.read_csv(data_dir / "monthly_ga4_pages_current.csv") if (data_dir / "monthly_ga4_pages_current.csv").exists() else pd.DataFrame(),
        "ga4_channels_current": pd.read_csv(data_dir / "monthly_ga4_channels_current.csv") if (data_dir / "monthly_ga4_channels_current.csv").exists() else pd.DataFrame(),
        "ga4_channels_previous": pd.read_csv(data_dir / "monthly_ga4_channels_previous.csv") if (data_dir / "monthly_ga4_channels_previous.csv").exists() else pd.DataFrame(),
        "ga4_devices": pd.read_csv(data_dir / "monthly_ga4_devices.csv") if (data_dir / "monthly_ga4_devices.csv").exists() else pd.DataFrame(),
        "gsc_queries": pd.read_csv(data_dir / "monthly_gsc_queries.csv") if (data_dir / "monthly_gsc_queries.csv").exists() else pd.DataFrame(),
        "gsc_pages": pd.read_csv(data_dir / "monthly_gsc_pages.csv") if (data_dir / "monthly_gsc_pages.csv").exists() else pd.DataFrame(),
        "gsc_daily": pd.read_csv(data_dir / "monthly_gsc_daily.csv") if (data_dir / "monthly_gsc_daily.csv").exists() else pd.DataFrame(),
        "gsc_devices": pd.read_csv(data_dir / "monthly_gsc_devices.csv") if (data_dir / "monthly_gsc_devices.csv").exists() else pd.DataFrame(),
    }
    
    print(f"✓ Loaded {len([d for d in data.values() if not d.empty])} data files")
    
    # Build all charts
    chart_paths = build_all_monthly_charts(data)
    
    print(f"\n✓ Generated {len(chart_paths)} charts in charts/ directory")
