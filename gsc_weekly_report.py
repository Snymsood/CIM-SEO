from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
from weasyprint import HTML
import pandas as pd
import requests
import os
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
KEY_FILE = "gsc-key.json"
SITE_URL = os.environ["GSC_PROPERTY"]
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"
CHARTS_DIR = Path("charts")

ACCENT = "#0F4C81"
ACCENT_2 = "#2A9D8F"
ACCENT_3 = "#E76F51"
ACCENT_4 = "#6C757D"
GRID = "#D9E2EC"
TEXT = "#1F2937"
BG = "#F5F7FB"


def get_service():
    credentials = service_account.Credentials.from_service_account_file(
        KEY_FILE,
        scopes=SCOPES,
    )
    return build("searchconsole", "v1", credentials=credentials)


def empty_dimension_df(dimension_name):
    return pd.DataFrame(columns=[dimension_name, "clicks", "impressions", "ctr", "position"])


def fetch_dimension_data(service, start_date, end_date, dimension, row_limit=250):
    request = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": [dimension],
        "rowLimit": row_limit,
    }

    response = service.searchanalytics().query(
        siteUrl=SITE_URL,
        body=request
    ).execute()

    rows = response.get("rows", [])
    data = []

    for row in rows:
        data.append({
            dimension: row["keys"][0],
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0),
            "position": row.get("position", 0),
        })

    df = pd.DataFrame(data)

    if df.empty:
        return empty_dimension_df(dimension)

    return df


def prepare_comparison(current_df, previous_df, key_column):
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

    merged_df = pd.merge(current_df, previous_df, on=key_column, how="outer").fillna(0)

    merged_df["clicks_change"] = merged_df["clicks_current"] - merged_df["clicks_previous"]
    merged_df["impressions_change"] = merged_df["impressions_current"] - merged_df["impressions_previous"]
    merged_df["ctr_change"] = merged_df["ctr_current"] - merged_df["ctr_previous"]
    merged_df["position_change"] = merged_df["position_current"] - merged_df["position_previous"]

    merged_df["is_new"] = (merged_df["clicks_previous"] == 0) & (merged_df["clicks_current"] > 0)
    merged_df["is_lost"] = (merged_df["clicks_previous"] > 0) & (merged_df["clicks_current"] == 0)

    return merged_df.sort_values(by="clicks_current", ascending=False)


def safe_pct_change(current, previous):
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100


def format_pct_change(current, previous):
    pct = safe_pct_change(current, previous)
    if pct is None:
        return "n/a"
    return f"{pct:+.1f}%"


def format_delta(value, decimals=0):
    if pd.isna(value):
        return ""
    if value > 0:
        return f"+{value:.{decimals}f}"
    return f"{value:.{decimals}f}"


def short_url(url, max_len=58):
    text = str(url)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def build_executive_read(total_clicks_current, total_clicks_previous,
                         total_impressions_current, total_impressions_previous,
                         weighted_ctr_current, weighted_ctr_previous,
                         avg_position_current, avg_position_previous,
                         top_queries_df):
    lines = []

    if total_clicks_current > total_clicks_previous:
        lines.append("Overall clicks are up week over week.")
    elif total_clicks_current < total_clicks_previous:
        lines.append("Overall clicks are down week over week.")
    else:
        lines.append("Overall clicks are flat week over week.")

    impressions_pct = safe_pct_change(total_impressions_current, total_impressions_previous)
    if impressions_pct is None:
        lines.append("Impressions do not yet have a prior-period baseline.")
    elif abs(impressions_pct) < 3:
        lines.append("Impressions are essentially flat.")
    elif total_impressions_current > total_impressions_previous:
        lines.append("Impressions increased week over week.")
    else:
        lines.append("Impressions declined week over week.")

    if weighted_ctr_current > weighted_ctr_previous:
        lines.append("CTR improved, indicating better search-result efficiency.")
    elif weighted_ctr_current < weighted_ctr_previous:
        lines.append("CTR declined versus the prior period.")
    else:
        lines.append("CTR was flat versus the prior period.")

    if avg_position_current < avg_position_previous:
        lines.append("Average position improved.")
    elif avg_position_current > avg_position_previous:
        lines.append("Average position weakened.")
    else:
        lines.append("Average position was unchanged.")

    branded_mask = top_queries_df["query"].astype(str).str.contains(
        r"cim connect|vancouver 2026|cim 2026|cim vancouver",
        case=False,
        na=False,
    )
    branded_clicks = top_queries_df.loc[branded_mask, "clicks_current"].sum()
    total_top_clicks = top_queries_df["clicks_current"].sum()

    if total_top_clicks > 0 and (branded_clicks / total_top_clicks) >= 0.4:
        lines.append("Performance concentration remains heavily weighted toward CIM Connect / Vancouver 2026 branded demand.")

    return lines


