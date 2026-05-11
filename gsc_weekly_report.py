# GSC Weekly Report - Part 1 (imports and constants)
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import os, html, math, base64, re

from google.oauth2 import service_account
from googleapiclient.discovery import build
import google_auth_httplib2
import httplib2
from openai import OpenAI
import pandas as pd
import json
from html_report_utils import (
    mm_html_shell, mm_section, mm_kpi_card, mm_kpi_grid,
    mm_apex_chart, mm_report_section, mm_col_header
)

from google_sheets_db import append_to_sheet
from pdf_report_formatter import get_pdf_css, build_card, format_pct_change
from monday_utils import upload_pdf_to_monday as _upload_pdf
from seo_utils import get_weekly_date_windows, short_url, safe_pct_change

# ── Auth / config ──────────────────────────────────────────────────────────────
SCOPES    = ["https://www.googleapis.com/auth/webmasters.readonly"]
KEY_FILE  = "gsc-key.json"
SITE_URL  = os.environ["GSC_PROPERTY"]
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID   = os.getenv("MONDAY_ITEM_ID")
CHARTS_DIR = Path("charts")

ROW_LIMIT = 25000   # raised from 1000 for max collection

# ── Brand palette ──────────────────────────────────────────────────────────────
C_NAVY   = "#212878"
C_TEAL   = "#2A9D8F"
C_CORAL  = "#E76F51"
C_SLATE  = "#6C757D"
C_GREEN  = "#059669"
C_RED    = "#DC2626"
C_AMBER  = "#D97706"
C_LIGHT  = "#F1F5F9"
C_BORDER = "#E2E8F0"

BRANDED_PATTERN = r"cim connect|vancouver 2026|cim 2026|cim vancouver"



# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def get_credentials():
    """Return a fresh Credentials object. Called per-thread so each gets its own."""
    return service_account.Credentials.from_service_account_file(KEY_FILE, scopes=SCOPES)


def get_service():
    """Build a single GSC service for sequential use (main thread only)."""
    authed_http = google_auth_httplib2.AuthorizedHttp(
        get_credentials(), http=httplib2.Http(timeout=120)
    )
    return build("searchconsole", "v1", http=authed_http, cache_discovery=False)


def _build_thread_service():
    """Build a fresh, independent GSC service for use inside a worker thread."""
    authed_http = google_auth_httplib2.AuthorizedHttp(
        get_credentials(), http=httplib2.Http(timeout=120)
    )
    return build("searchconsole", "v1", http=authed_http, cache_discovery=False)


def _empty_df(dimension_name):
    return pd.DataFrame(columns=[dimension_name, "clicks", "impressions", "ctr", "position"])


def fetch_dimension_data(service, start_date, end_date, dimension, row_limit=ROW_LIMIT, extra_filters=None):
    """Fetch a single dimension from GSC searchanalytics."""
    body = {
        "startDate": start_date.isoformat(),
        "endDate":   end_date.isoformat(),
        "dimensions": [dimension],
        "rowLimit":   row_limit,
    }
    if extra_filters:
        body["dimensionFilterGroups"] = extra_filters

    try:
        resp = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
    except Exception as e:
        print(f"GSC API error fetching {dimension}: {e}")
        return _empty_df(dimension)

    rows = resp.get("rows", [])
    data = [
        {
            dimension:    row["keys"][0],
            "clicks":     row.get("clicks", 0),
            "impressions":row.get("impressions", 0),
            "ctr":        row.get("ctr", 0),
            "position":   row.get("position", 0),
        }
        for row in rows
    ]
    return pd.DataFrame(data) if data else _empty_df(dimension)


def fetch_date_trend(service, start_date, end_date):
    """Fetch daily clicks + impressions for trend line chart."""
    body = {
        "startDate":  start_date.isoformat(),
        "endDate":    end_date.isoformat(),
        "dimensions": ["date"],
        "rowLimit":   25,
    }
    try:
        resp = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
    except Exception as e:
        print(f"GSC API error fetching date trend: {e}")
        return pd.DataFrame()

    rows = resp.get("rows", [])
    data = [
        {
            "date":        row["keys"][0],
            "clicks":      row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr":         row.get("ctr", 0),
            "position":    row.get("position", 0),
        }
        for row in rows
    ]
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")


