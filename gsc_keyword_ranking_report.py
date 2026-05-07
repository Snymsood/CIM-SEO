from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
import pandas as pd
import numpy as np
import requests
import os
import html as _html
from pathlib import Path
import matplotlib
from pdf_report_formatter import html_table_from_df, format_delta, format_num
from html_report_utils import (
    mm_html_shell, mm_kpi_card, mm_kpi_grid, mm_section, mm_report_section,
    mm_col_header, mm_chart_wrap, mm_chart_row_2, mm_exec_bullets,
    generate_self_contained_html, upload_html_to_monday,
)
from seo_utils import get_weekly_date_windows, short_url
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
KEY_FILE = "gsc-key.json"
SITE_URL = os.environ["GSC_PROPERTY"]
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")

TRACKED_KEYWORDS_FILE = "tracked_keywords.csv"
CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

# Brand palette — matches REPORT_DESIGN_PRINCIPLES.md
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

def get_service():
    credentials = service_account.Credentials.from_service_account_file(
        KEY_FILE,
        scopes=SCOPES,
    )
    return build("searchconsole", "v1", credentials=credentials)


def load_tracked_keywords():
    df = pd.read_csv(TRACKED_KEYWORDS_FILE)
    df["keyword"] = df["keyword"].astype(str).str.strip().str.lower()
    df["category"] = df["category"].astype(str).str.strip()
    df["priority"] = df["priority"].astype(str).str.strip()
    return df


def _query_gsc(service, start_date, end_date, dimensions, row_limit=1000, search_type="web"):
    """Generic GSC searchanalytics query. Returns raw rows list."""
    try:
        request = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": dimensions,
            "rowLimit": row_limit,
            "type": search_type,
        }
        response = service.searchanalytics().query(
            siteUrl=SITE_URL, body=request
        ).execute()
        return response.get("rows", [])
    except Exception as e:
        print(f"  GSC query failed ({dimensions}, {search_type}): {e}")
        return []


def fetch_query_data(service, start_date, end_date, row_limit=1000):
    """Fetch query-level data for tracked keyword matching."""
    rows = _query_gsc(service, start_date, end_date, ["query"], row_limit)
    data = [
        {
            "query":       str(r["keys"][0]).strip().lower(),
            "clicks":      r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr":         r.get("ctr", 0),
            "position":    r.get("position", 0),
        }
        for r in rows
    ]
    if not data:
        return pd.DataFrame(columns=["query", "clicks", "impressions", "ctr", "position"])
    return pd.DataFrame(data)


def fetch_page_data(service, start_date, end_date, row_limit=1000):
    """Fetch query+page data — links each keyword to its ranking URL."""
    rows = _query_gsc(service, start_date, end_date, ["query", "page"], row_limit)
    data = [
        {
            "query":       str(r["keys"][0]).strip().lower(),
            "page":        str(r["keys"][1]).strip(),
            "clicks":      r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr":         r.get("ctr", 0),
            "position":    r.get("position", 0),
        }
        for r in rows
    ]
    if not data:
        return pd.DataFrame(columns=["query", "page", "clicks", "impressions", "ctr", "position"])
    return pd.DataFrame(data)


def fetch_device_data(service, start_date, end_date, row_limit=1000):
    """Fetch device-split data (DESKTOP / MOBILE / TABLET)."""
    rows = _query_gsc(service, start_date, end_date, ["device"], row_limit)
    data = [
        {
            "device":      str(r["keys"][0]).upper(),
            "clicks":      r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr":         r.get("ctr", 0),
            "position":    r.get("position", 0),
        }
        for r in rows
    ]
    if not data:
        return pd.DataFrame(columns=["device", "clicks", "impressions", "ctr", "position"])
    return pd.DataFrame(data)


