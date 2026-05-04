import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from seo_utils import get_weekly_date_windows

# GSC Configuration
GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
GSC_KEY_FILE = "gsc-key.json"
GSC_PROPERTY = os.environ.get("GSC_PROPERTY")

# GA4 Configuration
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID")
GA4_KEY_FILE = "gsc-key.json"

CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

def get_gsc_service():
    if not os.path.exists(GSC_KEY_FILE): return None
    creds = service_account.Credentials.from_service_account_file(GSC_KEY_FILE, scopes=GSC_SCOPES)
    return build("searchconsole", "v1", credentials=creds)

def get_ga4_client():
    if not os.path.exists(GA4_KEY_FILE): return None
    creds = service_account.Credentials.from_service_account_file(GA4_KEY_FILE)
    return BetaAnalyticsDataClient(credentials=creds)

def categorize_url(url):
    url = str(url).lower().split('?')[0].rstrip('/')
    
    # Subdomains first
    if "magazine.cim.org" in url: return "Magazine"
    if "convention.cim.org" in url: return "Events"
    if "mrmr.cim.org" in url: return "Technical Standards"
    if "memo.cim.org" in url: return "Regional News"
    if "com.metsoc.org" in url: return "Societies"
    
    # Path patterns
    if "/events" in url or "/calendar" in url: return "Events"
    if "/professional-development" in url or "/short-courses" in url: return "Education"
    if "/library" in url or "/technical-resources" in url or "/cim-journal" in url: return "Technical Library"
    if "/membership" in url: return "Membership"
    if "/scholarships" in url or "/student" in url: return "Student/Scholarships"
    if "/news" in url or "/press-releases" in url: return "News/Press"
    if "/awards" in url: return "Awards"
    if "/about-us" in url: return "Institute Info"
    if url == "https://www.cim.org": return "Homepage"
    
    return "Other"

def fetch_gsc_data(service, start_date, end_date):
    if not service: return pd.DataFrame()
    # Pulling 25k rows to capture almost everything
    request = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["page"],
        "rowLimit": 25000,
    }
    response = service.searchanalytics().query(siteUrl=GSC_PROPERTY, body=request).execute()
    rows = response.get("rows", [])
    data = []
    for row in rows:
        url = row["keys"][0]
        data.append({
            "page": url,
            "category": categorize_url(url),
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "position": row.get("position", 0)
        })
    return pd.DataFrame(data)

def fetch_ga4_data(client, start_date, end_date):
    if not client: return pd.DataFrame()
    # Pulling 25k rows from GA4 too
    request = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name="pagePath")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="engagementRate"),
            Metric(name="averageSessionDuration")
        ],
        date_ranges=[DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())],
        limit=25000
    )
    response = client.run_report(request)
    data = []
    base_url = "https://www.cim.org"
    for row in response.rows:
        path = row.dimension_values[0].value
        url = base_url + path if path.startswith('/') else path
        data.append({
            "page": url,
            "category": categorize_url(url),
            "sessions": float(row.metric_values[0].value),
            "engagement_rate": float(row.metric_values[1].value),
            "avg_duration": float(row.metric_values[2].value)
        })
    return pd.DataFrame(data)


# ── Brand palette ──────────────────────────────────────────────────────────────
C_NAVY   = "#212878"
C_TEAL   = "#2A9D8F"
C_CORAL  = "#E76F51"
C_SLATE  = "#6C757D"
C_GREEN  = "#059669"
C_RED    = "#DC2626"
C_AMBER  = "#D97706"
C_BORDER = "#E2E8F0"

CATEGORY_COLORS = [C_NAVY, C_TEAL, C_CORAL, C_AMBER, C_GREEN, C_SLATE,
                   C_RED, "#8B5CF6", "#F59E0B", "#10B981", "#6366F1", "#EC4899"]


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