def fetch_device_split(service, start_date, end_date):
    """Fetch clicks/impressions broken down by device."""
    body = {
        "startDate":  start_date.isoformat(),
        "endDate":    end_date.isoformat(),
        "dimensions": ["device"],
        "rowLimit":   10,
    }
    try:
        resp = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
    except Exception as e:
        print(f"GSC API error fetching device split: {e}")
        return pd.DataFrame()

    rows = resp.get("rows", [])
    data = [
        {
            "device":      row["keys"][0],
            "clicks":      row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr":         row.get("ctr", 0),
            "position":    row.get("position", 0),
        }
        for row in rows
    ]
    return pd.DataFrame(data) if data else pd.DataFrame()


def fetch_search_appearance(service, start_date, end_date):
    """Fetch impressions by search appearance / rich result type."""
    body = {
        "startDate":  start_date.isoformat(),
        "endDate":    end_date.isoformat(),
        "dimensions": ["searchAppearance"],
        "rowLimit":   25,
    }
    try:
        resp = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
    except Exception as e:
        print(f"GSC API error fetching search appearance: {e}")
        return pd.DataFrame()

    rows = resp.get("rows", [])
    data = [
        {
            "appearance":  row["keys"][0],
            "clicks":      row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr":         row.get("ctr", 0),
        }
        for row in rows
    ]
    return pd.DataFrame(data) if data else pd.DataFrame()


def fetch_all_data_parallel(current_start, current_end, previous_start, previous_end):
    """Run all GSC API calls in parallel. Each worker builds its own service object
    so there is no shared-state / thread-safety issue with googleapiclient."""

    def _run(fn, *args):
        svc = _build_thread_service()
        return fn(svc, *args)

    tasks = {
        "current_query":  (fetch_dimension_data, current_start,  current_end,  "query"),
        "previous_query": (fetch_dimension_data, previous_start, previous_end, "query"),
        "current_page":   (fetch_dimension_data, current_start,  current_end,  "page"),
        "previous_page":  (fetch_dimension_data, previous_start, previous_end, "page"),
        "trend_current":  (fetch_date_trend,     current_start,  current_end),
        "trend_previous": (fetch_date_trend,     previous_start, previous_end),
        "device_current": (fetch_device_split,   current_start,  current_end),
        "appearance":     (fetch_search_appearance, current_start, current_end),
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
                results[key] = pd.DataFrame()

    return results



# ══════════════════════════════════════════════════════════════════════════════
# DATA PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

def prepare_comparison(current_df, previous_df, key_column):
    """Merge current and previous period DataFrames and compute deltas."""
    cur = current_df.rename(columns={
        "clicks": "clicks_current", "impressions": "impressions_current",
        "ctr": "ctr_current", "position": "position_current",
    })
    prev = previous_df.rename(columns={
        "clicks": "clicks_previous", "impressions": "impressions_previous",
        "ctr": "ctr_previous", "position": "position_previous",
    })
    merged = pd.merge(cur, prev, on=key_column, how="outer").fillna(0)

    # Ensure numeric dtypes — outer merge on two empty DFs can leave object columns
    for col in ["clicks_current", "clicks_previous", "impressions_current", "impressions_previous",
                "ctr_current", "ctr_previous", "position_current", "position_previous"]:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)

    merged["clicks_change"]      = merged["clicks_current"]      - merged["clicks_previous"]
    merged["impressions_change"] = merged["impressions_current"] - merged["impressions_previous"]
    merged["ctr_change"]         = merged["ctr_current"]         - merged["ctr_previous"]
    merged["position_change"]    = merged["position_current"]    - merged["position_previous"]
    merged["is_new"]  = (merged["clicks_previous"] == 0) & (merged["clicks_current"] > 0)
    merged["is_lost"] = (merged["clicks_previous"] > 0) & (merged["clicks_current"] == 0)

    # Round position values to 1 decimal place for clean display
    for col in ["position_current", "position_previous", "position_change"]:
        if col in merged.columns:
            merged[col] = merged[col].round(1)

    return merged.sort_values("clicks_current", ascending=False)


def calculate_kpis(df):
    """Return a dict of aggregate KPI metrics from a comparison DataFrame."""
    clicks_curr  = df["clicks_current"].sum()
    clicks_prev  = df["clicks_previous"].sum()
    impr_curr    = df["impressions_current"].sum()
    impr_prev    = df["impressions_previous"].sum()
    ctr_curr     = clicks_curr / impr_curr  if impr_curr  else 0
    ctr_prev     = clicks_prev / impr_prev  if impr_prev  else 0
    has_impr_cur = df["impressions_current"] > 0
    has_impr_pre = df["impressions_previous"] > 0
    pos_curr = df.loc[has_impr_cur, "position_current"].mean()  if has_impr_cur.any()  else 0
    pos_prev = df.loc[has_impr_pre, "position_previous"].mean() if has_impr_pre.any() else 0
    return {
        "clicks_current": clicks_curr,   "clicks_previous": clicks_prev,
        "impressions_current": impr_curr, "impressions_previous": impr_prev,
        "ctr_current": ctr_curr,          "ctr_previous": ctr_prev,
        "position_current": pos_curr,     "position_previous": pos_prev,
    }