def fetch_country_data(service, start_date, end_date, row_limit=50):
    """Fetch top countries by impressions."""
    rows = _query_gsc(service, start_date, end_date, ["country"], row_limit)
    data = [
        {
            "country":     str(r["keys"][0]).upper(),
            "clicks":      r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr":         r.get("ctr", 0),
            "position":    r.get("position", 0),
        }
        for r in rows
    ]
    if not data:
        return pd.DataFrame(columns=["country", "clicks", "impressions", "ctr", "position"])
    df = pd.DataFrame(data)
    for col in ["clicks", "impressions", "ctr", "position"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df.sort_values("impressions", ascending=False).head(15)


def fetch_discover_data(service, start_date, end_date, row_limit=200):
    """Fetch Google Discover performance (searchType=discover)."""
    rows = _query_gsc(service, start_date, end_date, ["page"], row_limit, search_type="discover")
    data = [
        {
            "page":        str(r["keys"][0]).strip(),
            "clicks":      r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr":         r.get("ctr", 0),
        }
        for r in rows
    ]
    if not data:
        return pd.DataFrame(columns=["page", "clicks", "impressions", "ctr"])
    df = pd.DataFrame(data)
    for col in ["clicks", "impressions", "ctr"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df.sort_values("impressions", ascending=False)


# ══════════════════════════════════════════════════════════════════════════════
# DATA PROCESSING
# ══════════════════════════════════════════════════════════════════════════════


def build_keyword_snapshot(tracked_df, query_df):
    merged = pd.merge(
        tracked_df,
        query_df,
        left_on="keyword",
        right_on="query",
        how="left"
    )

    merged["clicks"] = pd.to_numeric(merged["clicks"], errors="coerce").fillna(0)
    merged["impressions"] = pd.to_numeric(merged["impressions"], errors="coerce").fillna(0)
    merged["ctr"] = pd.to_numeric(merged["ctr"], errors="coerce").fillna(0)
    merged["position"] = pd.to_numeric(merged["position"], errors="coerce").fillna(0)

    return merged[["keyword", "category", "priority", "clicks", "impressions", "ctr", "position"]]


def prepare_comparison(current_df, previous_df):
    current_df = current_df.rename(columns={
        "clicks": "clicks_current",
        "impressions": "impressions_current",
        "ctr": "ctr_current",
        "position": "position_current",
    })

    previous_df = previous_df.rename(columns={
        "clicks": "clicks_previous",
        "impressions": "impressions_previous",
        "ctr": "ctr_previous",
        "position": "position_previous",
    })

    merged = pd.merge(
        current_df,
        previous_df,
        on=["keyword", "category", "priority"],
        how="outer"
    )

    for col in ["clicks_current", "impressions_current", "ctr_current", "position_current",
                "clicks_previous", "impressions_previous", "ctr_previous", "position_previous"]:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)

    merged["clicks_change"] = merged["clicks_current"] - merged["clicks_previous"]
    merged["impressions_change"] = merged["impressions_current"] - merged["impressions_previous"]
    merged["ctr_change"] = merged["ctr_current"] - merged["ctr_previous"]
    merged["position_change"] = merged["position_current"] - merged["position_previous"]

    merged["ranking_improved"] = (
        (merged["position_previous"] > 0) &
        (merged["position_current"] > 0) &
        (merged["position_current"] < merged["position_previous"])
    )
    merged["ranking_declined"] = (
        (merged["position_previous"] > 0) &
        (merged["position_current"] > 0) &
        (merged["position_current"] > merged["position_previous"])
    )
    merged["newly_visible"] = (
        (merged["impressions_previous"] == 0) &
        (merged["impressions_current"] > 0)
    )
    merged["lost_visibility"] = (
        (merged["impressions_previous"] > 0) &
        (merged["impressions_current"] == 0)
    )
    merged["entered_top_3"] = (
        (merged["position_current"] > 0) &
        (merged["position_current"] <= 3) &
        ((merged["position_previous"] == 0) | (merged["position_previous"] > 3))
    )
    merged["entered_top_10"] = (
        (merged["position_current"] > 0) &
        (merged["position_current"] <= 10) &
        ((merged["position_previous"] == 0) | (merged["position_previous"] > 10))
    )

    return merged.sort_values(
        by=["priority", "clicks_current", "impressions_current"],
        ascending=[True, False, False]
    )


def enrich_with_pages(comparison_df, page_df):
    """Join the top-ranking page URL onto each tracked keyword."""
    if page_df.empty:
        comparison_df["top_page"] = ""
        return comparison_df
    # Keep the highest-click page per query
    best_page = (
        page_df.sort_values("clicks", ascending=False)
        .drop_duplicates(subset="query")
        [["query", "page"]]
        .rename(columns={"page": "top_page"})
    )
    merged = pd.merge(comparison_df, best_page, left_on="keyword", right_on="query", how="left")
    merged["top_page"] = merged["top_page"].fillna("")
    return merged.drop(columns=["query"], errors="ignore")


def build_click_potential_gap(comparison_df):
    """
    Keywords ranked 4–10 with ≥100 impressions and CTR < 5%.
    These are the highest-ROI optimisation targets — one position improvement
    can double clicks.
    """
    gap = comparison_df[
        (comparison_df["position_current"] >= 4) &
        (comparison_df["position_current"] <= 10) &
        (comparison_df["impressions_current"] >= 100) &
        (comparison_df["ctr_current"] < 0.05) &
        (comparison_df["position_current"] > 0)
    ].copy()
    gap["click_potential"] = (gap["impressions_current"] * 0.10).round(0).astype(int)
    return gap.sort_values("impressions_current", ascending=False)




# ══════════════════════════════════════════════════════════════════════════════
# AI ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def build_deterministic_bullets(comparison_df, device_df=None, country_df=None, discover_df=None):
    """Hard metric facts — always present even if AI fails."""
    bullets = []

    visible_now  = comparison_df[comparison_df["impressions_current"] > 0]
    visible_prev = comparison_df[comparison_df["impressions_previous"] > 0]
    improved     = comparison_df[comparison_df["ranking_improved"]]
    declined     = comparison_df[comparison_df["ranking_declined"]]
    entered_top_3  = comparison_df[comparison_df["entered_top_3"]]
    entered_top_10 = comparison_df[comparison_df["entered_top_10"]]
    lost_vis       = comparison_df[comparison_df["lost_visibility"]]
    newly_vis      = comparison_df[comparison_df["newly_visible"]]

    vis_change = len(visible_now) - len(visible_prev)
    vis_sign   = "+" if vis_change >= 0 else ""
    bullets.append(
        f"{len(visible_now)} tracked keywords generated visibility this week "
        f"({vis_sign}{vis_change} WoW)."
    )

    if len(improved) > len(declined):
        bullets.append(
            f"Ranking movement was net positive: {len(improved)} keywords improved vs "
            f"{len(declined)} that declined."
        )
    elif len(improved) < len(declined):
        bullets.append(
            f"Ranking movement was net negative: {len(declined)} keywords declined vs "
            f"{len(improved)} that improved."
        )
    else:
        bullets.append(
            f"Ranking movement was balanced: {len(improved)} improved, {len(declined)} declined."
        )

    if not entered_top_3.empty:
        kws = ", ".join(entered_top_3["keyword"].head(3).tolist())
        bullets.append(f"{len(entered_top_3)} keyword(s) entered the top 3 this week: {kws}.")
    if not entered_top_10.empty:
        bullets.append(f"{len(entered_top_10)} keyword(s) moved onto page 1 (top 10) this week.")
    if not newly_vis.empty:
        bullets.append(f"{len(newly_vis)} keyword(s) gained new visibility this week.")
    if not lost_vis.empty:
        bullets.append(f"{len(lost_vis)} keyword(s) lost all visibility week over week.")

    high_priority = comparison_df[comparison_df["priority"].str.lower() == "high"]
    if not high_priority.empty:
        avg_pos = high_priority.loc[high_priority["position_current"] > 0, "position_current"]
        if not avg_pos.empty:
            bullets.append(
                f"High-priority keywords averaged position {avg_pos.mean():.1f} this week."
            )

    # CTR efficiency — keywords with >200 impressions but <2% CTR
    opportunity = comparison_df[
        (comparison_df["impressions_current"] >= 200) &
        (comparison_df["ctr_current"] < 0.02) &
        (comparison_df["position_current"] > 0)
    ]
    if not opportunity.empty:
        bullets.append(
            f"{len(opportunity)} keyword(s) have 200+ impressions but sub-2% CTR — "
            "title/meta optimisation opportunity."
        )

    # Click potential gap — page 1 keywords with room to grow
    gap = build_click_potential_gap(comparison_df)
    if not gap.empty:
        bullets.append(
            f"{len(gap)} keyword(s) sit on page 1 (pos 4–10) with <5% CTR — "
            f"estimated {gap['click_potential'].sum():,} additional clicks available with title optimisation."
        )

    # Device insight
    if device_df is not None and not device_df.empty:
        mobile = device_df[device_df["device"] == "MOBILE"]
        desktop = device_df[device_df["device"] == "DESKTOP"]
        if not mobile.empty and not desktop.empty:
            mob_pos  = float(mobile["position"].iloc[0])
            desk_pos = float(desktop["position"].iloc[0])
            gap_val  = mob_pos - desk_pos
            if abs(gap_val) >= 1.5:
                direction = "worse" if gap_val > 0 else "better"
                bullets.append(
                    f"Mobile average position ({mob_pos:.1f}) is {abs(gap_val):.1f} positions "
                    f"{direction} than desktop ({desk_pos:.1f}) — "
                    f"{'mobile optimisation needed' if gap_val > 0 else 'strong mobile performance'}."
                )

    # Country insight — flag if top market is dominant
    if country_df is not None and not country_df.empty:
        total_impr = country_df["impressions"].sum()
        top_country = country_df.iloc[0]
        share = top_country["impressions"] / total_impr if total_impr > 0 else 0
        if share >= 0.6:
            bullets.append(
                f"{top_country['country']} accounts for {share:.0%} of total impressions — "
                "traffic is highly concentrated in one market."
            )

    # Discover insight
    if discover_df is not None and not discover_df.empty:
        disc_clicks = int(discover_df["clicks"].sum())
        disc_impr   = int(discover_df["impressions"].sum())
        if disc_impr > 0:
            bullets.append(
                f"Google Discover generated {disc_impr:,} impressions and {disc_clicks:,} clicks "
                f"across {len(discover_df)} page(s) this week."
            )

    return bullets


def build_ai_bullets(comparison_df, current_start, current_end, previous_start, previous_end,
                     device_df=None, country_df=None, discover_df=None):
    """AI-generated interpretation bullets. Returns [] on failure."""
    if not GROQ_API_KEY:
        return []

    top_table = comparison_df[[
        "keyword", "category", "priority", "clicks_current", "impressions_current",
        "position_current", "clicks_change", "position_change"
    ]].head(15)

    # Build optional context snippets
    device_ctx = ""
    if device_df is not None and not device_df.empty:
        device_ctx = f"\nDevice split:\n{device_df[['device','clicks','impressions','position']].to_csv(index=False)}"

    country_ctx = ""
    if country_df is not None and not country_df.empty:
        country_ctx = f"\nTop countries:\n{country_df.head(5)[['country','clicks','impressions']].to_csv(index=False)}"

    discover_ctx = ""
    if discover_df is not None and not discover_df.empty:
        disc_total = int(discover_df["impressions"].sum())
        discover_ctx = f"\nGoogle Discover: {disc_total:,} total impressions across {len(discover_df)} pages."

    prompt = f"""
You are writing concise executive bullet points for a weekly keyword ranking report.

Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.
Each bullet is one sentence. Maximum 6 bullets total.
Do not invent data. Do not mention AI, models, or automation.
Focus on ranking movement, visibility changes, device/country patterns, risks, and recommended actions.
Write as if this is part of a manually produced executive report.

Current period: {current_start} to {current_end}
Previous period: {previous_start} to {previous_end}

Tracked keyword data:
{top_table.to_csv(index=False)}{device_ctx}{country_ctx}{discover_ctx}
"""

    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write polished weekly executive SEO briefs as bullet points only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        raw = response.choices[0].message.content.strip()
        bullets = []
        for line in raw.splitlines():
            clean = line.strip().lstrip("-*+•·▪▸").replace("**", "").replace("__", "").replace("*", "").strip()
            if clean:
                bullets.append(clean)
        return bullets
    except Exception:
        return []


def build_unified_executive_bullets(comparison_df, current_start, current_end, previous_start, previous_end,
                                    device_df=None, country_df=None, discover_df=None):
    """Deterministic bullets first, AI bullets appended. Always returns a non-empty list."""
    det = build_deterministic_bullets(comparison_df, device_df, country_df, discover_df)
    ai  = build_ai_bullets(comparison_df, current_start, current_end, previous_start, previous_end,
                           device_df, country_df, discover_df)
    return det + ai


# ══════════════════════════════════════════════════════════════════════════════
# HTML TABLE BUILDERS
# ══════════════════════════════════════════════════════════════════════════════




def _style_ax(ax, title="", xlabel="", ylabel=""):
    """Shared axes styling — matches REPORT_DESIGN_PRINCIPLES.md §6."""
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
    """Save figure with standard settings and close it."""
    path = CHARTS_DIR / name
    fig.patch.set_facecolor("white")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path.absolute())


