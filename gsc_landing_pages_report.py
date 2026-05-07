# ═══════════════════
# IMPORTS
# ═══════════════════
from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
import pandas as pd
import requests
import os
import html
import base64
from io import BytesIO
from pathlib import Path
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pdf_report_formatter import format_num, format_delta, format_pct_change
from seo_utils import get_weekly_date_windows, short_url

# ═══════════════════
# CONSTANTS
# ═══════════════════
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
KEY_FILE = "gsc-key.json"
SITE_URL = os.environ["GSC_PROPERTY"]
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")
CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

TRACKED_PAGES_FILE = "tracked_pages.csv"

# Brand colour palette
C_NAVY   = "#212878"
C_TEAL   = "#2A9D8F"
C_CORAL  = "#E76F51"
C_SLATE  = "#6C757D"
C_GREEN  = "#059669"
C_RED    = "#DC2626"
C_AMBER  = "#D97706"
C_BORDER = "#E2E8F0"
C_LIGHT  = "#F1F5F9"


# ═══════════════════
# DATA FETCHING
# ═══════════════════
def get_service():
    credentials = service_account.Credentials.from_service_account_file(
        KEY_FILE,
        scopes=SCOPES,
    )
    return build("searchconsole", "v1", credentials=credentials)


# ═══════════════════
# DATA PROCESSING
# ═══════════════════
def load_tracked_pages():
    df = pd.read_csv(TRACKED_PAGES_FILE)
    df["page"] = df["page"].astype(str).str.strip()
    df["category"] = df["category"].astype(str).str.strip()
    df["priority"] = df["priority"].astype(str).str.strip()
    return df


def fetch_page_data(service, start_date, end_date, row_limit=1000):
    request = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["page"],
        "rowLimit": row_limit,
    }

    try:
        response = service.searchanalytics().query(
            siteUrl=SITE_URL,
            body=request
        ).execute()
    except Exception as e:
        print(f"✗ Failed to fetch page data: {e}")
        return pd.DataFrame(columns=["page", "clicks", "impressions", "ctr", "position"])

    rows = response.get("rows", [])
    data = []

    for row in rows:
        data.append({
            "page": str(row["keys"][0]).strip(),
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0),
            "position": row.get("position", 0),
        })

    if not data:
        return pd.DataFrame(columns=["page", "clicks", "impressions", "ctr", "position"])

    print(f"✓ Fetched {len(data)} pages")
    return pd.DataFrame(data)