def build_ai_analysis(query_df, page_df, current_start, current_end, previous_start, previous_end):
    if not GROQ_API_KEY:
        return "AI executive analysis was skipped because GROQ_API_KEY is not configured."

    top_queries = query_df.sort_values(by="clicks_current", ascending=False).head(10)[[
        "query", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"
    ]]
    top_pages = page_df.sort_values(by="clicks_current", ascending=False).head(10)[[
        "page", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"
    ]]

    total_clicks_current = query_df["clicks_current"].sum()
    total_clicks_previous = query_df["clicks_previous"].sum()
    total_impressions_current = query_df["impressions_current"].sum()
    total_impressions_previous = query_df["impressions_previous"].sum()
    ctr_current = total_clicks_current / total_impressions_current if total_impressions_current else 0
    ctr_previous = total_clicks_previous / total_impressions_previous if total_impressions_previous else 0
    avg_position_current = query_df.loc[query_df["impressions_current"] > 0, "position_current"].mean() if not query_df.loc[query_df["impressions_current"] > 0].empty else 0
    avg_position_previous = query_df.loc[query_df["impressions_previous"] > 0, "position_previous"].mean() if not query_df.loc[query_df["impressions_previous"] > 0].empty else 0

    prompt = f"""
You are writing a concise executive SEO analysis for a corporate stakeholder report.

Write under these headings:
Executive Summary
Key Wins
Risks / Watchouts
Recommended Actions for Next Week

Requirements:
- professional corporate tone
- no hype
- use short paragraphs and bullets
- keep it under 275 words
- do not invent data
- emphasize interpretation and priorities, not just metric repetition

Current period: {current_start} to {current_end}
Previous period: {previous_start} to {previous_end}

Overall metrics:
- Clicks: {total_clicks_current:.0f} vs {total_clicks_previous:.0f}
- Impressions: {total_impressions_current:.0f} vs {total_impressions_previous:.0f}
- CTR: {ctr_current:.2%} vs {ctr_previous:.2%}
- Avg position: {avg_position_current:.2f} vs {avg_position_previous:.2f}

Top queries:
{top_queries.to_csv(index=False)}

Top pages:
{top_pages.to_csv(index=False)}
"""

    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write polished weekly executive SEO briefs."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content.strip()
        return content if content else "AI executive analysis returned an empty response."
    except Exception as e:
        return f"AI executive analysis failed, so the report fell back to deterministic output only. Error: {str(e)}"