def _placeholder(name):
    """Return a clean 'no data' placeholder chart."""
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    ax.text(0.5, 0.5, "No data available for this period.",
            ha="center", va="center", fontsize=12, color="#94A3B8",
            transform=ax.transAxes)
    ax.set_axis_off()
    return _save(fig, name)


# ══════════════════════════════════════════════════════════════════════════════
# CHART GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def chart_kpi_overview(comparison_df):
    """Paired bar chart: current vs previous for 4 KPI buckets."""
    if comparison_df.empty:
        return _placeholder("kw_kpi_overview.png")

    visible_now  = int((comparison_df["impressions_current"] > 0).sum())
    visible_prev = int((comparison_df["impressions_previous"] > 0).sum())
    improved     = int(comparison_df["ranking_improved"].sum())
    declined     = int(comparison_df["ranking_declined"].sum())
    top10_curr   = int((comparison_df["position_current"].between(1, 10, inclusive="both")).sum())
    top10_prev   = int((comparison_df["position_previous"].between(1, 10, inclusive="both")).sum())
    top3_curr    = int((comparison_df["position_current"].between(1, 3, inclusive="both")).sum())
    top3_prev    = int((comparison_df["position_previous"].between(1, 3, inclusive="both")).sum())

    labels   = ["Visible", "Improved", "Declined", "Top 10", "Top 3"]
    curr_vals = [visible_now, improved, declined, top10_curr, top3_curr]
    prev_vals = [visible_prev, 0, 0, top10_prev, top3_prev]

    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars_prev = ax.bar(x - 0.2, prev_vals, width=0.38, color=C_SLATE, label="Previous", zorder=2)
    bars_curr = ax.bar(x + 0.2, curr_vals, width=0.38, color=C_NAVY, label="Current", zorder=2)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Keyword Visibility & Ranking Movement")

    max_v = max(curr_vals + prev_vals, default=1)
    for bar in list(bars_prev) + list(bars_curr):
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, h * 1.03,
                    f"{int(h)}", ha="center", va="bottom", fontsize=8,
                    color="#374151", fontweight="600")
    ax.set_ylim(0, max_v * 1.22)
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_kpi_overview.png")