def position_band_html(pos):
    """Return a coloured badge HTML string for a ranking position."""
    try:
        p = float(pos)
    except (TypeError, ValueError):
        return ""
    if p <= 3:
        return '<span class="badge badge-top3">Top 3</span>'
    if p <= 10:
        return '<span class="badge badge-p1">Page 1</span>'
    if p <= 20:
        return '<span class="badge badge-p2">Page 2</span>'
    return '<span class="badge badge-p3">Page 3+</span>'


def _fmt(val, decimals=0, pct=False):
    """Lightweight number formatter for table cells."""
    try:
        v = float(val)
        if math.isnan(v):
            return "-"
        if pct:
            return f"{v:.2%}"
        if decimals == 0:
            return f"{v:,.0f}"
        # Cap position/decimal values at 2 decimal places max
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

def build_deterministic_bullets(kpis, query_df):
    """Return a list of plain-text bullet strings from hard metrics."""
    bullets = []
    clicks_curr = kpis["clicks_current"]
    clicks_prev = kpis["clicks_previous"]
    impr_curr   = kpis["impressions_current"]
    impr_prev   = kpis["impressions_previous"]
    ctr_curr    = kpis["ctr_current"]
    ctr_prev    = kpis["ctr_previous"]
    pos_curr    = kpis["position_current"]
    pos_prev    = kpis["position_previous"]

    # Clicks
    pct_clicks = safe_pct_change(clicks_curr, clicks_prev)
    if pct_clicks is not None:
        direction = "up" if clicks_curr > clicks_prev else ("down" if clicks_curr < clicks_prev else "flat")
        pct_str   = f" ({pct_clicks:+.1%})" if pct_clicks else ""
        bullets.append(f"Clicks are {direction} week over week: {clicks_curr:,.0f} vs {clicks_prev:,.0f}{pct_str}.")
    else:
        bullets.append(f"Clicks this week: {clicks_curr:,.0f} (no prior-period baseline).")

    # Impressions
    pct_impr = safe_pct_change(impr_curr, impr_prev)
    if pct_impr is not None:
        if abs(pct_impr) < 0.03:
            bullets.append(f"Impressions are essentially flat: {impr_curr:,.0f} vs {impr_prev:,.0f}.")
        else:
            direction = "up" if impr_curr > impr_prev else "down"
            bullets.append(f"Impressions are {direction} {pct_impr:+.1%}: {impr_curr:,.0f} vs {impr_prev:,.0f}.")

    # CTR
    if ctr_curr > ctr_prev:
        bullets.append(f"CTR improved to {ctr_curr:.2%} (from {ctr_prev:.2%}), indicating better search-result efficiency.")
    elif ctr_curr < ctr_prev:
        bullets.append(f"CTR declined to {ctr_curr:.2%} (from {ctr_prev:.2%}).")
    else:
        bullets.append(f"CTR was flat at {ctr_curr:.2%}.")

    # Position
    if pos_curr > 0 and pos_prev > 0:
        if pos_curr < pos_prev:
            bullets.append(f"Average position improved to {pos_curr:.1f} (from {pos_prev:.1f}).")
        elif pos_curr > pos_prev:
            bullets.append(f"Average position weakened to {pos_curr:.1f} (from {pos_prev:.1f}).")
        else:
            bullets.append(f"Average position unchanged at {pos_curr:.1f}.")

    # New / lost queries
    new_count  = int(query_df["is_new"].sum())
    lost_count = int(query_df["is_lost"].sum())
    if new_count:
        bullets.append(f"{new_count} new quer{'y' if new_count == 1 else 'ies'} appeared this week with no prior-period clicks.")
    if lost_count:
        bullets.append(f"{lost_count} quer{'y' if lost_count == 1 else 'ies'} that had clicks last week recorded zero clicks this week.")

    # Branded concentration
    top25 = query_df.nlargest(25, "clicks_current")
    branded_mask   = top25["query"].astype(str).str.contains(BRANDED_PATTERN, case=False, na=False)
    branded_clicks = top25.loc[branded_mask, "clicks_current"].sum()
    total_top      = top25["clicks_current"].sum()
    if total_top > 0 and (branded_clicks / total_top) >= 0.4:
        bullets.append("Traffic remains heavily concentrated in CIM Connect / Vancouver 2026 branded demand.")

    return bullets