def html_table_from_df(df, columns, rename_map=None):
    work = df[columns].copy()
    if rename_map:
        work = work.rename(columns=rename_map)

    for col in work.columns:
        lower_col = col.lower()
        if "ctr" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.2%}" if pd.notnull(x) else "")
        elif "position" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.2f}" if pd.notnull(x) else "")
        elif "change" in lower_col or col.strip() == "Δ" or "delta" in lower_col:
            decimals = 2 if "position" in lower_col or "ctr" in lower_col else 0
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x, decimals) if pd.notnull(x) else "")
        elif any(token in lower_col for token in ["click", "impression", "prev", "current"]):
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.0f}" if pd.notnull(x) else "")
        else:
            work[col] = work[col].fillna("").astype(str)

    header_html = "".join(f"<th>{html.escape(str(col))}</th>" for col in work.columns)
    body_rows = []
    for row in work.values.tolist():
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in row)
        body_rows.append(f"<tr>{cells}</tr>")

    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def plot_metric_comparison(total_clicks_current, total_clicks_previous,
                           total_impressions_current, total_impressions_previous,
                           weighted_ctr_current, weighted_ctr_previous,
                           avg_position_current, avg_position_previous):
    CHARTS_DIR.mkdir(exist_ok=True)
    path = CHARTS_DIR / "kpi_comparison.png"

    labels = ["Clicks", "Impressions", "CTR %", "Avg Position"]
    current = [total_clicks_current, total_impressions_current, weighted_ctr_current * 100, avg_position_current]
    previous = [total_clicks_previous, total_impressions_previous, weighted_ctr_previous * 100, avg_position_previous]

    fig, ax = plt.subplots(figsize=(10, 5.2))
    x = range(len(labels))
    width = 0.35
    ax.bar([i - width / 2 for i in x], previous, width=width, label="Previous", color=ACCENT_4)
    ax.bar([i + width / 2 for i in x], current, width=width, label="Current", color=ACCENT)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_title("Current Week vs Previous Week")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_top_items(df, label_col, value_col, title, output_name, color=ACCENT, max_label=42):
    CHARTS_DIR.mkdir(exist_ok=True)
    path = CHARTS_DIR / output_name
    plot_df = df[[label_col, value_col]].copy().head(10)
    if plot_df.empty:
        return None

    labels = [short_url(v, max_label) for v in plot_df[label_col].astype(str).tolist()][::-1]
    values = plot_df[value_col].astype(float).tolist()[::-1]

    fig_height = max(4.8, len(labels) * 0.55)
    fig, ax = plt.subplots(figsize=(10, fig_height))
    ax.barh(labels, values, color=color)
    ax.set_title(title)
    ax.grid(axis="x", linestyle="--", alpha=0.35)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_winners_losers(gainers_df, losers_df, label_col, change_col, title, output_name):
    CHARTS_DIR.mkdir(exist_ok=True)
    path = CHARTS_DIR / output_name

    gainers = gainers_df[[label_col, change_col]].head(5).copy()
    losers = losers_df[[label_col, change_col]].head(5).copy()

    merged = pd.concat([losers, gainers], ignore_index=True)
    if merged.empty:
        return None

    labels = [short_url(v, 42) for v in merged[label_col].astype(str).tolist()]
    values = merged[change_col].astype(float).tolist()
    colors = [ACCENT_3 if v < 0 else ACCENT_2 for v in values]

    fig_height = max(4.5, len(labels) * 0.52)
    fig, ax = plt.subplots(figsize=(10, fig_height))
    ax.barh(labels, values, color=colors)
    ax.axvline(0, color="#374151", linewidth=1)
    ax.set_title(title)
    ax.grid(axis="x", linestyle="--", alpha=0.30)
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def build_chart_paths(query_df, page_df,
                      total_clicks_current, total_clicks_previous,
                      total_impressions_current, total_impressions_previous,
                      weighted_ctr_current, weighted_ctr_previous,
                      avg_position_current, avg_position_previous):
    top_queries = query_df.sort_values(by="clicks_current", ascending=False).head(10)
    gainers = query_df.sort_values(by="clicks_change", ascending=False).head(10)
    losers = query_df.sort_values(by="clicks_change", ascending=True).head(10)
    top_pages = page_df.sort_values(by="clicks_current", ascending=False).head(10)
    page_gainers = page_df.sort_values(by="clicks_change", ascending=False).head(10)
    page_losers = page_df.sort_values(by="clicks_change", ascending=True).head(10)

    return {
        "kpi": plot_metric_comparison(
            total_clicks_current, total_clicks_previous,
            total_impressions_current, total_impressions_previous,
            weighted_ctr_current, weighted_ctr_previous,
            avg_position_current, avg_position_previous,
        ),
        "top_queries": plot_top_items(top_queries, "query", "clicks_current", "Top Queries by Clicks", "top_queries.png", ACCENT),
        "top_pages": plot_top_items(top_pages, "page", "clicks_current", "Top Pages by Clicks", "top_pages.png", ACCENT_2, 52),
        "query_moves": plot_winners_losers(gainers, losers, "query", "clicks_change", "Query Winners and Losers", "query_moves.png"),
        "page_moves": plot_winners_losers(page_gainers, page_losers, "page", "clicks_change", "Page Winners and Losers", "page_moves.png"),
    }


def image_block(path, alt):
    if not path:
        return ""
    return f'<div class="chart-card"><img src="{html.escape(str(path))}" alt="{html.escape(alt)}"></div>'