def chart_position_band_distribution(comparison_df):
    """Horizontal stacked bar showing how keywords are distributed across SERP bands."""
    visible = comparison_df[comparison_df["position_current"] > 0].copy()
    if visible.empty:
        return _placeholder("kw_position_bands.png")

    def band(pos):
        if pos <= 3:   return "Top 3"
        if pos <= 10:  return "Page 1 (4–10)"
        if pos <= 20:  return "Page 2"
        return "Page 3+"

    visible["band"] = visible["position_current"].apply(band)
    counts = visible["band"].value_counts()
    order  = ["Top 3", "Page 1 (4–10)", "Page 2", "Page 3+"]
    colors = [C_GREEN, C_NAVY, C_AMBER, C_CORAL]

    fig, ax = plt.subplots(figsize=(13, 4.8))
    left = 0
    total = counts.sum()
    for band_name, color in zip(order, colors):
        val = counts.get(band_name, 0)
        if val == 0:
            continue
        bar = ax.barh(["Keywords"], [val], left=left, color=color, label=band_name, height=0.45)
        pct = val / total * 100
        if pct >= 5:
            ax.text(left + val / 2, 0, f"{val}\n({pct:.0f}%)",
                    ha="center", va="center", fontsize=9, color="white", fontweight="600")
        left += val

    ax.legend(loc="lower right", frameon=False, fontsize=8, ncol=4)
    ax.set_xlim(0, total * 1.05)
    ax.set_yticks([])
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="SERP Position Band Distribution")
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_position_bands.png")


def chart_top_keywords_clicks(top_df):
    """Horizontal bar — top keywords by clicks with inline value labels."""
    if top_df.empty:
        return _placeholder("kw_top_clicks.png")

    df = top_df.head(10).copy().iloc[::-1]
    df["label"] = df["keyword"].apply(lambda k: short_url(k, 40))
    max_v = df["clicks_current"].max() or 1

    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["label"], df["clicks_current"], color=C_TEAL, zorder=2)
    for bar in bars:
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Tracked Keywords — Clicks")
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_top_clicks.png")


def chart_top_keywords_impressions(top_df):
    """Horizontal bar — top keywords by impressions."""
    if top_df.empty:
        return _placeholder("kw_top_impressions.png")

    df = top_df.head(10).copy().iloc[::-1]
    df["label"] = df["keyword"].apply(lambda k: short_url(k, 40))
    max_v = df["impressions_current"].max() or 1

    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["label"], df["impressions_current"], color=C_NAVY, zorder=2)
    for bar in bars:
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Tracked Keywords — Impressions")
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_top_impressions.png")


def chart_lollipop_movers(gainers_df, losers_df):
    """Lollipop chart showing ranking winners (teal) and losers (coral) on one axis."""
    g = gainers_df.head(6).copy()
    l = losers_df.head(6).copy()
    if g.empty and l.empty:
        return _placeholder("kw_movers.png")

    g["delta"] = (g["position_previous"] - g["position_current"]).abs()
    l["delta"] = -(l["position_current"] - l["position_previous"]).abs()
    g["label"] = g["keyword"].apply(lambda k: short_url(k, 38))
    l["label"] = l["keyword"].apply(lambda k: short_url(k, 38))

    plot_df = pd.concat([
        g[["label", "delta"]],
        l[["label", "delta"]],
    ], ignore_index=True).sort_values("delta")

    colors = [C_TEAL if v > 0 else C_CORAL for v in plot_df["delta"]]

    fig, ax = plt.subplots(figsize=(13, 4.8))

    # Shaded halves
    ax.axhspan(-0.5, len(plot_df) - 0.5, xmin=0, xmax=0.5, color=C_CORAL, alpha=0.04, zorder=0)
    ax.axhspan(-0.5, len(plot_df) - 0.5, xmin=0.5, xmax=1.0, color=C_TEAL, alpha=0.04, zorder=0)
    ax.axvline(0, color="#888", linewidth=0.8, zorder=1)

    for i, (_, row) in enumerate(plot_df.iterrows()):
        color = C_TEAL if row["delta"] > 0 else C_CORAL
        ax.plot([0, row["delta"]], [i, i], color=color, linewidth=1.5, zorder=2)
        ax.scatter([row["delta"]], [i], color=color, s=60, zorder=3)

    ax.set_yticks(range(len(plot_df)))
    ax.set_yticklabels(plot_df["label"], fontsize=8)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)

    gain_patch = mpatches.Patch(color=C_TEAL, label="Improved")
    loss_patch = mpatches.Patch(color=C_CORAL, label="Declined")
    ax.legend(handles=[gain_patch, loss_patch], frameon=False, fontsize=8, loc="lower right")

    _style_ax(ax, title="Ranking Winners & Losers (Position Change)")
    ax.set_xlabel("Position change (positive = improved)", fontsize=8, color="#64748B")
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_movers.png")