def build_ai_bullets(kpis, query_df, page_df, current_start, current_end, previous_start, previous_end):
    """Call Groq/Llama and return a list of bullet strings (no headings, no markdown)."""
    if not GROQ_API_KEY:
        return []

    top_queries = query_df.nlargest(10, "clicks_current")[
        ["query", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"]
    ]
    top_pages = page_df.nlargest(10, "clicks_current")[
        ["page", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"]
    ]

    prompt = f"""You are writing a concise executive SEO brief for a corporate stakeholder report.

Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.
Each bullet is one sentence. Maximum 10 bullets total.
Cover: what changed and why it matters, key wins, risks or watchouts, one or two recommended actions.
Do not repeat raw numbers already obvious from the data — interpret and prioritise.
Professional corporate tone. Under 200 words total.

Current period: {current_start} to {current_end}
Previous period: {previous_start} to {previous_end}

Overall metrics:
- Clicks: {kpis['clicks_current']:.0f} vs {kpis['clicks_previous']:.0f}
- Impressions: {kpis['impressions_current']:.0f} vs {kpis['impressions_previous']:.0f}
- CTR: {kpis['ctr_current']:.2%} vs {kpis['ctr_previous']:.2%}
- Avg position: {kpis['position_current']:.2f} vs {kpis['position_previous']:.2f}

Top queries:
{top_queries.to_csv(index=False)}

Top pages:
{top_pages.to_csv(index=False)}
"""

    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write polished weekly executive SEO briefs as bullet points only."},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.2,
        )
        raw = resp.choices[0].message.content.strip()
        bullets = []
        for line in raw.splitlines():
            clean = line.strip().lstrip("-•*·▪▸").strip()
            # Strip any stray markdown bold/italic
            clean = clean.replace("**", "").replace("__", "").replace("*", "").strip()
            if clean:
                bullets.append(clean)
        return bullets
    except Exception as e:
        print(f"AI analysis failed: {e}")
        return []


def build_unified_executive_bullets(kpis, query_df, page_df,
                                    current_start, current_end,
                                    previous_start, previous_end):
    """Merge deterministic + AI bullets into one flat list."""
    det_bullets = build_deterministic_bullets(kpis, query_df)
    ai_bullets  = build_ai_bullets(kpis, query_df, page_df,
                                   current_start, current_end,
                                   previous_start, previous_end)
    return det_bullets + ai_bullets



# ══════════════════════════════════════════════════════════════════════════════
# HTML TABLE BUILDERS  (inline bar + badge variants)
# ══════════════════════════════════════════════════════════════════════════════

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


def build_top_table(df, key_col, is_page=False, n=15):
    """Top queries or pages table with inline click bar, position badge, and delta columns."""
    if df.empty:
        return "<p style='color:#94A3B8;font-size:10px;'>No data available.</p>"

    work = df.nlargest(n, "clicks_current").copy()
    max_clicks = work["clicks_current"].max()
    max_impr   = work["impressions_current"].max()

    headers = ["#", "Query" if not is_page else "Page",
               "Clicks", "Impr", "CTR", "Pos", "Band", "Clicks Δ", "Pos Δ"]
    th = "".join(f"<th>{h}</th>" for h in headers)

    rows_html = []
    for i, (_, row) in enumerate(work.iterrows(), 1):
        # Truncate more aggressively for pages to prevent wrapping
        max_len = 45 if is_page else 40
        label = short_url(str(row[key_col]), max_len)
        click_bar  = _bar_cell(row["clicks_current"], max_clicks, C_NAVY)
        impr_bar   = _bar_cell(row["impressions_current"], max_impr, C_TEAL)
        ctr_str    = _fmt(row["ctr_current"], pct=True)
        pos_str    = _fmt(row["position_current"], decimals=1)
        band       = position_band_html(row["position_current"])
        click_dlt  = _delta_html(row["clicks_change"])
        pos_dlt    = _delta_html(row["position_change"], decimals=1, lower_is_better=True)

        rows_html.append(
            f"<tr>"
            f"<td style='color:#94A3B8;font-size:9px;width:18px;'>{i}</td>"
            f"<td class='url-cell'>{html.escape(label)}</td>"
            f"{click_bar}{impr_bar}"
            f"<td style='white-space:nowrap;'>{ctr_str}</td>"
            f"<td style='white-space:nowrap;'>{pos_str}</td>"
            f"<td style='white-space:nowrap;'>{band}</td>"
            f"<td style='white-space:nowrap;'>{click_dlt}</td>"
            f"<td style='white-space:nowrap;'>{pos_dlt}</td>"
            f"</tr>"
        )

    return (
        f"<table><thead><tr>{th}</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table>"
    )


def build_movers_table(gainers_df, losers_df, key_col, n=10):
    """Single color-coded table: losers on top, gainers below, sorted by click change."""
    if gainers_df.empty and losers_df.empty:
        return "<p style='color:#94A3B8;font-size:10px;'>No movement data available.</p>"

    gainers = gainers_df.nlargest(n, "clicks_change").copy()
    losers  = losers_df.nsmallest(n, "clicks_change").copy()
    merged  = pd.concat([losers, gainers], ignore_index=True)

    headers = ["Query" if key_col == "query" else "Page",
               "Prev Clicks", "Curr Clicks", "Click Δ", "Pos Δ"]
    th = "".join(f"<th>{h}</th>" for h in headers)

    rows_html = []
    for _, row in merged.iterrows():
        change = float(row["clicks_change"])
        is_gain = change >= 0
        border_color = C_TEAL if is_gain else C_CORAL
        label = short_url(str(row[key_col]), 60)
        click_dlt = _delta_html(row["clicks_change"])
        pos_dlt   = _delta_html(row["position_change"], decimals=1, lower_is_better=True)

        rows_html.append(
            f'<tr style="border-left:3px solid {border_color};">'
            f"<td class='url-cell'>{html.escape(label)}</td>"
            f"<td style='white-space:nowrap;'>{_fmt(row['clicks_previous'])}</td>"
            f"<td style='white-space:nowrap;'>{_fmt(row['clicks_current'])}</td>"
            f"<td style='white-space:nowrap;'>{click_dlt}</td>"
            f"<td style='white-space:nowrap;'>{pos_dlt}</td>"
            f"</tr>"
        )

    return (
        f"<table><thead><tr>{th}</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table>"
    )


def build_new_lost_block(query_df):
    """Two mini-tables: new queries this week + queries that dropped to zero."""
    new_df  = query_df[query_df["is_new"]].nlargest(10, "clicks_current")
    lost_df = query_df[query_df["is_lost"]].nlargest(10, "clicks_previous")

    def mini_table(df, key_col, val_col, val_label, border_color):
        if df.empty:
            return f"<p style='color:#94A3B8;font-size:9px;'>None this week.</p>"
        th = f"<th>Query</th><th>{val_label}</th><th>Impr</th>"
        rows = []
        for _, row in df.iterrows():
            label = html.escape(short_url(str(row[key_col]), 38))
            impr_val = row.get("impressions_current", row.get("impressions_previous", 0))
            rows.append(
                f'<tr style="border-left:3px solid {border_color};">'
                f"<td class='url-cell'>{label}</td>"
                f"<td style='white-space:nowrap;'>{_fmt(row[val_col])}</td>"
                f"<td style='white-space:nowrap;'>{_fmt(impr_val)}</td>"
                f"</tr>"
            )
        return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(rows)}</tbody></table>"

    new_html  = mini_table(new_df,  "query", "clicks_current",  "Clicks",      C_TEAL)
    lost_html = mini_table(lost_df, "query", "clicks_previous", "Prev Clicks", C_CORAL)

    # CSS Grid two-column — works in browser, no WeasyPrint needed
    return f"""
<div class="nl-grid">
  <div>
    <div class="section-label" style="color:{C_TEAL};">&#9650; New This Week ({len(new_df)})</div>
    {new_html}
  </div>
  <div>
    <div class="section-label" style="color:{C_CORAL};">&#9660; Lost This Week ({len(lost_df)})</div>
    {lost_html}
  </div>
</div>
"""