def build_page_snapshot(tracked_df, page_df):
    merged = pd.merge(
        tracked_df,
        page_df,
        on="page",
        how="left"
    )

    merged["clicks"] = merged["clicks"].fillna(0)
    merged["impressions"] = merged["impressions"].fillna(0)
    merged["ctr"] = merged["ctr"].fillna(0)
    merged["position"] = merged["position"].fillna(0)

    return merged[["page", "category", "priority", "clicks", "impressions", "ctr", "position"]]


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
        on=["page", "category", "priority"],
        how="outer"
    )
    
    # Cast all numeric columns to float after merge
    numeric_cols = [
        "clicks_current", "impressions_current", "ctr_current", "position_current",
        "clicks_previous", "impressions_previous", "ctr_previous", "position_previous"
    ]
    for col in numeric_cols:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)

    merged["clicks_change"] = merged["clicks_current"] - merged["clicks_previous"]
    merged["impressions_change"] = merged["impressions_current"] - merged["impressions_previous"]
    merged["ctr_change"] = merged["ctr_current"] - merged["ctr_previous"]
    merged["position_change"] = merged["position_current"] - merged["position_previous"]

    # Round position values to 1 decimal place for clean display
    for col in ["position_current", "position_previous", "position_change"]:
        merged[col] = merged[col].round(1)

    merged["position_improved"] = (
        (merged["position_previous"] > 0) &
        (merged["position_current"] > 0) &
        (merged["position_current"] < merged["position_previous"])
    )
    merged["position_declined"] = (
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

    priority_order = {"high": 0, "medium": 1, "low": 2}
    merged["priority_order"] = merged["priority"].str.lower().map(priority_order).fillna(9)
    merged = merged.sort_values(
        by=["priority_order", "clicks_current", "impressions_current"],
        ascending=[True, False, False]
    ).drop(columns=["priority_order"])

    return merged

def _fmt(val, decimals=0, pct=False):
    """Format a value for table display."""
    try:
        v = float(val)
        import math
        if math.isnan(v):
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
    """Return a colored delta span for HTML tables."""
    import math
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "-"
    if math.isclose(v, 0, abs_tol=0.05):  # treat |Δ| < 0.05 as zero (avoids "+0" / "-0")
        return '<span class="chg neu">—</span>'
    is_positive = v > 0
    is_good = (is_positive and not lower_is_better) or (not is_positive and lower_is_better)
    css_class = "pos" if is_good else "neg"
    sign = "+" if v > 0 else ""
    return f'<span class="chg {css_class}">{sign}{v:.{decimals}f}</span>'


def position_band_html(pos):
    """Return a position band badge for HTML tables."""
    try:
        p = float(pos)
        if p == 0:
            return "-"
        if p <= 3:
            return '<span class="badge badge-top3">Top 3</span>'
        if p <= 10:
            return '<span class="badge badge-p1">Page 1</span>'
        if p <= 20:
            return '<span class="badge badge-p2">Page 2</span>'
        return '<span class="badge badge-p3">Page 3+</span>'
    except (ValueError, TypeError):
        return "-"


# ═══════════════════
# CHART GENERATION
# ═══════════════════
def _style_ax(ax, title="", xlabel="", ylabel=""):
    """Apply consistent styling to matplotlib axes."""
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
    """Save a chart to the charts directory."""
    path = CHARTS_DIR / name
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def short_page_label(url, max_len=52):
    """Shorten a page URL for chart labels."""
    if not isinstance(url, str):
        return ""
    label = url.replace("https://", "").replace("http://", "")
    if len(label) > max_len:
        return label[:max_len - 1] + "…"
    return label


# ═══════════════════
# AI ANALYSIS
# ═══════════════════
def build_deterministic_bullets(comparison_df):
    lines = []

    visible_now = comparison_df[comparison_df["impressions_current"] > 0]
    improved = comparison_df[comparison_df["position_improved"]]
    declined = comparison_df[comparison_df["position_declined"]]
    lost_visibility = comparison_df[comparison_df["lost_visibility"]]
    new_visibility = comparison_df[comparison_df["newly_visible"]]

    lines.append(f"{len(visible_now)} tracked landing pages generated visibility this week.")

    if len(improved) > len(declined):
        lines.append("More tracked landing pages improved in average position than declined.")
    elif len(improved) < len(declined):
        lines.append("More tracked landing pages declined in average position than improved.")
    else:
        lines.append("Position movement was mixed across the tracked landing page set.")

    if not new_visibility.empty:
        lines.append(f"{len(new_visibility)} tracked pages became newly visible this week.")
    if not lost_visibility.empty:
        lines.append(f"{len(lost_visibility)} tracked pages lost visibility week over week.")

    high_priority = comparison_df[comparison_df["priority"].str.lower() == "high"]
    if not high_priority.empty:
        total_clicks = high_priority["clicks_current"].sum()
        lines.append(f"High-priority landing pages delivered {total_clicks:.0f} clicks this week.")

    return lines


def build_ai_bullets(comparison_df, current_start, current_end, previous_start, previous_end):
    """Generate AI-powered bullet points for executive summary."""
    if not GROQ_API_KEY:
        return []

    top_table = comparison_df[[
        "page", "category", "priority", "clicks_current", "impressions_current",
        "position_current", "clicks_change", "position_change"
    ]].head(15)

    prompt = f"""
You are writing bullet points for a corporate SEO landing page monitoring report.

Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.
Each bullet is one sentence. Maximum 6 bullets total.
Do not invent data. Focus on landing page movement and visibility changes.
Professional corporate tone. Avoid hype. Do not mention AI, models, or automation.

Current period: {current_start} to {current_end}
Previous period: {previous_start} to {previous_end}

Tracked landing page data:
{top_table.to_csv(index=False)}
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
        
        # Clean markdown from AI output
        bullets = []
        for line in raw.splitlines():
            clean = line.strip().lstrip("-*+•·▪▸").strip()
            clean = clean.replace("**", "").replace("__", "").replace("*", "").strip()
            if clean and not clean.startswith("#"):
                bullets.append(clean)
        
        return bullets
    except Exception as e:
        print(f"✗ AI commentary failed: {e}")
        return []


def build_unified_executive_bullets(comparison_df, current_start, current_end, previous_start, previous_end):
    """Build unified executive summary with deterministic + AI bullets."""
    deterministic = build_deterministic_bullets(comparison_df)
    ai_bullets = build_ai_bullets(comparison_df, current_start, current_end, previous_start, previous_end)
    return deterministic + ai_bullets


# ═══════════════════
# HTML TABLE BUILDERS
# ═══════════════════
def html_table_from_df(df, columns, rename_map=None):
    """Build an HTML table from a DataFrame."""
    if df.empty:
        return "<p class='muted'>No data available to display.</p>"
        
    work = df[columns].copy()
    if rename_map:
        work = work.rename(columns=rename_map)

    # Format columns
    rows_html = []
    for _, row in work.iterrows():
        cells = []
        for col_name, val in zip(work.columns, row):
            lower_col = col_name.lower()
            
            if "page" in lower_col or "url" in lower_col:
                # URL cell
                cell_val = html.escape(short_url(str(val), 45))
                cells.append(f'<td class="url-cell">{cell_val}</td>')
            elif "δ" in col_name or "change" in lower_col:
                # Delta cell
                if "position" in lower_col:
                    cells.append(f'<td style="white-space:nowrap;">{_delta_html(val, decimals=2, lower_is_better=True)}</td>')
                else:
                    cells.append(f'<td style="white-space:nowrap;">{_delta_html(val, decimals=0)}</td>')
            elif "position" in lower_col and "change" not in lower_col:
                # Position cell with band
                cells.append(f'<td style="white-space:nowrap;">{_fmt(val, decimals=2)} {position_band_html(val)}</td>')
            elif "ctr" in lower_col or "rate" in lower_col:
                # Percentage cell
                cells.append(f'<td style="white-space:nowrap;">{_fmt(val, pct=True)}</td>')
            elif any(token in lower_col for token in ["click", "impr", "impression"]):
                # Numeric cell
                cells.append(f'<td style="white-space:nowrap;">{_fmt(val, decimals=0)}</td>')
            else:
                # Text cell
                cells.append(f'<td>{html.escape(str(val))}</td>')
        
        rows_html.append(f"<tr>{''.join(cells)}</tr>")

    header_html = "".join(f"<th>{html.escape(str(col))}</th>" for col in work.columns)
    return f'<table style="table-layout:fixed;"><thead><tr>{header_html}</tr></thead><tbody>{"".join(rows_html)}</tbody></table>'


# ═══════════════════
# CSS
# ═══════════════════
def get_extra_css():
    """Extra CSS specific to landing pages report."""
    return """
    /* ══════════════════════════════════════════════════════════════
       MINIMALIST MONOCHROME — Design System
       Playfair Display (display) · Source Serif 4 (body) · JetBrains Mono (data)
    ══════════════════════════════════════════════════════════════ */

    /* ── Noise texture overlay (paper quality) ──────────────────── */
    body::before {
        content: '';
        position: fixed;
        inset: 0;
        background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
        opacity: 0.018;
        pointer-events: none;
        z-index: 9999;
    }

    /* ── Executive summary panel ────────────────────────────────── */
    .exec-panel {
        border: none;
        padding: 0;
        margin: 0;
        background: transparent;
    }
    .panel-label {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #525252;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .panel-label::after {
        content: '';
        flex: 1;
        height: 1px;
        background: #E5E5E5;
    }
    .exec-bullets {
        margin: 0;
        padding: 0;
        list-style: none;
    }
    .exec-bullets li {
        font-family: 'Source Serif 4', Georgia, serif;
        font-size: 14px;
        color: #000000;
        line-height: 1.7;
        padding: 10px 0;
        border-bottom: 1px solid #E5E5E5;
        padding-left: 20px;
        position: relative;
    }
    .exec-bullets li::before {
        content: '—';
        position: absolute;
        left: 0;
        color: #525252;
        font-family: 'JetBrains Mono', monospace;
    }
    .exec-bullets li:last-child { border-bottom: none; }

    /* ── Section label ──────────────────────────────────────────── */
    .section-label {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #525252;
        margin-bottom: 8px;
    }

    /* ── Delta spans — monochrome, border-based ─────────────────── */
    .chg {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        font-weight: 600;
        padding: 2px 7px;
        border-radius: 0;
        display: inline-block;
        border: 1px solid #000;
    }
    .chg.pos { background: #000; color: #fff; border-color: #000; }
    .chg.neg { background: #fff; color: #000; border-color: #000; }
    .chg.neu { background: #fff; color: #525252; border-color: #E5E5E5; }

    /* ── Position band badges — sharp, monochrome ───────────────── */
    .badge {
        font-family: 'JetBrains Mono', monospace;
        font-size: 8px;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 0;
        display: inline-block;
        white-space: nowrap;
        border: 1px solid #000;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .badge-top3 { background: #000; color: #fff; }
    .badge-p1   { background: #fff; color: #000; }
    .badge-p2   { background: #fff; color: #525252; border-color: #525252; }
    .badge-p3   { background: #fff; color: #E5E5E5; border-color: #E5E5E5; }

    /* ── Chart wrapper ──────────────────────────────────────────── */
    .chart-wrap { width: 100%; margin-bottom: 24px; }
    .chart-wrap img {
        width: 100%;
        display: block;
        border: 2px solid #000;
        border-radius: 0;
    }

    /* ── Two-chart row ──────────────────────────────────────────── */
    .chart-row-2 {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
        margin-bottom: 24px;
    }
    .chart-row-2 img {
        width: 100%;
        display: block;
        border: 2px solid #000;
        border-radius: 0;
    }

    /* ── Section header ─────────────────────────────────────────── */
    .col-header {
        font-family: 'Playfair Display', Georgia, serif;
        font-size: 13px;
        font-weight: 700;
        color: #000;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-top: 28px;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 2px solid #000;
    }
    .col-header:first-child { margin-top: 0; }

    /* ── Table ──────────────────────────────────────────────────── */
    table {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 0;
    }
    th {
        font-family: 'JetBrains Mono', monospace;
        font-size: 8px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        padding: 10px 12px;
        text-align: left;
        background: #000;
        color: #fff;
        border: none;
    }
    td {
        padding: 9px 12px;
        border-bottom: 1px solid #E5E5E5;
        overflow-wrap: break-word;
        word-break: normal;
        color: #000;
    }
    td.url-cell {
        max-width: 220px;
        overflow-wrap: break-word;
        word-break: break-word;
        font-size: 9px;
        color: #525252;
    }
    tr:hover td { background: #F5F5F5; }
    tr:nth-child(even) td { background: transparent; }
    """


# ═══════════════════
# MARKDOWN REPORT
# ═══════════════════
    work = df[columns].copy()
    if rename_map:
        work = work.rename(columns=rename_map)

    for col in work.columns:
        lower_col = col.lower()
        if "ctr" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.2%}" if pd.notnull(x) else "")
        elif "position" in lower_col and "change" not in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.2f}" if pd.notnull(x) and x != 0 else "")
        elif "position" in lower_col and "change" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x, decimals=2) if pd.notnull(x) else "")
        elif "change" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x, decimals=0) if pd.notnull(x) else "")
        elif any(token in lower_col for token in ["click", "impression"]):
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.0f}" if pd.notnull(x) else "")
        else:
            work[col] = work[col].fillna("").astype(str)
    return work.to_markdown(index=False)




def create_kpi_comparison_chart(comparison_df):
    """Create KPI comparison chart with current vs previous week."""
    if comparison_df.empty:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No data available for this period.",
                ha="center", va="center", fontsize=12, color="#94A3B8",
                transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "landing_page_comparison.png")
    
    current_clicks = comparison_df["clicks_current"].sum()
    previous_clicks = comparison_df["clicks_previous"].sum()
    current_impressions = comparison_df["impressions_current"].sum()
    previous_impressions = comparison_df["impressions_previous"].sum()
    current_ctr = current_clicks / current_impressions if current_impressions else 0
    previous_ctr = previous_clicks / previous_impressions if previous_impressions else 0

    current_position = comparison_df.loc[comparison_df["impressions_current"] > 0, "position_current"].mean()
    previous_position = comparison_df.loc[comparison_df["impressions_previous"] > 0, "position_previous"].mean()
    current_position = 0 if pd.isna(current_position) else current_position
    previous_position = 0 if pd.isna(previous_position) else previous_position

    labels = ["Clicks", "Impressions", "CTR %", "Avg Position"]
    current_vals = [current_clicks, current_impressions, current_ctr * 100, current_position]
    previous_vals = [previous_clicks, previous_impressions, previous_ctr * 100, previous_position]

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    fig.tight_layout(pad=2.0)
    
    x = range(len(labels))
    width = 0.36
    bars_prev = ax.bar([i - width/2 for i in x], previous_vals, width=width, label="Previous", color=C_SLATE)
    bars_curr = ax.bar([i + width/2 for i in x], current_vals, width=width, label="Current", color=C_NAVY)
    
    # Add value labels
    for bar in bars_prev:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, height * 1.03,
                f"{height:,.0f}", ha="center", va="bottom", fontsize=9, color="#374151", fontweight="600")
    for bar in bars_curr:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, height * 1.03,
                f"{height:,.0f}", ha="center", va="bottom", fontsize=9, color="#374151", fontweight="600")
    
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.legend(frameon=False)
    _style_ax(ax, title="Current Week vs Previous Week")
    
    return _save(fig, "landing_page_comparison.png")


def create_top_pages_chart(top_pages):
    """Create horizontal bar chart of top landing pages by clicks."""
    if top_pages.empty:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No data available for this period.",
                ha="center", va="center", fontsize=12, color="#94A3B8",
                transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "landing_page_top_clicks.png")
    
    work = top_pages.head(10).iloc[::-1].copy()
    labels = [short_page_label(v, 42) for v in work["page"]]
    vals = pd.to_numeric(work["clicks_current"], errors="coerce").fillna(0)

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    fig.tight_layout(pad=2.0)
    
    bars = ax.barh(labels, vals, color=C_NAVY)
    
    # Add value labels
    max_v = vals.max()
    for bar, v in zip(bars, vals):
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height()/2,
                f"{v:,.0f}", va="center", fontsize=9, color="#374151")
    
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Landing Pages by Clicks")
    
    return _save(fig, "landing_page_top_clicks.png")


def create_traffic_change_chart(gainers, losers):
    """Create lollipop chart showing traffic winners and losers."""
    if gainers.empty and losers.empty:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No data available for this period.",
                ha="center", va="center", fontsize=12, color="#94A3B8",
                transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "landing_page_traffic_changes.png")
    
    gainers = gainers.head(5).copy()
    losers = losers.head(5).copy()

    labels = [short_page_label(v, 36) for v in list(losers["page"])[::-1] + list(gainers["page"])[::-1]]
    values = list(pd.to_numeric(losers["clicks_change"], errors="coerce").fillna(0))[::-1] + \
             list(pd.to_numeric(gainers["clicks_change"], errors="coerce").fillna(0))[::-1]
    colors = [C_CORAL if v < 0 else C_TEAL for v in values]

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    fig.tight_layout(pad=2.0)
    
    ax.barh(labels, values, color=colors)
    ax.axvline(0, color="#475569", linewidth=1)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Traffic Winners and Losers")
    
    return _save(fig, "landing_page_traffic_changes.png")


def create_position_change_chart(position_gainers, position_losers):
    """Create chart showing position movement (lower is better)."""
    if position_gainers.empty and position_losers.empty:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No data available for this period.",
                ha="center", va="center", fontsize=12, color="#94A3B8",
                transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "landing_page_position_changes.png")
    
    position_gainers = position_gainers.head(5).copy()
    position_losers = position_losers.head(5).copy()

    loser_vals = list(pd.to_numeric(position_losers["position_change"], errors="coerce").fillna(0))[::-1]
    gainer_vals = list(pd.to_numeric(position_gainers["position_change"], errors="coerce").fillna(0))[::-1]
    labels = [short_page_label(v, 36) for v in list(position_losers["page"])[::-1] + list(position_gainers["page"])[::-1]]
    values = loser_vals + gainer_vals
    # For position: negative change = improvement (green), positive change = decline (red)
    colors = [C_RED if v > 0 else C_GREEN for v in values]

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    fig.tight_layout(pad=2.0)
    
    ax.barh(labels, values, color=colors)
    ax.axvline(0, color="#475569", linewidth=1)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Position Movement")
    
    return _save(fig, "landing_page_position_changes.png")


def md_table_from_df(df, columns, rename_map=None):
    """Build a markdown table from a DataFrame."""
    work = df[columns].copy()
    if rename_map:
        work = work.rename(columns=rename_map)

    for col in work.columns:
        lower_col = col.lower()
        if "ctr" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.2%}" if pd.notnull(x) else "")
        elif "position" in lower_col and "change" not in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.2f}" if pd.notnull(x) and x != 0 else "")
        elif "position" in lower_col and "change" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x, decimals=2) if pd.notnull(x) else "")
        elif "change" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x, decimals=0) if pd.notnull(x) else "")
        elif any(token in lower_col for token in ["click", "impression"]):
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.0f}" if pd.notnull(x) else "")
        else:
            work[col] = work[col].fillna("").astype(str)
    return work.to_markdown(index=False)


def write_markdown_summary(comparison_df, unified_bullets, current_start, current_end, previous_start, previous_end):
    """Write markdown summary report."""
    top_pages = comparison_df.sort_values(by=["clicks_current", "impressions_current"], ascending=[False, False]).head(25)
    biggest_gainers = comparison_df.sort_values(by="clicks_change", ascending=False).head(15)
    biggest_losers = comparison_df.sort_values(by="clicks_change", ascending=True).head(15)
    position_gainers = comparison_df[comparison_df["position_improved"]].sort_values(by="position_change", ascending=True).head(15)
    position_losers = comparison_df[comparison_df["position_declined"]].sort_values(by="position_change", ascending=False).head(15)
    lost_visibility = comparison_df[comparison_df["lost_visibility"]].head(15)

    lines = [
        "# Critical Landing Pages to Monitor",
        "",
        "## Executive Summary",
        "",
    ]
    lines.extend([f"- {line}" for line in unified_bullets])
    lines.extend([
        "",
        "## Reporting Window",
        "",
        f"- Current period: {current_start} to {current_end}",
        f"- Previous period: {previous_start} to {previous_end}",
        "",
        "## Top Tracked Landing Pages",
        "",
        md_table_from_df(
            top_pages,
            ["page", "category", "priority", "clicks_current", "impressions_current", "ctr_current", "position_current", "clicks_change"],
            {
                "page": "Page",
                "category": "Category",
                "priority": "Priority",
                "clicks_current": "Clicks",
                "impressions_current": "Impressions",
                "ctr_current": "CTR",
                "position_current": "Current Position",
                "clicks_change": "WoW Clicks Δ",
            }
        ),
        "",
        "## Biggest Traffic Gainers",
        "",
        md_table_from_df(
            biggest_gainers,
            ["page", "clicks_previous", "clicks_current", "clicks_change", "impressions_current"],
            {
                "page": "Page",
                "clicks_previous": "Prev Clicks",
                "clicks_current": "Current Clicks",
                "clicks_change": "Δ",
                "impressions_current": "Impressions",
            }
        ),
        "",
        "## Biggest Traffic Losers",
        "",
        md_table_from_df(
            biggest_losers,
            ["page", "clicks_previous", "clicks_current", "clicks_change", "impressions_current"],
            {
                "page": "Page",
                "clicks_previous": "Prev Clicks",
                "clicks_current": "Current Clicks",
                "clicks_change": "Δ",
                "impressions_current": "Impressions",
            }
        ),
        "",
        "## Best Position Improvements",
        "",
        md_table_from_df(
            position_gainers,
            ["page", "position_previous", "position_current", "position_change", "clicks_current"],
            {
                "page": "Page",
                "position_previous": "Prev Position",
                "position_current": "Current Position",
                "position_change": "Position Δ",
                "clicks_current": "Clicks",
            }
        ),
        "",
        "## Biggest Position Declines",
        "",
        md_table_from_df(
            position_losers,
            ["page", "position_previous", "position_current", "position_change", "clicks_current"],
            {
                "page": "Page",
                "position_previous": "Prev Position",
                "position_current": "Current Position",
                "position_change": "Position Δ",
                "clicks_current": "Clicks",
            }
        ),
        "",
        "## Lost Visibility",
        "",
        md_table_from_df(
            lost_visibility,
            ["page", "category", "priority", "impressions_previous", "impressions_current"],
            {
                "page": "Page",
                "category": "Category",
                "priority": "Priority",
                "impressions_previous": "Prev Impressions",
                "impressions_current": "Current Impressions",
            }
        ),
    ])

    with open("landing_pages_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Saved landing_pages_summary.md")


# ═══════════════════
# HTML & PDF REPORT
# ═══════════════════


# ═══════════════════
# HTML REPORT BUILDER
# ═══════════════════
def _img_tag(path, alt="chart"):
    """Return an <img> tag. Path is a local file — will be base64-embedded later."""
    print(f"DEBUG _img_tag: path={path}, type={type(path)}", flush=True)
    if not path:
        return ""
    path_str = str(path)
    print(f"DEBUG _img_tag: path_str={path_str}", flush=True)
    return f'<img src="{html.escape(path_str)}" alt="{html.escape(alt)}" style="width:100%;display:block;border-radius:6px;border:1px solid #E2E8F0;">'


def _chart_wrap(path, alt="chart"):
    """Single full-width chart."""
    print(f"DEBUG _chart_wrap called with path={path}, alt={alt}", flush=True)
    if not path:
        print(f"DEBUG _chart_wrap returning empty (path is falsy)", flush=True)
        return ""
    result = f'<div class="chart-wrap">{_img_tag(path, alt)}</div>'
    print(f"DEBUG _chart_wrap returning: {result[:100]}...", flush=True)
    return result


def _chart_row_2(path_a, alt_a, path_b, alt_b):
    """Two charts side-by-side in a CSS Grid row."""
    a = _img_tag(path_a, alt_a) if path_a else ""
    b = _img_tag(path_b, alt_b) if path_b else ""
    if not a and not b:
        return ""
    return f'<div class="chart-row-2"><div>{a}</div><div>{b}</div></div>'


def write_html_summary(comparison_df, unified_bullets, current_start, current_end, previous_start, previous_end):
    """Write HTML summary report matching gsc_weekly_report.py pattern."""
    top_pages       = comparison_df.sort_values(by=["clicks_current","impressions_current"], ascending=[False,False]).head(25)
    biggest_gainers = comparison_df.sort_values(by="clicks_change", ascending=False).head(15)
    biggest_losers  = comparison_df.sort_values(by="clicks_change", ascending=True).head(15)
    position_gainers= comparison_df[comparison_df["position_improved"]].sort_values(by="position_change", ascending=True).head(15)
    position_losers = comparison_df[comparison_df["position_declined"]].sort_values(by="position_change", ascending=False).head(15)
    lost_visibility = comparison_df[comparison_df["lost_visibility"]].head(15)

    visible_now      = int((comparison_df["impressions_current"] > 0).sum())
    total_clicks     = int(comparison_df["clicks_current"].sum())
    total_impressions= int(comparison_df["impressions_current"].sum())
    weighted_ctr     = (comparison_df["clicks_current"].sum() / total_impressions) if total_impressions else 0
    avg_position     = comparison_df.loc[comparison_df["impressions_current"] > 0, "position_current"].mean()
    avg_position     = 0 if pd.isna(avg_position) else avg_position
    
    prev_clicks      = int(comparison_df["clicks_previous"].sum())
    prev_impressions = int(comparison_df["impressions_previous"].sum())
    prev_ctr         = (comparison_df["clicks_previous"].sum() / prev_impressions) if prev_impressions else 0
    prev_position    = comparison_df.loc[comparison_df["impressions_previous"] > 0, "position_previous"].mean()
    prev_position    = 0 if pd.isna(prev_position) else prev_position

    charts = {
        "kpi":              create_kpi_comparison_chart(comparison_df),
        "top_pages":        create_top_pages_chart(top_pages),
        "traffic_changes":  create_traffic_change_chart(biggest_gainers, biggest_losers),
        "position_changes": create_position_change_chart(position_gainers, position_losers),
    }
    
    # Debug: print chart paths
    print("DEBUG: Charts created", flush=True)
    for key, path in charts.items():
        print(f"Chart '{key}': {path}", flush=True)

    bullet_items = "".join(f"<li>{html.escape(b)}</li>" for b in unified_bullets)

    # ── KPI cards — inverted (black bg, white text) ────────────────────────
    def _kpi_card(label, curr_val, prev_val, is_pct=False, decimals=0, lower_better=False):
        curr_str  = format_num(curr_val, decimals, as_percent=is_pct)
        prev_str  = format_num(prev_val, decimals, as_percent=is_pct)
        delta_str = format_pct_change(curr_val, prev_val)
        if delta_str == "-":
            delta_html_str = '<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">—</span>'
        else:
            is_pos = delta_str.startswith("+")
            good   = (is_pos and not lower_better) or (not is_pos and lower_better)
            d_color = "#fff" if good else "#000"
            d_bg    = "#000" if good else "#fff"
            d_border = "1px solid #000"
            delta_html_str = (
                f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;'
                f'font-weight:700;padding:2px 8px;background:{d_bg};color:{d_color};'
                f'border:{d_border};">{delta_str}</span>'
            )
        return f"""
        <div style="background:#000;color:#fff;padding:24px 20px;border:2px solid #000;position:relative;overflow:hidden;">
          <div style="position:absolute;inset:0;background-image:repeating-linear-gradient(90deg,transparent,transparent 1px,#fff 1px,#fff 2px);background-size:4px 100%;opacity:0.03;pointer-events:none;"></div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.15em;color:#999;margin-bottom:12px;">{html.escape(label)}</div>
          <div style="font-family:'Playfair Display',Georgia,serif;font-size:36px;font-weight:700;color:#fff;line-height:1;margin-bottom:10px;">{html.escape(curr_str)}</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#999;margin-bottom:8px;">prev {html.escape(prev_str)}</div>
          {delta_html_str}
        </div>"""

    kpi_grid = "".join([
        _kpi_card("Visible Pages",  visible_now,  None),
        _kpi_card("Total Clicks",   total_clicks, prev_clicks),
        _kpi_card("Weighted CTR",   weighted_ctr, prev_ctr, is_pct=True),
        _kpi_card("Avg Position",   avg_position, prev_position, decimals=2, lower_better=True),
    ])

    top_pages_tbl = html_table_from_df(top_pages,
        ["page","category","priority","clicks_current","impressions_current","ctr_current","position_current","clicks_change"],
        {"page":"Page","category":"Category","priority":"Priority","clicks_current":"Clicks","impressions_current":"Impr",
         "ctr_current":"CTR","position_current":"Pos","clicks_change":"Clicks Δ"}
    ) if not top_pages.empty else '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">No data.</p>'

    gainers_tbl = html_table_from_df(biggest_gainers,
        ["page","clicks_previous","clicks_current","clicks_change","impressions_current"],
        {"page":"Page","clicks_previous":"Prev Clicks","clicks_current":"Curr Clicks","clicks_change":"Δ","impressions_current":"Impr"}
    ) if not biggest_gainers.empty else '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">No data.</p>'

    losers_tbl = html_table_from_df(biggest_losers,
        ["page","clicks_previous","clicks_current","clicks_change","impressions_current"],
        {"page":"Page","clicks_previous":"Prev Clicks","clicks_current":"Curr Clicks","clicks_change":"Δ","impressions_current":"Impr"}
    ) if not biggest_losers.empty else '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">No data.</p>'

    pos_gainers_tbl = html_table_from_df(position_gainers,
        ["page","position_previous","position_current","position_change","clicks_current"],
        {"page":"Page","position_previous":"Prev Pos","position_current":"Curr Pos","position_change":"Pos Δ","clicks_current":"Clicks"}
    ) if not position_gainers.empty else '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">No data.</p>'

    pos_losers_tbl = html_table_from_df(position_losers,
        ["page","position_previous","position_current","position_change","clicks_current"],
        {"page":"Page","position_previous":"Prev Pos","position_current":"Curr Pos","position_change":"Pos Δ","clicks_current":"Clicks"}
    ) if not position_losers.empty else '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">No data.</p>'

    lost_tbl = html_table_from_df(lost_visibility,
        ["page","category","priority","impressions_previous","impressions_current"],
        {"page":"Page","category":"Category","priority":"Priority","impressions_previous":"Prev Impr","impressions_current":"Curr Impr"}
    ) if not lost_visibility.empty else '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">No data.</p>'

    # ── Horizontal rule between sections ──────────────────────────────────
    HR = '<hr style="border:none;border-top:4px solid #000;margin:40px 0;">'

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Critical Landing Pages Performance</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=Source+Serif+4:ital,wght@0,300;0,400;0,600;1,400&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

/* ── Global horizontal line texture ── */
html {{
    background: #fff;
    background-image: repeating-linear-gradient(
        0deg,
        transparent,
        transparent 1px,
        #000 1px,
        #000 2px
    );
    background-size: 100% 4px;
    background-attachment: fixed;
}}
html::before {{
    content: '';
    position: fixed;
    inset: 0;
    background: rgba(255,255,255,0.97);
    pointer-events: none;
    z-index: 0;
}}

body {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 14px;
    color: #000;
    background: transparent;
    line-height: 1.625;
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 40px 80px;
    position: relative;
    z-index: 1;
}}

/* ── Header ── */
.site-header {{
    background: #000;
    color: #fff;
    padding: 40px 48px;
    margin: 0 -40px 0;
    position: relative;
    overflow: hidden;
}}
.site-header::before {{
    content: '';
    position: absolute;
    inset: 0;
    background-image: repeating-linear-gradient(
        90deg,
        transparent,
        transparent 1px,
        #fff 1px,
        #fff 2px
    );
    background-size: 4px 100%;
    opacity: 0.03;
    pointer-events: none;
}}
.site-header__eyebrow {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    color: #999;
    margin-bottom: 12px;
}}
.site-header__title {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: clamp(32px, 5vw, 64px);
    font-weight: 900;
    line-height: 1;
    letter-spacing: -0.02em;
    color: #fff;
    margin-bottom: 16px;
}}
.site-header__meta {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #666;
    letter-spacing: 0.05em;
    display: flex;
    align-items: center;
    gap: 16px;
}}
.site-header__meta::before {{
    content: '';
    display: inline-block;
    width: 24px;
    height: 2px;
    background: #fff;
    flex-shrink: 0;
}}

/* ── Section wrapper ── */
.section {{
    padding: 40px 0;
}}

/* ── Section title ── */
.section-title {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: #000;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 16px;
}}
.section-title::before {{
    content: '';
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #000;
    flex-shrink: 0;
}}

/* ── KPI grid ── */
.kpi-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 2px;
    margin-bottom: 0;
    border: 2px solid #000;
}}
.kpi-grid > div {{
    border-right: 2px solid #000;
}}
.kpi-grid > div:last-child {{ border-right: none; }}

/* ── Report section ── */
.report-section {{
    background: #fff;
    border: 2px solid #000;
    padding: 28px 32px;
    margin-bottom: 0;
}}

/* ── Thick rule ── */
.rule-thick {{
    border: none;
    border-top: 4px solid #000;
    margin: 0;
}}

{get_extra_css()}

/* ── Responsive ── */
@media (max-width: 768px) {{
    body {{ padding: 0 20px 60px; }}
    .site-header {{ padding: 28px 24px; margin: 0 -20px 0; }}
    .kpi-grid {{ grid-template-columns: 1fr 1fr; }}
    .chart-row-2 {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>

<!-- ══ HEADER ══════════════════════════════════════════════════════ -->
<header class="site-header">
  <div class="site-header__eyebrow">Google Search Console</div>
  <h1 class="site-header__title">Critical Landing<br>Pages</h1>
  <div class="site-header__meta">
    {current_start} → {current_end} &nbsp;/&nbsp; prev {previous_start} → {previous_end}
  </div>
</header>

<hr class="rule-thick">

<!-- ══ EXECUTIVE SUMMARY ══════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Executive Summary</div>
  <div class="exec-panel">
    <ul class="exec-bullets">{bullet_items}</ul>
  </div>
</div>

<hr class="rule-thick">

<!-- ══ KPI CARDS ══════════════════════════════════════════════════ -->
<div class="section" style="padding-top:0;">
  <div class="kpi-grid">{kpi_grid}</div>
</div>

<hr class="rule-thick">

<!-- ══ PERFORMANCE OVERVIEW ══════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Performance Overview</div>
  <div class="report-section">
    <div class="col-header">Current vs Previous Week</div>
    {_chart_wrap(charts.get("kpi"), "KPI comparison")}
  </div>
</div>

{HR}

<!-- ══ TOP DEMAND DRIVERS ════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Top Demand Drivers</div>
  <div class="report-section">
    {_chart_wrap(charts.get("top_pages"), "Top landing pages by clicks")}
  </div>
</div>

{HR}

<!-- ══ WINNERS & LOSERS ══════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Winners &amp; Losers</div>
  <div class="report-section">
    <div class="col-header">Traffic Winners &amp; Losers</div>
    {_chart_wrap(charts.get("traffic_changes"), "Traffic winners & losers")}
    <div class="col-header">Position Movement</div>
    {_chart_wrap(charts.get("position_changes"), "Position movement")}
  </div>
</div>

{HR}

<!-- ══ TRACKED LANDING PAGES ════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Tracked Landing Pages</div>
  <div class="report-section">
    {top_pages_tbl}
  </div>
</div>

{HR}

<!-- ══ TRAFFIC GAINERS ══════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Biggest Traffic Gainers</div>
  <div class="report-section">
    {gainers_tbl}
  </div>
</div>

{HR}

<!-- ══ TRAFFIC LOSERS ═══════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Biggest Traffic Losers</div>
  <div class="report-section">
    {losers_tbl}
  </div>
</div>

{HR}

<!-- ══ POSITION IMPROVEMENTS ════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Best Position Improvements</div>
  <div class="report-section">
    {pos_gainers_tbl}
  </div>
</div>

{HR}

<!-- ══ POSITION DECLINES ════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Biggest Position Declines</div>
  <div class="report-section">
    {pos_losers_tbl}
  </div>
</div>

{HR}

<!-- ══ LOST VISIBILITY ══════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Lost Visibility</div>
  <div class="report-section">
    {lost_tbl}
  </div>
</div>

{HR}

<!-- ══ FOOTER ════════════════════════════════════════════════════ -->
<footer style="padding:32px 0;display:flex;justify-content:space-between;align-items:center;">
  <span style="font-family:'Playfair Display',Georgia,serif;font-size:13px;font-weight:700;letter-spacing:0.05em;">CIM SEO Intelligence</span>
  <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#525252;text-transform:uppercase;letter-spacing:0.12em;">Generated {date.today().strftime('%B %d, %Y')}</span>
</footer>

</body>
</html>"""

    with open("landing_pages_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("Saved landing_pages_summary.html")


# ═══════════════════
# SELF-CONTAINED HTML (base64-embed all chart images)
# ═══════════════════
def embed_images_as_base64(html_content: str) -> str:
    """Replace all local file src= paths with inline base64 data URIs."""
    def replace_src(match):
        src = match.group(1)
        img_path = Path(src)
        if img_path.exists():
            ext  = img_path.suffix.lstrip(".").lower()
            mime = "image/png" if ext == "png" else f"image/{ext}"
            b64  = base64.b64encode(img_path.read_bytes()).decode()
            return f'src="data:{mime};base64,{b64}"'
        return match.group(0)  # leave unchanged if file not found

    return re.sub(r'src="([^"]+\.(png|jpg|jpeg|svg|gif))"', replace_src, html_content)


def generate_self_contained_html():
    """Read landing_pages_summary.html, embed all chart images as base64, write final file."""
    raw = Path("landing_pages_summary.html").read_text(encoding="utf-8")
    final = embed_images_as_base64(raw)
    Path("landing_pages_summary_final.html").write_text(final, encoding="utf-8")
    size_kb = len(final.encode()) // 1024
    print(f"Saved landing_pages_summary_final.html ({size_kb} KB, self-contained)")




def upload_to_monday():
    """Upload self-contained HTML to Monday.com."""
    api_token = os.getenv("MONDAY_API_TOKEN")
    item_id   = os.getenv("MONDAY_ITEM_ID")

    if not api_token or not item_id:
        print("Monday upload skipped: MONDAY_API_TOKEN or MONDAY_ITEM_ID not configured.")
        return

    # Step 1 — create a text update on the item
    body_text = (
        "Critical Landing Pages Report attached as a self-contained HTML file. "
        "Open in any browser — all charts are embedded inline."
    )
    update_query = """
    mutation ($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) { id }
    }
    """
    resp = requests.post(
        "https://api.monday.com/v2",
        headers={"Authorization": api_token, "Content-Type": "application/json"},
        json={"query": update_query, "variables": {"item_id": str(item_id), "body": body_text}},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday update creation failed: {data['errors']}")
    update_id = data["data"]["create_update"]["id"]

    # Step 2 — attach the self-contained HTML file to that update
    file_query = """
    mutation ($update_id: ID!, $file: File!) {
      add_file_to_update(update_id: $update_id, file: $file) { id }
    }
    """
    html_path = Path("landing_pages_summary_final.html")
    if not html_path.exists():
        print("Monday file attach skipped: landing_pages_summary_final.html not found.")
        return

    with open(html_path, "rb") as f:
        file_resp = requests.post(
            "https://api.monday.com/v2/file",
            headers={"Authorization": api_token},
            data={
                "query": file_query,
                "variables": '{"update_id": "' + str(update_id) + '", "file": null}',
                "map": '{"file": ["variables.file"]}',
            },
            files={"file": ("critical-landing-pages.html", f, "text/html")},
            timeout=120,
        )
    file_resp.raise_for_status()
    file_data = file_resp.json()
    if "errors" in file_data:
        raise RuntimeError(f"Monday file attach failed: {file_data['errors']}")
    print("Uploaded critical-landing-pages.html to Monday.com successfully.")


# ═══════════════════
# MAIN
# ═══════════════════
def main():
    print("Critical Landing Pages Report — starting")
    service = get_service()
    tracked_df = load_tracked_pages()

    current_start, current_end, previous_start, previous_end = get_weekly_date_windows()
    print(f"Current:  {current_start} → {current_end}")
    print(f"Previous: {previous_start} → {previous_end}")

    # Fetch data
    current_page_df = fetch_page_data(service, current_start, current_end, row_limit=1000)
    previous_page_df = fetch_page_data(service, previous_start, previous_end, row_limit=1000)

    # Build snapshots
    current_snapshot_df = build_page_snapshot(tracked_df, current_page_df)
    previous_snapshot_df = build_page_snapshot(tracked_df, previous_page_df)

    # Prepare comparison
    comparison_df = prepare_comparison(current_snapshot_df, previous_snapshot_df)

    # Save CSV outputs
    current_snapshot_df.to_csv("tracked_pages_current_week.csv", index=False)
    previous_snapshot_df.to_csv("tracked_pages_previous_week.csv", index=False)
    comparison_df.to_csv("tracked_pages_comparison.csv", index=False)

    traffic_gainers = comparison_df.sort_values(by="clicks_change", ascending=False)
    traffic_losers = comparison_df.sort_values(by="clicks_change", ascending=True)
    position_gainers = comparison_df[comparison_df["position_improved"]].sort_values(by="position_change", ascending=True)
    position_losers = comparison_df[comparison_df["position_declined"]].sort_values(by="position_change", ascending=False)

    traffic_gainers.to_csv("page_traffic_gainers.csv", index=False)
    traffic_losers.to_csv("page_traffic_losers.csv", index=False)
    position_gainers.to_csv("page_position_gainers.csv", index=False)
    position_losers.to_csv("page_position_losers.csv", index=False)
    print("✓ Saved CSV outputs")

    # Build unified executive summary
    print("Building executive summary…")
    unified_bullets = build_unified_executive_bullets(
        comparison_df,
        current_start,
        current_end,
        previous_start,
        previous_end
    )

    # Generate reports
    write_markdown_summary(comparison_df, unified_bullets, current_start, current_end, previous_start, previous_end)
    write_html_summary(comparison_df, unified_bullets, current_start, current_end, previous_start, previous_end)
    generate_self_contained_html()

    # Upload to Monday.com (non-fatal)
    try:
        upload_to_monday()
    except Exception as e:
        print(f"Monday upload failed: {e}")

    print("Critical Landing Pages Report — complete")


if __name__ == "__main__":
    main()