def write_markdown_summary(query_df, page_df, ai_analysis, current_start, current_end, previous_start, previous_end):
    total_clicks_current = query_df["clicks_current"].sum()
    total_clicks_previous = query_df["clicks_previous"].sum()
    total_impressions_current = query_df["impressions_current"].sum()
    total_impressions_previous = query_df["impressions_previous"].sum()
    weighted_ctr_current = total_clicks_current / total_impressions_current if total_impressions_current else 0
    weighted_ctr_previous = total_clicks_previous / total_impressions_previous if total_impressions_previous else 0
    avg_position_current = query_df.loc[query_df["impressions_current"] > 0, "position_current"].mean() if not query_df.loc[query_df["impressions_current"] > 0].empty else 0
    avg_position_previous = query_df.loc[query_df["impressions_previous"] > 0, "position_previous"].mean() if not query_df.loc[query_df["impressions_previous"] > 0].empty else 0

    top_queries = query_df.sort_values(by="clicks_current", ascending=False).head(10)
    top_pages = page_df.sort_values(by="clicks_current", ascending=False).head(10)

    executive_read = build_executive_read(
        total_clicks_current, total_clicks_previous,
        total_impressions_current, total_impressions_previous,
        weighted_ctr_current, weighted_ctr_previous,
        avg_position_current, avg_position_previous,
        top_queries,
    )

    lines = [
        "# Weekly GSC Summary",
        "",
        f"Current period: {current_start} to {current_end}",
        f"Previous period: {previous_start} to {previous_end}",
        "",
        "## Executive Read",
    ]
    lines.extend([f"- {line}" for line in executive_read])
    lines.extend([
        "",
        "## AI Executive Analysis",
        "",
        ai_analysis,
        "",
        "## KPI Snapshot",
        f"- Clicks: {total_clicks_current:.0f} vs {total_clicks_previous:.0f} ({format_pct_change(total_clicks_current, total_clicks_previous)})",
        f"- Impressions: {total_impressions_current:.0f} vs {total_impressions_previous:.0f} ({format_pct_change(total_impressions_current, total_impressions_previous)})",
        f"- CTR: {weighted_ctr_current:.2%} vs {weighted_ctr_previous:.2%}",
        f"- Avg position: {avg_position_current:.2f} vs {avg_position_previous:.2f}",
        "",
        "## Top Queries",
        top_queries[["query", "clicks_current", "impressions_current", "ctr_current", "position_current"]].to_markdown(index=False),
        "",
        "## Top Pages",
        top_pages[["page", "clicks_current", "impressions_current", "ctr_current", "position_current"]].to_markdown(index=False),
    ])

    with open("weekly_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_html_summary(query_df, page_df, ai_analysis, current_start, current_end, previous_start, previous_end):
    total_clicks_current = query_df["clicks_current"].sum()
    total_clicks_previous = query_df["clicks_previous"].sum()
    total_impressions_current = query_df["impressions_current"].sum()
    total_impressions_previous = query_df["impressions_previous"].sum()
    weighted_ctr_current = total_clicks_current / total_impressions_current if total_impressions_current else 0
    weighted_ctr_previous = total_clicks_previous / total_impressions_previous if total_impressions_previous else 0
    avg_position_current = query_df.loc[query_df["impressions_current"] > 0, "position_current"].mean() if not query_df.loc[query_df["impressions_current"] > 0].empty else 0
    avg_position_previous = query_df.loc[query_df["impressions_previous"] > 0, "position_previous"].mean() if not query_df.loc[query_df["impressions_previous"] > 0].empty else 0

    top_queries = query_df.sort_values(by="clicks_current", ascending=False).head(10)
    gainers = query_df.sort_values(by="clicks_change", ascending=False).head(10)
    losers = query_df.sort_values(by="clicks_change", ascending=True).head(10)
    top_pages = page_df.sort_values(by="clicks_current", ascending=False).head(10)
    page_gainers = page_df.sort_values(by="clicks_change", ascending=False).head(10)
    page_losers = page_df.sort_values(by="clicks_change", ascending=True).head(10)

    executive_read = build_executive_read(
        total_clicks_current, total_clicks_previous,
        total_impressions_current, total_impressions_previous,
        weighted_ctr_current, weighted_ctr_previous,
        avg_position_current, avg_position_previous,
        top_queries,
    )

    chart_paths = build_chart_paths(
        query_df, page_df,
        total_clicks_current, total_clicks_previous,
        total_impressions_current, total_impressions_previous,
        weighted_ctr_current, weighted_ctr_previous,
        avg_position_current, avg_position_previous,
    )

    def card(title, current, previous, delta_text, footer=""):
        return f"""
        <div class=\"card\">
            <div class=\"label\">{html.escape(title)}</div>
            <div class=\"value\">{html.escape(current)}</div>
            <div class=\"sub\">Previous: {html.escape(previous)}</div>
            <div class=\"delta\">{html.escape(delta_text)}</div>
            <div class=\"foot\">{html.escape(footer)}</div>
        </div>
        """

    highlights = "".join(f"<li>{html.escape(line)}</li>" for line in executive_read)

    html_output = f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<title>Weekly GSC Summary</title>
<style>
    @page {{
        size: A4;
        margin: 20mm 14mm 18mm 14mm;
        @bottom-right {{
            content: "Page " counter(page);
            color: #6B7280;
            font-size: 10px;
        }}
    }}
    body {{
        font-family: Arial, sans-serif;
        margin: 0;
        background: {BG};
        color: {TEXT};
    }}
    .container {{
        width: 100%;
        max-width: 1120px;
        margin: 0 auto;
    }}
    .hero {{
        background: linear-gradient(135deg, {ACCENT} 0%, #163A5F 100%);
        color: white;
        padding: 28px 30px;
        border-radius: 18px;
        margin-bottom: 20px;
    }}
    .hero h1 {{
        margin: 0 0 8px 0;
        font-size: 30px;
    }}
    .hero .subline {{
        font-size: 14px;
        opacity: 0.95;
    }}
    .hero .meta {{
        margin-top: 12px;
        font-size: 12px;
        opacity: 0.9;
    }}
    .section-title {{
        margin: 24px 0 10px 0;
        font-size: 20px;
        color: #0F172A;
    }}
    .section-note {{
        color: #667085;
        margin-bottom: 14px;
        font-size: 13px;
    }}
    .grid-4 {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 14px;
        margin-bottom: 18px;
    }}
    .grid-2 {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 18px;
        margin-bottom: 18px;
    }}
    .card, .panel, .chart-card {{
        background: white;
        border-radius: 14px;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08);
        padding: 16px 18px;
    }}
    .label {{
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #64748B;
        margin-bottom: 8px;
    }}
    .value {{
        font-size: 28px;
        font-weight: 700;
        color: #0F172A;
    }}
    .sub {{
        font-size: 12px;
        color: #64748B;
        margin-top: 6px;
    }}
    .delta {{
        margin-top: 10px;
        font-size: 16px;
        font-weight: 700;
        color: {ACCENT};
    }}
    .foot {{
        margin-top: 6px;
        font-size: 11px;
        color: #94A3B8;
    }}
    .panel h2, .chart-card h2 {{
        margin: 0 0 10px 0;
        font-size: 18px;
    }}
    .highlight-list {{
        margin: 0;
        padding-left: 18px;
        line-height: 1.55;
    }}
    .ai-block {{
        white-space: pre-wrap;
        line-height: 1.55;
        font-size: 14px;
    }}
    .chart-card img {{
        width: 100%;
        height: auto;
        display: block;
    }}
    .callout {{
        border-left: 4px solid {ACCENT_2};
        background: #F8FAFC;
        padding: 14px 16px;
        border-radius: 10px;
        margin-top: 12px;
        font-size: 13px;
        color: #475569;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        background: white;
        border-radius: 14px;
        overflow: hidden;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08);
        margin-bottom: 18px;
        font-size: 12px;
    }}
    th, td {{
        text-align: left;
        padding: 10px 12px;
        border-bottom: 1px solid #E5E7EB;
        vertical-align: top;
        word-break: break-word;
    }}
    th {{
        background: #0F172A;
        color: white;
        font-size: 12px;
    }}
    tr:nth-child(even) td {{
        background: #FAFAFA;
    }}
    .break-before {{
        page-break-before: always;
    }}