# ══════════════════════════════════════════════════════════════════════════════
# CSS  (extends pdf_report_formatter base styles)
# ══════════════════════════════════════════════════════════════════════════════

def get_extra_css():
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

    /* ── New/lost two-column ────────────────────────────────────── */
    .nl-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 24px;
        margin-bottom: 0;
    }

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


# ══════════════════════════════════════════════════════════════════════════════
# HTML REPORT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# SELF-CONTAINED HTML  (base64-embed all chart images)
# ══════════════════════════════════════════════════════════════════════════════

def _img_tag(path, alt="chart"):
    """Return an <img> tag. Path is a local file — will be base64-embedded later."""
    if not path:
        return ""
    return f'<img src="{html.escape(str(path))}" alt="{html.escape(alt)}" style="width:100%;display:block;border-radius:6px;border:1px solid #E2E8F0;">'


def _chart_wrap(path, alt="chart"):
    """Single full-width chart."""
    if not path:
        return ""
    return f'<div class="chart-wrap">{_img_tag(path, alt)}</div>'


def _chart_row_2(path_a, alt_a, path_b, alt_b):
    """Two charts side-by-side in a CSS Grid row."""
    a = _img_tag(path_a, alt_a) if path_a else ""
    b = _img_tag(path_b, alt_b) if path_b else ""
    if not a and not b:
        return ""
    return f'<div class="chart-row-2"><div>{a}</div><div>{b}</div></div>'


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
    """Read weekly_summary.html, embed all chart images as base64, write final file."""
    raw = Path("weekly_summary.html").read_text(encoding="utf-8")
    final = embed_images_as_base64(raw)
    Path("weekly_summary_final.html").write_text(final, encoding="utf-8")
    size_kb = len(final.encode()) // 1024
    print(f"Saved weekly_summary_final.html ({size_kb} KB, self-contained)")