def plot_ecosystem_scatter(df):
    """Bubble chart: impressions vs engagement rate, sized by sessions."""
    if df.empty or df["sessions"].sum() == 0:
        fig, ax = plt.subplots(figsize=(13, 6.5))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No data available.", ha="center", va="center",
                fontsize=12, color="#94A3B8", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "content_ecosystem_map.png")

    plot_df = df[df["sessions"] > 0].copy()
    plot_df["log_impressions"] = np.log10(plot_df["impressions"].clip(lower=1))
    max_sess = plot_df["sessions"].max()
    sizes = (plot_df["sessions"] / max_sess * 1200).clip(lower=60)
    colors = [CATEGORY_COLORS[i % len(CATEGORY_COLORS)]
              for i in range(len(plot_df))]

    fig, ax = plt.subplots(figsize=(13, 6.5))
    fig.patch.set_facecolor("white")

    # Quadrant shading
    mid_x = plot_df["log_impressions"].median()
    mid_y = plot_df["engagement_rate"].median()
    ax.axvspan(ax.get_xlim()[0] if ax.get_xlim()[0] > 0 else 0, mid_x,
               ymin=0.5, alpha=0.04, color=C_TEAL, zorder=0)
    ax.axvspan(mid_x, plot_df["log_impressions"].max() * 1.05,
               ymin=0.5, alpha=0.04, color=C_GREEN, zorder=0)
    ax.axvspan(ax.get_xlim()[0] if ax.get_xlim()[0] > 0 else 0, mid_x,
               ymax=0.5, alpha=0.04, color=C_CORAL, zorder=0)
    ax.axvspan(mid_x, plot_df["log_impressions"].max() * 1.05,
               ymax=0.5, alpha=0.04, color=C_AMBER, zorder=0)

    ax.scatter(plot_df["log_impressions"], plot_df["engagement_rate"],
               s=sizes, c=colors, alpha=0.80, edgecolors="white",
               linewidths=0.8, zorder=3)

    # Quadrant labels
    x_min = plot_df["log_impressions"].min()
    x_max = plot_df["log_impressions"].max()
    y_max = plot_df["engagement_rate"].max()
    ax.text(x_min, y_max * 0.95, "Hidden Gems", fontsize=8, color=C_TEAL, alpha=0.6)
    ax.text(x_max * 0.85, y_max * 0.95, "Champions", fontsize=8, color=C_GREEN, alpha=0.6)
    ax.text(x_min, y_max * 0.05, "Underperformers", fontsize=8, color=C_CORAL, alpha=0.6)
    ax.text(x_max * 0.85, y_max * 0.05, "Broad Reach", fontsize=8, color=C_AMBER, alpha=0.6)

    # Annotate each category
    for i, (_, row) in enumerate(plot_df.iterrows()):
        ax.annotate(row["category"],
                    (row["log_impressions"], row["engagement_rate"]),
                    textcoords="offset points", xytext=(6, 4),
                    fontsize=7, color="#374151")

    ax.axvline(mid_x, color=C_BORDER, linewidth=1, linestyle="--", zorder=1)
    ax.axhline(mid_y, color=C_BORDER, linewidth=1, linestyle="--", zorder=1)
    ax.grid(linestyle="--", alpha=0.2, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Content Ecosystem Map  ·  bubble = sessions  ·  x = log impressions  ·  y = engagement rate",
              xlabel="Search Visibility (Log10 Impressions)", ylabel="Engagement Rate")
    fig.tight_layout(pad=2.0)
    return _save(fig, "content_ecosystem_map.png")


def plot_share_of_voice(df):
    """Horizontal bar: sessions share by content category."""
    if df.empty or df["sessions"].sum() == 0:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No session data available.", ha="center", va="center",
                fontsize=12, color="#94A3B8", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "content_share_of_voice.png")

    data = df.groupby("category")["sessions"].sum().sort_values(ascending=True)
    total = data.sum()
    colors = [CATEGORY_COLORS[i % len(CATEGORY_COLORS)] for i in range(len(data))]
    max_v = data.max()

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars = ax.barh(data.index, data.values, color=colors, height=0.55, zorder=2)
    for bar, v in zip(bars, data.values):
        pct = v / total * 100
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{v:,.0f} ({pct:.1f}%)", va="center", fontsize=9, color="#374151")
    ax.set_xlim(0, max_v * 1.25)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Sessions by Content Category", xlabel="Sessions")
    fig.tight_layout(pad=2.0)
    return _save(fig, "content_share_of_voice.png")


