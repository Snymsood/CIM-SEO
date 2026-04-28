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

from google_sheets_db import append_to_sheet
from pdf_report_formatter import get_pdf_css, html_table_from_df, build_card, format_pct_change
from monday_utils import upload_pdf_to_monday as _upload_pdf
from seo_utils import get_weekly_date_windows, short_url, safe_pct_change
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



def calculate_kpis(df):
    """Calculate aggregate KPI metrics from a GSC comparison dataframe."""
    clicks_curr = df["clicks_current"].sum()
    clicks_prev = df["clicks_previous"].sum()
    impr_curr = df["impressions_current"].sum()
    impr_prev = df["impressions_previous"].sum()
    
    ctr_curr = clicks_curr / impr_curr if impr_curr else 0
    ctr_prev = clicks_prev / impr_prev if impr_prev else 0
    
    # Position mean for only those queries that had impressions in that period
    pos_curr = df.loc[df["impressions_current"] > 0, "position_current"].mean() if not df.loc[df["impressions_current"] > 0].empty else 0
    pos_prev = df.loc[df["impressions_previous"] > 0, "position_previous"].mean() if not df.loc[df["impressions_previous"] > 0].empty else 0
    
    return {
        "clicks_current": clicks_curr,
        "clicks_previous": clicks_prev,
        "impressions_current": impr_curr,
        "impressions_previous": impr_prev,
        "ctr_current": ctr_curr,
        "ctr_previous": ctr_prev,
        "position_current": pos_curr,
        "position_previous": pos_prev
    }





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
        return "Executive commentary is unavailable for this run."

    top_queries = query_df.sort_values(by="clicks_current", ascending=False).head(10)[[
        "query", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"
    ]]
    top_pages = page_df.sort_values(by="clicks_current", ascending=False).head(10)[[
        "page", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"
    ]]

    kpis = calculate_kpis(query_df)
    
    total_clicks_current = kpis["clicks_current"]
    total_clicks_previous = kpis["clicks_previous"]
    total_impressions_current = kpis["impressions_current"]
    total_impressions_previous = kpis["impressions_previous"]
    ctr_current = kpis["ctr_current"]
    ctr_previous = kpis["ctr_previous"]
    avg_position_current = kpis["position_current"]
    avg_position_previous = kpis["position_previous"]

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
        return content if content else "Executive commentary was empty for this run."
    except Exception as e:
        return "Executive commentary is temporarily unavailable for this run."



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
    kpis = calculate_kpis(query_df)
    
    total_clicks_current = kpis["clicks_current"]
    total_clicks_previous = kpis["clicks_previous"]
    total_impressions_current = kpis["impressions_current"]
    total_impressions_previous = kpis["impressions_previous"]
    weighted_ctr_current = kpis["ctr_current"]
    weighted_ctr_previous = kpis["ctr_previous"]
    avg_position_current = kpis["position_current"]
    avg_position_previous = kpis["position_previous"]

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
        "## Executive Commentary",
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
    kpis = calculate_kpis(query_df)
    
    total_clicks_current = kpis["clicks_current"]
    total_clicks_previous = kpis["clicks_previous"]
    total_impressions_current = kpis["impressions_current"]
    total_impressions_previous = kpis["impressions_previous"]
    weighted_ctr_current = kpis["ctr_current"]
    weighted_ctr_previous = kpis["ctr_previous"]
    avg_position_current = kpis["position_current"]
    avg_position_previous = kpis["position_previous"]

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

    highlights = "".join(f"<li>{html.escape(line)}</li>" for line in executive_read)

    html_output = f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<title>Weekly GSC Summary</title>
<style>
{get_pdf_css()}
</style>
</head>
<body>
    <div class="header-bar">
        <h1>GSC Weekly Performance Summary</h1>
        <div class="subtitle">Current window: {current_start} to {current_end} | Comparison: {previous_start} to {previous_end}</div>
    </div>

    <div class=\"panel\">
        <h2>Executive Read</h2>
        <ul>{highlights}</ul>
    </div>

    <div class=\"panel\">
        <h2>Executive Commentary</h2>
        <div class=\"ai-block\">{html.escape(ai_analysis)}</div>
    </div>

    <div class=\"grid\">
        {build_card("Clicks", total_clicks_current, total_clicks_previous)}
        {build_card("Impressions", total_impressions_current, total_impressions_previous)}
        {build_card("CTR", weighted_ctr_current, weighted_ctr_previous, is_pct=True)}
        {build_card("Avg Position", avg_position_current, avg_position_previous, decimals=2)}
    </div>

    <h2>Performance Overview</h2>
    {image_block(chart_paths['kpi'], 'KPI comparison chart')}

    <div class="break-before"></div>
    <h2>Top Demand Drivers</h2>
    {image_block(chart_paths['top_queries'], 'Top queries by clicks')}
    {image_block(chart_paths['top_pages'], 'Top pages by clicks')}

    <div class="break-before"></div>
    <h2>Winners and Losers</h2>
    {image_block(chart_paths['query_moves'], 'Query winners and losers')}
    {image_block(chart_paths['page_moves'], 'Page winners and losers')}

    <div class="break-before"></div>

    <h2>Top Queries</h2>
    {html_table_from_df(top_queries,
        ["query", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"],
        {
            "query": "Query",
            "clicks_current": "Clicks",
            "clicks_change": "Clicks Δ",
            "impressions_current": "Impr",
            "ctr_current": "CTR",
            "position_current": "Pos",
        }
    )}

    <h2>Query Gainers</h2>
    {html_table_from_df(gainers,
        ["query", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "query": "Query",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Curr Clicks",
            "clicks_change": "Δ",
        }
    )}

    <h2>Query Losers</h2>
    {html_table_from_df(losers,
        ["query", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "query": "Query",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Curr Clicks",
            "clicks_change": "Δ",
        }
    )}

    <div class="break-before"></div>

    <h2>Top Pages</h2>
    {html_table_from_df(top_pages,
        ["page", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"],
        {
            "page": "Page",
            "clicks_current": "Clicks",
            "clicks_change": "Clicks Δ",
            "impressions_current": "Impr",
            "ctr_current": "CTR",
            "position_current": "Pos",
        }
    )}

    <h2>Page Gainers</h2>
    {html_table_from_df(page_gainers,
        ["page", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Curr Clicks",
            "clicks_change": "Δ",
        }
    )}

    <h2>Page Losers</h2>
    {html_table_from_df(page_losers,
        ["page", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Curr Clicks",
            "clicks_change": "Δ",
        }
    )}
</body>
</html>
"""
    with open("weekly_summary.html", "w", encoding="utf-8") as f:
        f.write(html_output)


def generate_pdf():
    HTML("weekly_summary.html", base_url=os.getcwd()).write_pdf("weekly_summary.pdf")
    print("Saved weekly_summary.pdf")


def upload_pdf_to_monday(pdf_path):
    _upload_pdf(
        pdf_path,
        body_text="GSC weekly PDF report attached.",
        pdf_filename="google-search-console-audit.pdf",
    )


def main():
    service = get_service()

    current_start, current_end, previous_start, previous_end = get_weekly_date_windows()

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

    append_to_sheet(query_comparison_df, "GSC_Query_Comparison")
    append_to_sheet(page_comparison_df, "GSC_Page_Comparison")

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