def write_html_summary(query_df, page_df, exec_bullets, kpis,
                       chart_paths, device_df, appearance_df,
                       current_start, current_end, previous_start, previous_end,
                       trend_curr, trend_prev):
    """Build the final GSC report with ApexCharts integration."""
    today = date.today().strftime("%B %d, %Y")

    # 1. KPI Grid
    kpi_cards = (
        mm_kpi_card("Total Clicks",    kpis["clicks_current"],      kpis["clicks_previous"]) +
        mm_kpi_card("Impressions",     kpis["impressions_current"], kpis["impressions_previous"]) +
        mm_kpi_card("Average CTR",     kpis["ctr_current"],         kpis["ctr_previous"], is_pct=True) +
        mm_kpi_card("Average Position", kpis["position_current"],    kpis["position_previous"], lower_better=True)
    )
    kpi_grid = mm_kpi_grid(kpi_cards)

    # 2. Charts (ApexCharts)
    
    # 7-Day Search Trend (Area)
    trend_chart = ""
    if not trend_curr.empty:
        trend_chart = mm_apex_chart("gsc_trend", {
            "chart": {"type": "area", "height": 350},
            "series": [
                {"name": "Current Clicks", "data": [float(x) for x in trend_curr["clicks"].tolist()]},
                {"name": "Previous Clicks", "data": [float(x) for x in trend_prev["clicks"].tolist()] if not trend_prev.empty else []}
            ],
            "xaxis": {"categories": [pd.to_datetime(d).strftime("%a %d") for d in trend_curr["date"]]},
            "title": {"text": "Weekly Search Visibility Trend"},
            "colors": ["#212878", "#94A3B8"]
        })

    # Device Split (Donut)
    device_chart = ""
    if not device_df.empty:
        device_chart = mm_apex_chart("device_split", {
            "chart": {"type": "donut", "height": 350},
            "series": [float(x) for x in device_df["clicks"].tolist()],
            "labels": device_df["device"].str.capitalize().tolist(),
            "title": {"text": "Clicks by Device Type"}
        })

    # Query Movers (Bar)
    movers_chart = ""
    if not query_df.empty:
        movers = pd.concat([
            query_df.nsmallest(25, "clicks_change"),
            query_df.nlargest(25, "clicks_change")
        ]).sort_values("clicks_change")
        movers_chart = mm_apex_chart("query_movers", {
            "chart": {"type": "bar", "height": 400},
            "series": [{"name": "Click Change", "data": [float(x) for x in movers["clicks_change"].tolist()]}],
            "xaxis": {"categories": movers["query"].apply(lambda x: short_url(str(x), 30)).tolist()},
            "plotOptions": {"bar": {"horizontal": True, "colors": {"ranges": [{"from": -9999, "to": -0.1, "color": "#E76F51"}, {"from": 0.1, "to": 9999, "color": "#2A9D8F"}]}}},
            "title": {"text": "Top WoW Query Movers (Click Δ)"}
        })

    # 3. Body
    body_content = (
        mm_section("Executive Summary", 
            mm_report_section(mm_exec_bullets(exec_bullets))
        ) +
        '<div class="section" style="padding-top:0;">' + kpi_grid + '</div>'
        '<hr class="rule-thick">' +
        mm_section("Search Performance Deep-Dive",
            mm_report_section(
                '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#64748B;margin-bottom:16px;">\u24d8 <b>How to read:</b> Compares this week against the previous. Area chart shows search volume stability. Donut shows audience platform preferences.</p>' +
                trend_chart + "<br>" + device_chart
            )
        ) +
        mm_section("Query Dynamics",
            mm_report_section(
                '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#64748B;margin-bottom:16px;">\u24d8 <b>How to read:</b> Teal indicates growing search demand or ranking improvement. Coral indicates loss. Focus on high-impression queries in the coral zone.</p>' +
                movers_chart
            )
        ) +
        mm_section("Deep Performance Tables",
            mm_report_section(
                mm_col_header("Top 50 Queries by Clicks") +
                _build_top_table(query_df, "query", is_page=False, n=50) +
                "<br><br>" +
                mm_col_header("Top 50 Landing Pages by Clicks") +
                _build_top_table(page_df, "page", is_page=True, n=50)
            )
        )
    )

    doc = mm_html_shell(
        title=f"GSC Weekly Report — {today}",
        eyebrow="Google Search Console Intelligence",
        headline="Weekly Search\nPerformance",
        meta_line=f"{current_start} &rarr; {current_end} / prev {previous_start} &rarr; {previous_end}",
        body_content=body_content
    )

    with open("weekly_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("Saved weekly_summary.html with ApexCharts")


# ══════════════════════════════════════════════════════════════════════════════
# MARKDOWN SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def write_markdown_summary(query_df, page_df, exec_bullets, kpis,
                           current_start, current_end, previous_start, previous_end):
    top_queries = query_df.nlargest(10, "clicks_current")
    top_pages   = page_df.nlargest(10, "clicks_current")

    lines = [
        "# GSC Weekly Performance Summary",
        "",
        f"Current period: {current_start} to {current_end}",
        f"Previous period: {previous_start} to {previous_end}",
        "",
        "## Executive Summary",
        "",
    ]
    lines.extend(f"- {b}" for b in exec_bullets)
    lines.extend([
        "",
        "## KPI Snapshot",
        f"- Clicks: {kpis['clicks_current']:,.0f} vs {kpis['clicks_previous']:,.0f}"
        f" ({format_pct_change(kpis['clicks_current'], kpis['clicks_previous'])})",
        f"- Impressions: {kpis['impressions_current']:,.0f} vs {kpis['impressions_previous']:,.0f}"
        f" ({format_pct_change(kpis['impressions_current'], kpis['impressions_previous'])})",
        f"- CTR: {kpis['ctr_current']:.2%} vs {kpis['ctr_previous']:.2%}",
        f"- Avg Position: {kpis['position_current']:.2f} vs {kpis['position_previous']:.2f}",
        "",
        "## Top Queries",
        "",
        top_queries[["query", "clicks_current", "impressions_current",
                     "ctr_current", "position_current"]].to_markdown(index=False),
        "",
        "## Top Pages",
        "",
        top_pages[["page", "clicks_current", "impressions_current",
                   "ctr_current", "position_current"]].to_markdown(index=False),
    ])

    with open("weekly_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Saved weekly_summary.md")