def chart_ctr_efficiency(comparison_df):
    """Scatter: impressions vs CTR, sized by clicks. Highlights low-CTR opportunities."""
    visible = comparison_df[
        (comparison_df["impressions_current"] > 0) &
        (comparison_df["position_current"] > 0)
    ].copy()
    if visible.empty:
        return _placeholder("kw_ctr_efficiency.png")

    visible["label"] = visible["keyword"].apply(lambda k: short_url(k, 30))
    sizes = np.clip(visible["clicks_current"] * 8, 30, 600)

    fig, ax = plt.subplots(figsize=(13, 4.8))

    # Opportunity zone: high impressions, low CTR
    ax.axhspan(0, 0.02, color=C_CORAL, alpha=0.06, zorder=0, label="Low CTR zone (<2%)")
    ax.axhspan(0.05, 1.0, color=C_GREEN, alpha=0.04, zorder=0, label="Strong CTR zone (>5%)")

    scatter = ax.scatter(
        visible["impressions_current"],
        visible["ctr_current"],
        s=sizes,
        c=visible["position_current"],
        cmap="RdYlGn_r",
        alpha=0.75,
        edgecolors="white",
        linewidths=0.5,
        zorder=2,
    )

    cbar = fig.colorbar(scatter, ax=ax, pad=0.01)
    cbar.set_label("Avg Position", fontsize=8, color="#64748B")
    cbar.ax.tick_params(labelsize=7)

    # Annotate top 5 by impressions
    top5 = visible.nlargest(5, "impressions_current")
    for _, row in top5.iterrows():
        ax.annotate(row["label"],
                    xy=(row["impressions_current"], row["ctr_current"]),
                    xytext=(6, 4), textcoords="offset points",
                    fontsize=7, color="#374151")

    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.grid(linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.legend(frameon=False, fontsize=7, loc="upper right")
    _style_ax(ax, title="CTR Efficiency — Impressions vs Click-Through Rate",
              xlabel="Impressions", ylabel="CTR")
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_ctr_efficiency.png")


def chart_category_impressions(comparison_df):
    """Horizontal bar — impression share by content category."""
    visible = comparison_df[comparison_df["impressions_current"] > 0].copy()
    if visible.empty or "category" not in visible.columns:
        return _placeholder("kw_category_impressions.png")

    cat_df = (
        visible.groupby("category")["impressions_current"]
        .sum()
        .sort_values(ascending=True)
        .reset_index()
    )
    if cat_df.empty:
        return _placeholder("kw_category_impressions.png")

    max_v = cat_df["impressions_current"].max() or 1
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(cat_df["category"], cat_df["impressions_current"], color=C_NAVY, zorder=2)
    for bar in bars:
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Impressions by Content Category")
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_category_impressions.png")


def chart_device_split(device_df):
    """
    Side-by-side grouped bar: clicks and impressions by device.
    Shows desktop vs mobile vs tablet performance at a glance.
    """
    if device_df is None or device_df.empty:
        return _placeholder("kw_device_split.png")

    df = device_df.copy()
    for col in ["clicks", "impressions", "position"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    order  = ["DESKTOP", "MOBILE", "TABLET"]
    colors = [C_NAVY, C_TEAL, C_SLATE]
    df["device"] = pd.Categorical(df["device"], categories=order, ordered=True)
    df = df.sort_values("device").reset_index(drop=True)

    x = np.arange(len(df))
    fig, ax1 = plt.subplots(figsize=(13, 4.8))
    ax2 = ax1.twinx()

    w = 0.35
    bars_c = ax1.bar(x - w / 2, df["clicks"],      width=w, color=C_NAVY,  label="Clicks",      zorder=2)
    bars_i = ax2.bar(x + w / 2, df["impressions"], width=w, color=C_TEAL,  label="Impressions", alpha=0.75, zorder=2)

    # Value labels
    max_c = df["clicks"].max() or 1
    max_i = df["impressions"].max() or 1
    for bar in bars_c:
        h = bar.get_height()
        if h > 0:
            ax1.text(bar.get_x() + bar.get_width() / 2, h * 1.03,
                     f"{int(h):,}", ha="center", va="bottom", fontsize=8, color="#374151", fontweight="600")
    for bar in bars_i:
        h = bar.get_height()
        if h > 0:
            ax2.text(bar.get_x() + bar.get_width() / 2, h * 1.03,
                     f"{int(h):,}", ha="center", va="bottom", fontsize=8, color=C_TEAL, fontweight="600")

    # Position dots on secondary axis (reuse ax2 scale)
    for i, row in df.iterrows():
        if row["position"] > 0:
            ax2.plot(i, row["position"] * (max_i / (df["position"].max() or 1)),
                     marker="D", color=C_CORAL, markersize=7, zorder=4,
                     label="Avg Position" if i == 0 else "")

    ax1.set_xticks(x)
    ax1.set_xticklabels([d.title() for d in df["device"]])
    ax1.set_ylim(0, max_c * 1.3)
    ax2.set_ylim(0, max_i * 1.3)
    ax1.set_ylabel("Clicks", fontsize=8, color="#64748B")
    ax2.set_ylabel("Impressions", fontsize=8, color="#64748B")
    ax1.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, frameon=False, fontsize=8, loc="upper right")

    _style_ax(ax1, title="Performance by Device")
    ax2.tick_params(labelsize=8, colors="#64748B", length=0)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_color(C_BORDER)
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_device_split.png")


def chart_country_top10(country_df):
    """Horizontal bar — top countries by impressions with CTR annotation."""
    if country_df is None or country_df.empty:
        return _placeholder("kw_country_top10.png")

    df = country_df.head(10).copy()
    for col in ["clicks", "impressions", "ctr"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df = df.sort_values("impressions", ascending=True)

    max_v = df["impressions"].max() or 1
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["country"], df["impressions"], color=C_NAVY, zorder=2)
    for bar, (_, row) in zip(bars, df.iterrows()):
        v = bar.get_width()
        ctr_str = f"{row['ctr']:.1%}"
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}  CTR {ctr_str}", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.35)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Countries by Impressions")
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_country_top10.png")


def chart_click_potential_gap(comparison_df):
    """
    Horizontal bar — page 1 keywords (pos 4–10) with <5% CTR.
    Bar = impressions, annotated with current position and estimated click gain.
    """
    gap_df = build_click_potential_gap(comparison_df).head(12)
    if gap_df.empty:
        return _placeholder("kw_click_potential.png")

    df = gap_df.sort_values("impressions_current", ascending=True).copy()
    df["label"] = df["keyword"].apply(lambda k: short_url(k, 38))
    max_v = df["impressions_current"].max() or 1

    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["label"], df["impressions_current"], color=C_AMBER, zorder=2)
    for bar, (_, row) in zip(bars, df.iterrows()):
        v = bar.get_width()
        ax.text(
            v + max_v * 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"Pos {row['position_current']:.1f} · CTR {row['ctr_current']:.1%} · +{row['click_potential']:,} est. clicks",
            va="center", fontsize=7.5, color="#374151",
        )
    ax.set_xlim(0, max_v * 1.55)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Click Potential Gap — Page 1 Keywords with Low CTR (pos 4–10, CTR <5%)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_click_potential.png")


def chart_discover_top_pages(discover_df):
    """Horizontal bar — top pages by Discover impressions."""
    if discover_df is None or discover_df.empty:
        return _placeholder("kw_discover.png")

    df = discover_df.head(10).copy()
    df["label"] = df["page"].apply(lambda p: short_url(p, 45))
    df = df.sort_values("impressions", ascending=True)
    max_v = df["impressions"].max() or 1

    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["label"], df["impressions"], color=C_TEAL, zorder=2)
    for bar, (_, row) in zip(bars, df.iterrows()):
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}  {row['clicks']:.0f} clicks", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.35)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Google Discover — Top Pages by Impressions")
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_discover.png")