def plot_clicks_by_category(df):
    """Horizontal bar: GSC clicks by category."""
    if df.empty or df["clicks"].sum() == 0:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No click data available.", ha="center", va="center",
                fontsize=12, color="#94A3B8", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "content_clicks_by_category.png")

    data = df.groupby("category")["clicks"].sum().sort_values(ascending=True)
    colors = [CATEGORY_COLORS[i % len(CATEGORY_COLORS)] for i in range(len(data))]
    max_v = data.max()

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars = ax.barh(data.index, data.values, color=colors, height=0.55, zorder=2)
    for bar, v in zip(bars, data.values):
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{v:,.0f}", va="center", fontsize=9, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="GSC Clicks by Content Category", xlabel="Clicks")
    fig.tight_layout(pad=2.0)
    return _save(fig, "content_clicks_by_category.png")


def plot_engagement_by_category(df):
    """Horizontal bar: avg engagement rate by category."""
    if df.empty or df["engagement_rate"].sum() == 0:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No engagement data available.", ha="center", va="center",
                fontsize=12, color="#94A3B8", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "content_engagement_by_category.png")

    data = df.groupby("category")["engagement_rate"].mean().sort_values(ascending=True)
    colors = [C_TEAL if v >= data.median() else C_CORAL for v in data.values]
    max_v = data.max()

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars = ax.barh(data.index, data.values, color=colors, height=0.55, zorder=2)
    for bar, v in zip(bars, data.values):
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{v:.2%}", va="center", fontsize=9, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    ax.axvline(data.median(), color=C_AMBER, linewidth=1.2, linestyle="--",
               zorder=3, label=f"Median ({data.median():.2%})")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Avg Engagement Rate by Content Category", xlabel="Engagement Rate")
    fig.tight_layout(pad=2.0)
    return _save(fig, "content_engagement_by_category.png")


def build_all_charts(df):
    print("  Generating charts...", flush=True)
    return {
        "ecosystem":   plot_ecosystem_scatter(df),
        "share":       plot_share_of_voice(df),
        "clicks":      plot_clicks_by_category(df),
        "engagement":  plot_engagement_by_category(df),
    }


def main():
    print("Content Category Performance — starting", flush=True)
    curr_start, curr_end, prev_start, prev_end = get_weekly_date_windows()

    gsc_service = get_gsc_service()
    ga4_client  = get_ga4_client()

    gsc_data = fetch_gsc_data(gsc_service, curr_start, curr_end)
    ga4_data = fetch_ga4_data(ga4_client, curr_start, curr_end)

    gsc_cat = gsc_data.groupby("category").agg(
        clicks=("clicks", "sum"),
        impressions=("impressions", "sum"),
        position=("position", "mean"),
    ).reset_index() if not gsc_data.empty else pd.DataFrame(
        columns=["category", "clicks", "impressions", "position"])

    ga4_cat = ga4_data.groupby("category").agg(
        sessions=("sessions", "sum"),
        engagement_rate=("engagement_rate", "mean"),
        avg_duration=("avg_duration", "mean"),
    ).reset_index() if not ga4_data.empty else pd.DataFrame(
        columns=["category", "sessions", "engagement_rate", "avg_duration"])

    content_perf = pd.merge(gsc_cat, ga4_cat, on="category", how="outer").fillna(0)
    for col in ["category", "clicks", "impressions", "sessions", "engagement_rate", "avg_duration"]:
        if col not in content_perf.columns:
            content_perf[col] = 0

    content_perf.to_csv("content_category_performance.csv", index=False)
    print(f"  Saved content_category_performance.csv ({len(content_perf)} categories)", flush=True)

    chart_paths = build_all_charts(content_perf)
    print(f"  Generated {len(chart_paths)} charts", flush=True)
    print("Content Category Performance — complete", flush=True)


if __name__ == "__main__":
    main()