# ══════════════════════════════════════════════════════════════════════════════
# MONDAY UPLOAD  (post HTML body + attach self-contained HTML file)
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_monday():
    """Post a text summary update to Monday.com and attach the self-contained HTML."""
    api_token = os.getenv("MONDAY_API_TOKEN")
    item_id   = os.getenv("MONDAY_ITEM_ID")

    if not api_token or not item_id:
        print("Monday upload skipped: MONDAY_API_TOKEN or MONDAY_ITEM_ID not configured.")
        return

    import requests as _requests

    # Step 1 — create a text update on the item
    body_text = (
        "GSC Weekly Performance Report attached as a self-contained HTML file. "
        "Open in any browser — all charts are embedded inline."
    )
    update_query = """
    mutation ($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) { id }
    }
    """
    resp = _requests.post(
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
    html_path = Path("weekly_summary_final.html")
    if not html_path.exists():
        print("Monday file attach skipped: weekly_summary_final.html not found.")
        return

    with open(html_path, "rb") as f:
        file_resp = _requests.post(
            "https://api.monday.com/v2/file",
            headers={"Authorization": api_token},
            data={
                "query": file_query,
                "variables": '{"update_id": "' + str(update_id) + '", "file": null}',
                "map": '{"file": ["variables.file"]}',
            },
            files={"file": ("gsc-weekly-report.html", f, "text/html")},
            timeout=120,
        )
    file_resp.raise_for_status()
    file_data = file_resp.json()
    if "errors" in file_data:
        raise RuntimeError(f"Monday file attach failed: {file_data['errors']}")
    print("Uploaded gsc-weekly-report.html to Monday.com successfully.")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("GSC Weekly Report — starting")
    current_start, current_end, previous_start, previous_end = get_weekly_date_windows()
    print(f"Current:  {current_start} → {current_end}")
    print(f"Previous: {previous_start} → {previous_end}")

    # ── Fetch all data in parallel (each thread owns its own service) ──────
    print("Fetching GSC data (parallel)…")
    raw = fetch_all_data_parallel(current_start, current_end, previous_start, previous_end)

    current_query_df  = raw.get("current_query",  pd.DataFrame())
    previous_query_df = raw.get("previous_query", pd.DataFrame())
    current_page_df   = raw.get("current_page",   pd.DataFrame())
    previous_page_df  = raw.get("previous_page",  pd.DataFrame())
    trend_curr        = raw.get("trend_current",  pd.DataFrame())
    trend_prev        = raw.get("trend_previous", pd.DataFrame())
    device_df         = raw.get("device_current", pd.DataFrame())
    appearance_df     = raw.get("appearance",     pd.DataFrame())

    # ── Build comparison DataFrames ────────────────────────────────────────
    query_df = prepare_comparison(current_query_df, previous_query_df, "query")
    page_df  = prepare_comparison(current_page_df,  previous_page_df,  "page")
    kpis     = calculate_kpis(query_df)

    # ── Save raw CSVs ──────────────────────────────────────────────────────
    current_query_df.to_csv("weekly_gsc_report.csv",      index=False)
    query_df.to_csv("weekly_comparison.csv",               index=False)
    current_page_df.to_csv("weekly_pages_report.csv",      index=False)
    page_df.to_csv("weekly_pages_comparison.csv",          index=False)

    query_df.nlargest(25, "clicks_current").to_csv("top_queries.csv",    index=False)
    query_df.nlargest(25, "clicks_change").to_csv("biggest_gainers.csv", index=False)
    query_df.nsmallest(25, "clicks_change").to_csv("biggest_losers.csv", index=False)
    page_df.nlargest(25, "clicks_current").to_csv("top_pages.csv",       index=False)
    page_df.nlargest(25, "clicks_change").to_csv("page_gainers.csv",     index=False)
    page_df.nsmallest(25, "clicks_change").to_csv("page_losers.csv",     index=False)

    if not device_df.empty:
        device_df.to_csv("device_split.csv", index=False)
    if not appearance_df.empty:
        appearance_df.to_csv("search_appearance.csv", index=False)

    # ── Google Sheets ──────────────────────────────────────────────────────
    append_to_sheet(query_df,  "GSC_Query_Comparison")
    append_to_sheet(page_df,   "GSC_Page_Comparison")
    if not device_df.empty:
        append_to_sheet(device_df, "GSC_Device_Split")

    # ── Charts ─────────────────────────────────────────────────────────────
    print("Generating charts…")
    chart_paths = build_all_charts(query_df, page_df, kpis,
                                   trend_curr, trend_prev,
                                   device_df, appearance_df)

    # ── Executive bullets (deterministic + AI) ─────────────────────────────
    print("Building executive summary…")
    exec_bullets = build_unified_executive_bullets(
        kpis, query_df, page_df,
        current_start, current_end, previous_start, previous_end,
    )

    # ── Reports ────────────────────────────────────────────────────────────
    write_markdown_summary(query_df, page_df, exec_bullets, kpis,
                           current_start, current_end, previous_start, previous_end)

    write_html_summary(query_df, page_df, exec_bullets, kpis,
                       chart_paths, device_df, appearance_df,
                       current_start, current_end, previous_start, previous_end,
                       trend_curr, trend_prev)

    generate_self_contained_html()

    try:
        upload_to_monday()
    except Exception as e:
        print(f"Monday upload failed: {e}")

    print("GSC Weekly Report — complete")


if __name__ == "__main__":
    main()