def chart_keyword_page_table_chart(comparison_df):
    """
    Horizontal bar showing top keywords coloured by their top_page.
    Only rendered when page data is available (top_page column populated).
    """
    if "top_page" not in comparison_df.columns:
        return None
    df = comparison_df[
        (comparison_df["impressions_current"] > 0) &
        (comparison_df["top_page"] != "")
    ].sort_values("impressions_current", ascending=False).head(12).copy()
    if df.empty:
        return None

    # Assign a colour per unique page (up to 8 pages, rest = slate)
    pages  = df["top_page"].unique()
    palette = [C_NAVY, C_TEAL, C_CORAL, C_AMBER, C_GREEN, C_SLATE, "#7C3AED", "#DB2777"]
    page_color = {p: palette[i % len(palette)] for i, p in enumerate(pages)}

    df["label"]  = df["keyword"].apply(lambda k: short_url(k, 38))
    df["color"]  = df["top_page"].map(page_color)
    df["pg_lbl"] = df["top_page"].apply(lambda p: short_url(p, 30))
    df = df.sort_values("impressions_current", ascending=True)

    max_v = df["impressions_current"].max() or 1
    fig, ax = plt.subplots(figsize=(13, 4.8))
    for _, row in df.iterrows():
        ax.barh(row["label"], row["impressions_current"], color=row["color"], zorder=2)
        ax.text(row["impressions_current"] + max_v * 0.01,
                df.index.get_loc(_) if hasattr(df.index, "get_loc") else 0,
                row["pg_lbl"], va="center", fontsize=7, color="#374151")

    # Re-draw with proper y positions
    ax.cla()
    y_pos = range(len(df))
    for i, (_, row) in enumerate(df.iterrows()):
        ax.barh(i, row["impressions_current"], color=row["color"], zorder=2)
        ax.text(row["impressions_current"] + max_v * 0.01, i,
                row["pg_lbl"], va="center", fontsize=7, color="#374151")
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(df["label"].tolist(), fontsize=8)
    ax.set_xlim(0, max_v * 1.45)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Keywords by Impressions — Coloured by Landing Page")
    fig.tight_layout(pad=2.0)
    return _save(fig, "kw_keyword_pages.png")


def build_all_charts(comparison_df, device_df=None, country_df=None, discover_df=None):
    """Build all charts and return a dict of {name: path}."""
    top_keywords    = comparison_df.sort_values(
        by=["clicks_current", "impressions_current"], ascending=[False, False]
    ).head(15)
    biggest_gainers = comparison_df[comparison_df["ranking_improved"]].sort_values(
        by="position_change", ascending=True
    ).head(10)
    biggest_losers  = comparison_df[comparison_df["ranking_declined"]].sort_values(
        by="position_change", ascending=False
    ).head(10)

    charts = {
        "kpi_overview":         chart_kpi_overview(comparison_df),
        "position_bands":       chart_position_band_distribution(comparison_df),
        "top_clicks":           chart_top_keywords_clicks(top_keywords),
        "top_impressions":      chart_top_keywords_impressions(top_keywords),
        "movers":               chart_lollipop_movers(biggest_gainers, biggest_losers),
        "ctr_efficiency":       chart_ctr_efficiency(comparison_df),
        "category_impressions": chart_category_impressions(comparison_df),
        "click_potential":      chart_click_potential_gap(comparison_df),
        "device_split":         chart_device_split(device_df),
        "country_top10":        chart_country_top10(country_df),
        "discover":             chart_discover_top_pages(discover_df),
        "keyword_pages":        chart_keyword_page_table_chart(comparison_df),
    }
    return charts


# ══════════════════════════════════════════════════════════════════════════════
# REPORT BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def _tbl(df, cols, rename):
    return html_table_from_df(df, cols, rename) if not df.empty else "<p>No data.</p>"