</style>
</head>
<body>
<div class=\"container\">
    <div class=\"hero\">
        <h1>Google Search Console Weekly Executive Report</h1>
        <div class=\"subline\">Corporate SEO performance summary for {html.escape(SITE_URL)}</div>
        <div class=\"meta\">Current period: {current_start} to {current_end} | Previous period: {previous_start} to {previous_end}</div>
    </div>

    <div class=\"grid-4\">
        {card("Clicks", f"{total_clicks_current:.0f}", f"{total_clicks_previous:.0f}", format_pct_change(total_clicks_current, total_clicks_previous), "Week over week")}
        {card("Impressions", f"{total_impressions_current:.0f}", f"{total_impressions_previous:.0f}", format_pct_change(total_impressions_current, total_impressions_previous), "Week over week")}
        {card("CTR", f"{weighted_ctr_current:.2%}", f"{weighted_ctr_previous:.2%}", format_delta((weighted_ctr_current - weighted_ctr_previous) * 100, 2) + " pts", "Search-result efficiency")}
        {card("Avg Position", f"{avg_position_current:.2f}", f"{avg_position_previous:.2f}", format_delta(avg_position_previous - avg_position_current, 2), "Positive means improved")}
    </div>

    <div class=\"grid-2\">
        <div class=\"panel\">
            <h2>Executive Read</h2>
            <ul class=\"highlight-list\">{highlights}</ul>
            <div class=\"callout\">This report combines deterministic Search Console metrics with AI-assisted interpretation. Charts and KPI cards are source-of-truth visuals; the narrative is intended to accelerate executive review.</div>
        </div>
        <div class=\"panel\">
            <h2>AI Executive Analysis</h2>
            <div class=\"ai-block\">{html.escape(ai_analysis)}</div>
        </div>
    </div>

    <div class=\"section-title\">Performance Overview</div>
    <div class=\"section-note\">Current week versus prior week across the primary executive KPIs.</div>
    {image_block(chart_paths['kpi'], 'KPI comparison chart')}

    <div class=\"section-title\">Top Demand Drivers</div>
    <div class=\"grid-2\">
        {image_block(chart_paths['top_queries'], 'Top queries by clicks')}
        {image_block(chart_paths['top_pages'], 'Top pages by clicks')}
    </div>

    <div class=\"section-title\">Winners and Losers</div>
    <div class=\"grid-2\">
        {image_block(chart_paths['query_moves'], 'Query winners and losers')}
        {image_block(chart_paths['page_moves'], 'Page winners and losers')}
    </div>

    <div class=\"break-before\"></div>

    <div class=\"section-title\">Top Queries</div>
    <div class=\"section-note\">Highest-click query terms during the current week.</div>
    {html_table_from_df(top_queries,
        ["query", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"],
        {{
            "query": "Query",
            "clicks_current": "Clicks",
            "clicks_change": "WoW Clicks Δ",
            "impressions_current": "Impressions",
            "ctr_current": "CTR",
            "position_current": "Position",
        }}
    )}

    <div class=\"section-title\">Query Gainers</div>
    {html_table_from_df(gainers,
        ["query", "clicks_previous", "clicks_current", "clicks_change"],
        {{
            "query": "Query",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }}
    )}

    <div class=\"section-title\">Query Losers</div>
    {html_table_from_df(losers,
        ["query", "clicks_previous", "clicks_current", "clicks_change"],
        {{
            "query": "Query",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }}
    )}

    <div class=\"section-title\">Top Pages</div>
    <div class=\"section-note\">Highest-click landing pages during the current week.</div>
    {html_table_from_df(top_pages,
        ["page", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"],
        {{
            "page": "Page",
            "clicks_current": "Clicks",
            "clicks_change": "WoW Clicks Δ",
            "impressions_current": "Impressions",
            "ctr_current": "CTR",
            "position_current": "Position",
        }}
    )}

    <div class=\"section-title\">Page Gainers</div>
    {html_table_from_df(page_gainers,
        ["page", "clicks_previous", "clicks_current", "clicks_change"],
        {{
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }}
    )}

    <div class=\"section-title\">Page Losers</div>
    {html_table_from_df(page_losers,
        ["page", "clicks_previous", "clicks_current", "clicks_change"],
        {{
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }}
    )}
</div>
</body>
</html>
"""
    with open("weekly_summary.html", "w", encoding="utf-8") as f:
        f.write(html_output)


def generate_pdf():
    HTML("weekly_summary.html", base_url=os.getcwd()).write_pdf("weekly_summary.pdf")
    print("Saved weekly_summary.pdf")


def upload_pdf_to_monday(pdf_path):
    if not MONDAY_API_TOKEN or not MONDAY_ITEM_ID:
        print("Skipping monday file upload: MONDAY_API_TOKEN or MONDAY_ITEM_ID not configured.")
        return

    update_query = """
    mutation ($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) {
        id
      }
    }
    """
    update_variables = {
        "item_id": str(MONDAY_ITEM_ID),
        "body": "GSC weekly PDF report attached.",
    }

    update_response = requests.post(
        MONDAY_API_URL,
        headers={"Authorization": MONDAY_API_TOKEN, "Content-Type": "application/json"},
        json={"query": update_query, "variables": update_variables},
        timeout=60,
    )
    update_response.raise_for_status()
    update_data = update_response.json()

    if "errors" in update_data:
        raise RuntimeError(f"monday update creation failed: {update_data['errors']}")

    update_id = update_data["data"]["create_update"]["id"]

    file_query = """
    mutation ($update_id: ID!, $file: File!) {
      add_file_to_update(update_id: $update_id, file: $file) {
        id
      }
    }
    """

    with open(pdf_path, "rb") as f:
        response = requests.post(
            MONDAY_FILE_API_URL,
            headers={"Authorization": MONDAY_API_TOKEN},
            data={
                "query": file_query,
                "variables": json.dumps({"update_id": str(update_id), "file": None}),
                "map": json.dumps({"pdf": ["variables.file"]}),
            },
            files={"pdf": ("google-search-console-audit.pdf", f, "application/pdf")},
            timeout=120,
        )

    print("monday file upload status:", response.status_code)
    print("monday file upload response:", response.text)
    response.raise_for_status()
    response_data = response.json()
    if "errors" in response_data:
        raise RuntimeError(f"monday file upload failed: {response_data['errors']}")
    print("Uploaded PDF to monday update.")


def main():
    service = get_service()

    current_end = date.today() - timedelta(days=1)
    current_start = current_end - timedelta(days=6)

    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)

    current_query_df = fetch_dimension_data(service, current_start, current_end, "query", row_limit=250)
    previous_query_df = fetch_dimension_data(service, previous_start, previous_end, "query", row_limit=250)

    current_page_df = fetch_dimension_data(service, current_start, current_end, "page", row_limit=250)
    previous_page_df = fetch_dimension_data(service, previous_start, previous_end, "page", row_limit=250)

    query_comparison_df = prepare_comparison(current_query_df, previous_query_df, "query")
    page_comparison_df = prepare_comparison(current_page_df, previous_page_df, "page")

    current_query_df.to_csv("weekly_gsc_report.csv", index=False)
    query_comparison_df.to_csv("weekly_comparison.csv", index=False)
    current_page_df.to_csv("weekly_pages_report.csv", index=False)
    page_comparison_df.to_csv("weekly_pages_comparison.csv", index=False)

    top_queries = query_comparison_df.sort_values(by="clicks_current", ascending=False).head(25)
    gainers = query_comparison_df.sort_values(by="clicks_change", ascending=False).head(25)
    losers = query_comparison_df.sort_values(by="clicks_change", ascending=True).head(25)

    top_pages = page_comparison_df.sort_values(by="clicks_current", ascending=False).head(25)
    page_gainers = page_comparison_df.sort_values(by="clicks_change", ascending=False).head(25)
    page_losers = page_comparison_df.sort_values(by="clicks_change", ascending=True).head(25)

    top_queries.to_csv("top_queries.csv", index=False)
    gainers.to_csv("biggest_gainers.csv", index=False)
    losers.to_csv("biggest_losers.csv", index=False)
    top_pages.to_csv("top_pages.csv", index=False)
    page_gainers.to_csv("page_gainers.csv", index=False)
    page_losers.to_csv("page_losers.csv", index=False)

    ai_analysis = build_ai_analysis(
        query_comparison_df,
        page_comparison_df,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )

    write_markdown_summary(
        query_comparison_df,
        page_comparison_df,
        ai_analysis,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )

    write_html_summary(
        query_comparison_df,
        page_comparison_df,
        ai_analysis,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )

    generate_pdf()

    try:
        upload_pdf_to_monday("weekly_summary.pdf")
    except Exception as e:
        print(f"monday upload step failed: {e}")

    print("Saved weekly_summary.md, weekly_summary.html, weekly_summary.pdf")
    print("Saved query and page comparison outputs")


if __name__ == "__main__":
    main()