def write_markdown_summary(comparison_df, exec_bullets, current_start, current_end, previous_start, previous_end):
    top_keywords    = comparison_df.sort_values(by=["clicks_current", "impressions_current"], ascending=[False, False]).head(15)
    biggest_gainers = comparison_df[comparison_df["ranking_improved"]].sort_values(by="position_change", ascending=True).head(15)
    biggest_losers  = comparison_df[comparison_df["ranking_declined"]].sort_values(by="position_change", ascending=False).head(15)
    entered_top_3   = comparison_df[comparison_df["entered_top_3"]].head(15)
    entered_top_10  = comparison_df[comparison_df["entered_top_10"]].head(15)
    lost_visibility = comparison_df[comparison_df["lost_visibility"]].head(15)

    def md_tbl(df, columns, rename_map=None):
        work = df[columns].copy()
        if rename_map:
            work = work.rename(columns=rename_map)
        for col in work.columns:
            lc = col.lower()
            if "ctr" in lc:
                work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.2%}" if pd.notnull(x) else "")
            elif "position" in lc and "change" not in lc and "δ" not in lc:
                work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.2f}" if pd.notnull(x) and x != 0 else "")
            elif "change" in lc or "δ" in lc:
                work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x, decimals=2) if pd.notnull(x) else "")
            elif any(t in lc for t in ["click", "impression"]):
                work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.0f}" if pd.notnull(x) else "")
            else:
                work[col] = work[col].fillna("").astype(str)
        header = "| " + " | ".join(work.columns) + " |"
        sep    = "| " + " | ".join(["---"] * len(work.columns)) + " |"
        rows   = ["| " + " | ".join(str(v) for v in row) + " |" for row in work.values.tolist()]
        return "\n".join([header, sep] + rows)

    lines = []
    lines.append("# Weekly Keyword Ranking Review")
    lines.append("")
    lines.append(f"**Period:** {current_start} → {current_end} | **Previous:** {previous_start} → {previous_end}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    for b in exec_bullets:
        lines.append(f"- {b}")
    lines.append("")
    lines.append("## Top Tracked Keywords")
    lines.append("")
    lines.append(md_tbl(top_keywords,
        ["keyword", "category", "priority", "clicks_current", "impressions_current", "position_current", "position_change"],
        {"keyword": "Keyword", "category": "Category", "priority": "Priority",
         "clicks_current": "Clicks", "impressions_current": "Impressions",
         "position_current": "Position", "position_change": "WoW Δ"}))
    lines.append("")
    lines.append("## Biggest Ranking Improvements")
    lines.append("")
    lines.append(md_tbl(biggest_gainers,
        ["keyword", "position_previous", "position_current", "position_change", "clicks_current"],
        {"keyword": "Keyword", "position_previous": "Prev", "position_current": "Current",
         "position_change": "Δ", "clicks_current": "Clicks"}))
    lines.append("")
    lines.append("## Biggest Ranking Declines")
    lines.append("")
    lines.append(md_tbl(biggest_losers,
        ["keyword", "position_previous", "position_current", "position_change", "clicks_current"],
        {"keyword": "Keyword", "position_previous": "Prev", "position_current": "Current",
         "position_change": "Δ", "clicks_current": "Clicks"}))
    lines.append("")
    lines.append("## Entered Top 3")
    lines.append("")
    lines.append(md_tbl(entered_top_3,
        ["keyword", "category", "priority", "position_previous", "position_current"],
        {"keyword": "Keyword", "category": "Category", "priority": "Priority",
         "position_previous": "Prev", "position_current": "Current"}))
    lines.append("")
    lines.append("## Entered Top 10")
    lines.append("")
    lines.append(md_tbl(entered_top_10,
        ["keyword", "category", "priority", "position_previous", "position_current"],
        {"keyword": "Keyword", "category": "Category", "priority": "Priority",
         "position_previous": "Prev", "position_current": "Current"}))
    lines.append("")
    lines.append("## Lost Visibility")
    lines.append("")
    lines.append(md_tbl(lost_visibility,
        ["keyword", "category", "priority", "impressions_previous", "impressions_current"],
        {"keyword": "Keyword", "category": "Category", "priority": "Priority",
         "impressions_previous": "Prev Impr", "impressions_current": "Curr Impr"}))

    with open("keyword_ranking_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_html_summary(comparison_df, exec_bullets, chart_paths, current_start, current_end, previous_start, previous_end,
                       device_df=None, country_df=None, discover_df=None):
    top_keywords    = comparison_df.sort_values(by=["clicks_current", "impressions_current"], ascending=[False, False]).head(15)
    biggest_gainers = comparison_df[comparison_df["ranking_improved"]].sort_values(by="position_change", ascending=True).head(15)
    biggest_losers  = comparison_df[comparison_df["ranking_declined"]].sort_values(by="position_change", ascending=False).head(15)
    entered_top_3   = comparison_df[comparison_df["entered_top_3"]].head(15)
    entered_top_10  = comparison_df[comparison_df["entered_top_10"]].head(15)
    lost_visibility = comparison_df[comparison_df["lost_visibility"]].head(15)
    gap_df          = build_click_potential_gap(comparison_df).head(15)

    visible_now    = int((comparison_df["impressions_current"] > 0).sum())
    visible_prev   = int((comparison_df["impressions_previous"] > 0).sum())
    improved_count = int(comparison_df["ranking_improved"].sum())
    declined_count = int(comparison_df["ranking_declined"].sum())
    avg_pos_curr   = comparison_df.loc[comparison_df["position_current"] > 0, "position_current"].mean()
    avg_pos_prev   = comparison_df.loc[comparison_df["position_previous"] > 0, "position_previous"].mean()
    avg_pos_curr   = 0.0 if pd.isna(avg_pos_curr) else float(avg_pos_curr)
    avg_pos_prev   = 0.0 if pd.isna(avg_pos_prev) else float(avg_pos_prev)

    def _img(key, alt):
        path = chart_paths.get(key)
        return mm_chart_wrap(path, alt) if path else ""

    def _row2(key_a, alt_a, key_b, alt_b):
        """Render two charts stacked full-width (no side-by-side columns)."""
        return _img(key_a, alt_a) + _img(key_b, alt_b)

    kpi_grid = mm_kpi_grid(
        mm_kpi_card("Visible Keywords",     visible_now,    visible_prev),
        mm_kpi_card("Ranking Improvements", improved_count, None),
        mm_kpi_card("Ranking Declines",     declined_count, None),
        mm_kpi_card("Avg Position",         avg_pos_curr,   avg_pos_prev, decimals=2, lower_better=True),
    )

    # ── Optional sections (only rendered when data exists) ────────────────────
    device_section = ""
    if device_df is not None and not device_df.empty:
        device_section = mm_section("Device Performance",
            mm_report_section(
                _row2("device_split", "Performance by device",
                      "country_top10", "Top countries by impressions")
            )
        )

    discover_section = ""
    if discover_df is not None and not discover_df.empty:
        disc_total_impr = int(discover_df["impressions"].sum())
        disc_total_clk  = int(discover_df["clicks"].sum())
        discover_section = mm_section("Google Discover",
            mm_report_section(
                f'<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;margin-bottom:16px;">'
                f'{disc_total_impr:,} impressions · {disc_total_clk:,} clicks this week</p>' +
                _img("discover", "Google Discover top pages")
            )
        )

    keyword_pages_section = ""
    if chart_paths.get("keyword_pages"):
        keyword_pages_section = mm_section("Keywords by Landing Page",
            mm_report_section(_img("keyword_pages", "Top keywords coloured by landing page"))
        )

    gap_section = ""
    if not gap_df.empty:
        gap_section = mm_section("Click Potential Gap",
            mm_report_section(
                _img("click_potential", "Click potential gap — page 1 keywords with low CTR") +
                _tbl(gap_df,
                    ["keyword", "category", "position_current", "impressions_current", "ctr_current", "click_potential"],
                    {"keyword": "Keyword", "category": "Category", "position_current": "Pos",
                     "impressions_current": "Impr", "ctr_current": "CTR", "click_potential": "Est. Click Gain"}
                )
            )
        )

    # ── Top keywords table: include top_page column if available ──────────────
    top_kw_cols   = ["keyword", "category", "priority", "clicks_current", "impressions_current", "position_current", "position_change"]
    top_kw_rename = {"keyword": "Keyword", "category": "Category", "priority": "Priority",
                     "clicks_current": "Clicks", "impressions_current": "Impr",
                     "position_current": "Pos", "position_change": "Pos Δ"}
    if "top_page" in comparison_df.columns:
        top_kw_cols.append("top_page")
        top_kw_rename["top_page"] = "Landing Page"

    body = (
        # ── Executive Summary ─────────────────────────────────────────────────
        mm_section("Executive Summary",
            mm_report_section(mm_exec_bullets(exec_bullets))
        ) +

        # ── KPI Cards ─────────────────────────────────────────────────────────
        f'<div class="section" style="padding-top:0;">{kpi_grid}</div>'
        '<hr class="rule-thick">' +

        # ── Performance Overview: KPI chart + Position bands ──────────────────
        mm_section("Performance Overview",
            mm_report_section(_row2(
                "kpi_overview",   "Keyword visibility and ranking movement",
                "position_bands", "SERP position band distribution",
            ))
        ) +

        # ── Demand Drivers: Clicks + Impressions ──────────────────────────────
        mm_section("Top Demand Drivers",
            mm_report_section(_row2(
                "top_clicks",      "Top tracked keywords by clicks",
                "top_impressions", "Top tracked keywords by impressions",
            ))
        ) +

        # ── Keywords by Landing Page (when page data available) ───────────────
        keyword_pages_section +

        # ── Movers + CTR Efficiency ───────────────────────────────────────────
        mm_section("Ranking Movement & CTR Efficiency",
            mm_report_section(_row2(
                "movers",         "Ranking winners and losers",
                "ctr_efficiency", "CTR efficiency scatter",
            ))
        ) +

        # ── Click Potential Gap ───────────────────────────────────────────────
        gap_section +

        # ── Category Impressions (full width) ─────────────────────────────────
        mm_section("Impressions by Category",
            mm_report_section(_img("category_impressions", "Impressions by content category"))
        ) +

        # ── Device + Country (when data available) ────────────────────────────
        device_section +

        # ── Google Discover (when data available) ─────────────────────────────
        discover_section +

        # ── Data Tables ───────────────────────────────────────────────────────
        mm_section("Top Tracked Keywords",
            mm_report_section(_tbl(top_keywords, top_kw_cols, top_kw_rename))
        ) +
        mm_section("Biggest Ranking Improvements",
            mm_report_section(_tbl(biggest_gainers,
                ["keyword", "position_previous", "position_current", "position_change", "clicks_current"],
                {"keyword": "Keyword", "position_previous": "Prev Pos",
                 "position_current": "Curr Pos", "position_change": "Pos Δ", "clicks_current": "Clicks"}
            ))
        ) +
        mm_section("Biggest Ranking Declines",
            mm_report_section(_tbl(biggest_losers,
                ["keyword", "position_previous", "position_current", "position_change", "clicks_current"],
                {"keyword": "Keyword", "position_previous": "Prev Pos",
                 "position_current": "Curr Pos", "position_change": "Pos Δ", "clicks_current": "Clicks"}
            ))
        ) +
        mm_section("Entered Top 3",
            mm_report_section(_tbl(entered_top_3,
                ["keyword", "category", "priority", "position_previous", "position_current"],
                {"keyword": "Keyword", "category": "Category", "priority": "Priority",
                 "position_previous": "Prev Pos", "position_current": "Curr Pos"}
            ))
        ) +
        mm_section("Entered Top 10",
            mm_report_section(_tbl(entered_top_10,
                ["keyword", "category", "priority", "position_previous", "position_current"],
                {"keyword": "Keyword", "category": "Category", "priority": "Priority",
                 "position_previous": "Prev Pos", "position_current": "Curr Pos"}
            ))
        ) +
        mm_section("Lost Visibility",
            mm_report_section(_tbl(lost_visibility,
                ["keyword", "category", "priority", "impressions_previous", "impressions_current"],
                {"keyword": "Keyword", "category": "Category", "priority": "Priority",
                 "impressions_previous": "Prev Impr", "impressions_current": "Curr Impr"}
            ))
        )
    )

    doc = mm_html_shell(
        title="Weekly Keyword Ranking Review",
        eyebrow="Google Search Console",
        headline="Keyword Ranking\nReview",
        meta_line=f"{current_start} → {current_end} / prev {previous_start} → {previous_end}",
        body_content=body,
    )
    with open("keyword_ranking_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("Saved keyword_ranking_summary.html")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def generate_self_contained():
    generate_self_contained_html("keyword_ranking_summary.html", "keyword_ranking_summary_final.html")


def upload_to_monday():
    upload_html_to_monday(
        "keyword_ranking_summary_final.html",
        "keyword-ranking-review.html",
        body_text="Keyword Ranking Review attached as self-contained HTML.",
    )


def main():
    service = get_service()
    tracked_df = load_tracked_keywords()

    current_start, current_end, previous_start, previous_end = get_weekly_date_windows()

    print("Fetching GSC data...")
    current_query_df  = fetch_query_data(service, current_start, current_end, row_limit=1000)
    previous_query_df = fetch_query_data(service, previous_start, previous_end, row_limit=1000)

    # New dimension fetches — all gracefully return empty DataFrames on failure
    current_page_df   = fetch_page_data(service, current_start, current_end, row_limit=1000)
    device_df         = fetch_device_data(service, current_start, current_end)
    country_df        = fetch_country_data(service, current_start, current_end)
    discover_df       = fetch_discover_data(service, current_start, current_end)

    print(f"  Query rows: {len(current_query_df)} current / {len(previous_query_df)} previous")
    print(f"  Page rows: {len(current_page_df)}")
    print(f"  Device rows: {len(device_df)}")
    print(f"  Country rows: {len(country_df)}")
    print(f"  Discover rows: {len(discover_df)}")

    current_snapshot_df  = build_keyword_snapshot(tracked_df, current_query_df)
    previous_snapshot_df = build_keyword_snapshot(tracked_df, previous_query_df)

    comparison_df = prepare_comparison(current_snapshot_df, previous_snapshot_df)

    # Enrich with landing page data
    comparison_df = enrich_with_pages(comparison_df, current_page_df)

    # Save CSVs before report generation
    current_snapshot_df.to_csv("tracked_keywords_current_week.csv", index=False)
    previous_snapshot_df.to_csv("tracked_keywords_previous_week.csv", index=False)
    comparison_df.to_csv("tracked_keywords_comparison.csv", index=False)
    if not device_df.empty:
        device_df.to_csv("device_performance.csv", index=False)
    if not country_df.empty:
        country_df.to_csv("country_performance.csv", index=False)
    if not discover_df.empty:
        discover_df.to_csv("discover_performance.csv", index=False)
    if not current_page_df.empty:
        current_page_df.to_csv("keyword_page_mapping.csv", index=False)

    comparison_df[comparison_df["ranking_improved"]].sort_values("position_change").to_csv("ranking_gainers.csv", index=False)
    comparison_df[comparison_df["ranking_declined"]].sort_values("position_change", ascending=False).to_csv("ranking_losers.csv", index=False)
    comparison_df[comparison_df["entered_top_3"]].to_csv("entered_top_3.csv", index=False)
    comparison_df[comparison_df["entered_top_10"]].to_csv("entered_top_10.csv", index=False)
    build_click_potential_gap(comparison_df).to_csv("click_potential_gap.csv", index=False)

    # Build unified executive bullets (deterministic + AI)
    exec_bullets = build_unified_executive_bullets(
        comparison_df, current_start, current_end, previous_start, previous_end,
        device_df=device_df if not device_df.empty else None,
        country_df=country_df if not country_df.empty else None,
        discover_df=discover_df if not discover_df.empty else None,
    )

    # Build all charts
    chart_paths = build_all_charts(
        comparison_df,
        device_df=device_df if not device_df.empty else None,
        country_df=country_df if not country_df.empty else None,
        discover_df=discover_df if not discover_df.empty else None,
    )

    # Write reports
    write_markdown_summary(comparison_df, exec_bullets, current_start, current_end, previous_start, previous_end)
    write_html_summary(
        comparison_df, exec_bullets, chart_paths,
        current_start, current_end, previous_start, previous_end,
        device_df=device_df if not device_df.empty else None,
        country_df=country_df if not country_df.empty else None,
        discover_df=discover_df if not discover_df.empty else None,
    )
    generate_self_contained()

    try:
        upload_to_monday()
    except Exception as e:
        print(f"Monday upload step failed: {e}")

    print("Saved keyword ranking outputs.")


if __name__ == "__main__":
    main()
