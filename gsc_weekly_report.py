from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
import pandas as pd
import os
import html

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
KEY_FILE = "gsc-key.json"
SITE_URL = os.environ["GSC_PROPERTY"]
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


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


def format_delta(value):
    if value > 0:
        return f"+{value:.0f}"
    return f"{value:.0f}"


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

    branded_mask = top_queries_df["query"].str.contains(
        r"cim connect|vancouver 2026|cim 2026|cim vancouver",
        case=False,
        na=False
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
You are writing a concise corporate SEO executive analysis for internal stakeholders.

Write:
1. Executive Summary
2. Key Wins
3. Risks / Watchouts
4. Recommended Actions for Next Week

Requirements:
- professional corporate tone
- no hype
- no markdown headings with # symbols
- use short paragraphs and bullets
- refer to actual performance trends only
- keep it under 350 words
- do not invent data
- focus on strategic interpretation, not restating every metric

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
        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write precise weekly SEO stakeholder summaries."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )

        content = response.choices[0].message.content.strip()
        return content if content else "AI executive analysis returned an empty response."

    except Exception as e:
        return f"AI executive analysis failed, so the report fell back to deterministic output only. Error: {str(e)}"


def md_table_from_df(df, columns, rename_map=None):
    work = df[columns].copy()
    if rename_map:
        work = work.rename(columns=rename_map)

    for col in work.columns:
        if "ctr" in col.lower():
            work[col] = work[col].map(lambda x: f"{x:.2%}" if pd.notnull(x) else "")
        elif "position" in col.lower():
            work[col] = work[col].map(lambda x: f"{x:.2f}" if pd.notnull(x) else "")
        elif "change" in col.lower():
            work[col] = work[col].map(lambda x: format_delta(x) if pd.notnull(x) else "")
        elif work[col].dtype != object:
            work[col] = work[col].map(lambda x: f"{x:.0f}" if pd.notnull(x) else "")

    header = "| " + " | ".join(work.columns) + " |"
    separator = "| " + " | ".join(["---"] * len(work.columns)) + " |"
    rows = [
        "| " + " | ".join(str(v) for v in row) + " |"
        for row in work.values.tolist()
    ]
    return "\n".join([header, separator] + rows)


def html_table_from_df(df, columns, rename_map=None):
    work = df[columns].copy()
    if rename_map:
        work = work.rename(columns=rename_map)

    for col in work.columns:
        if "ctr" in col.lower():
            work[col] = work[col].map(lambda x: f"{x:.2%}" if pd.notnull(x) else "")
        elif "position" in col.lower():
            work[col] = work[col].map(lambda x: f"{x:.2f}" if pd.notnull(x) else "")
        elif "change" in col.lower():
            work[col] = work[col].map(lambda x: format_delta(x) if pd.notnull(x) else "")
        elif work[col].dtype != object:
            work[col] = work[col].map(lambda x: f"{x:.0f}" if pd.notnull(x) else "")

    header_html = "".join(f"<th>{html.escape(str(col))}</th>" for col in work.columns)
    body_rows = []
    for row in work.values.tolist():
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in row)
        body_rows.append(f"<tr>{cells}</tr>")

    return f"""
    <table>
      <thead><tr>{header_html}</tr></thead>
      <tbody>
        {''.join(body_rows)}
      </tbody>
    </table>
    """


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
    gainers = query_df.sort_values(by="clicks_change", ascending=False).head(10)
    losers = query_df.sort_values(by="clicks_change", ascending=True).head(10)
    top_pages = page_df.sort_values(by="clicks_current", ascending=False).head(10)
    page_gainers = page_df.sort_values(by="clicks_change", ascending=False).head(10)
    page_losers = page_df.sort_values(by="clicks_change", ascending=True).head(10)

    executive_read = build_executive_read(
        total_clicks_current,
        total_clicks_previous,
        total_impressions_current,
        total_impressions_previous,
        weighted_ctr_current,
        weighted_ctr_previous,
        avg_position_current,
        avg_position_previous,
        top_queries,
    )

    lines = []
    lines.append("# Weekly GSC Summary")
    lines.append("")
    lines.append("## Executive Read")
    lines.append("")
    for line in executive_read:
        lines.append(f"- {line}")

    lines.append("")
    lines.append("## AI Executive Analysis")
    lines.append("")
    lines.append(ai_analysis)
    lines.append("")
    lines.append("## Reporting Window")
    lines.append("")
    lines.append(f"- Current period: {current_start} to {current_end}")
    lines.append(f"- Previous period: {previous_start} to {previous_end}")
    lines.append("")
    lines.append("## KPI Snapshot")
    lines.append("")
    lines.append(f"- Clicks: {total_clicks_current:.0f} vs {total_clicks_previous:.0f} ({format_pct_change(total_clicks_current, total_clicks_previous)})")
    lines.append(f"- Impressions: {total_impressions_current:.0f} vs {total_impressions_previous:.0f} ({format_pct_change(total_impressions_current, total_impressions_previous)})")
    lines.append(f"- CTR: {weighted_ctr_current:.2%} vs {weighted_ctr_previous:.2%}")
    lines.append(f"- Avg position: {avg_position_current:.2f} vs {avg_position_previous:.2f}")
    lines.append("")
    lines.append("## Top Queries")
    lines.append("")
    lines.append(md_table_from_df(
        top_queries,
        ["query", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"],
        {
            "query": "Query",
            "clicks_current": "Clicks",
            "clicks_change": "WoW Clicks Δ",
            "impressions_current": "Impressions",
            "ctr_current": "CTR",
            "position_current": "Position",
        }
    ))
    lines.append("")
    lines.append("## Query Gainers")
    lines.append("")
    lines.append(md_table_from_df(
        gainers,
        ["query", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "query": "Query",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }
    ))
    lines.append("")
    lines.append("## Query Losers")
    lines.append("")
    lines.append(md_table_from_df(
        losers,
        ["query", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "query": "Query",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }
    ))
    lines.append("")
    lines.append("## Top Pages")
    lines.append("")
    lines.append(md_table_from_df(
        top_pages,
        ["page", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"],
        {
            "page": "Page",
            "clicks_current": "Clicks",
            "clicks_change": "WoW Clicks Δ",
            "impressions_current": "Impressions",
            "ctr_current": "CTR",
            "position_current": "Position",
        }
    ))
    lines.append("")
    lines.append("## Page Gainers")
    lines.append("")
    lines.append(md_table_from_df(
        page_gainers,
        ["page", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }
    ))
    lines.append("")
    lines.append("## Page Losers")
    lines.append("")
    lines.append(md_table_from_df(
        page_losers,
        ["page", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }
    ))

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
        total_clicks_current,
        total_clicks_previous,
        total_impressions_current,
        total_impressions_previous,
        weighted_ctr_current,
        weighted_ctr_previous,
        avg_position_current,
        avg_position_previous,
        top_queries,
    )

    def card(title, current, previous, delta_text):
        return f"""
        <div class="card">
            <div class="label">{html.escape(title)}</div>
            <div class="value">{html.escape(current)}</div>
            <div class="sub">Previous: {html.escape(previous)} | {html.escape(delta_text)}</div>
        </div>
        """

    html_output = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Weekly GSC Summary</title>
<style>
    body {{
        font-family: Arial, sans-serif;
        margin: 0;
        padding: 32px;
        background: #f5f7fb;
        color: #1f2937;
    }}
    .container {{
        max-width: 1200px;
        margin: 0 auto;
    }}
    h1 {{
        margin-bottom: 8px;
    }}
    h2 {{
        margin-top: 32px;
        border-bottom: 2px solid #e5e7eb;
        padding-bottom: 8px;
    }}
    .muted {{
        color: #6b7280;
        margin-bottom: 20px;
    }}
    .grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 16px;
        margin: 20px 0 28px 0;
    }}
    .card {{
        background: white;
        border-radius: 12px;
        padding: 18px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .label {{
        font-size: 12px;
        text-transform: uppercase;
        color: #6b7280;
        margin-bottom: 10px;
    }}
    .value {{
        font-size: 28px;
        font-weight: 700;
        margin-bottom: 6px;
    }}
    .sub {{
        font-size: 13px;
        color: #6b7280;
    }}
    .panel {{
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        margin-bottom: 20px;
    }}
    ul {{
        margin-top: 0;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        background: white;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        margin-bottom: 24px;
    }}
    th, td {{
        text-align: left;
        padding: 12px 14px;
        border-bottom: 1px solid #e5e7eb;
        vertical-align: top;
    }}
    th {{
        background: #111827;
        color: white;
        font-size: 13px;
    }}
    tr:nth-child(even) td {{
        background: #f9fafb;
    }}
    .section-note {{
        margin: 8px 0 14px 0;
        color: #6b7280;
        font-size: 14px;
    }}
    .ai-block {{
        white-space: pre-wrap;
        line-height: 1.5;
    }}
</style>
</head>
<body>
<div class="container">
    <h1>Weekly GSC Summary</h1>
    <div class="muted">Current period: {current_start} to {current_end} | Previous period: {previous_start} to {previous_end}</div>

    <div class="panel">
        <h2>Executive Read</h2>
        <ul>
            {''.join(f"<li>{html.escape(line)}</li>" for line in executive_read)}
        </ul>
    </div>

    <div class="panel">
        <h2>AI Executive Analysis</h2>
        <div class="ai-block">{html.escape(ai_analysis)}</div>
    </div>

    <h2>KPI Snapshot</h2>
    <div class="grid">
        {card("Clicks", f"{total_clicks_current:.0f}", f"{total_clicks_previous:.0f}", format_pct_change(total_clicks_current, total_clicks_previous))}
        {card("Impressions", f"{total_impressions_current:.0f}", f"{total_impressions_previous:.0f}", format_pct_change(total_impressions_current, total_impressions_previous))}
        {card("CTR", f"{weighted_ctr_current:.2%}", f"{weighted_ctr_previous:.2%}", "efficiency")}
        {card("Avg Position", f"{avg_position_current:.2f}", f"{avg_position_previous:.2f}", "lower is better")}
    </div>

    <h2>Top Queries</h2>
    <div class="section-note">Highest-click query terms in the current week.</div>
    {html_table_from_df(top_queries,
        ["query", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"],
        {
            "query": "Query",
            "clicks_current": "Clicks",
            "clicks_change": "WoW Clicks Δ",
            "impressions_current": "Impressions",
            "ctr_current": "CTR",
            "position_current": "Position",
        }
    )}

    <h2>Query Gainers</h2>
    {html_table_from_df(gainers,
        ["query", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "query": "Query",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }
    )}

    <h2>Query Losers</h2>
    {html_table_from_df(losers,
        ["query", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "query": "Query",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }
    )}

    <h2>Top Pages</h2>
    <div class="section-note">Highest-click landing pages in the current week.</div>
    {html_table_from_df(top_pages,
        ["page", "clicks_current", "clicks_change", "impressions_current", "ctr_current", "position_current"],
        {
            "page": "Page",
            "clicks_current": "Clicks",
            "clicks_change": "WoW Clicks Δ",
            "impressions_current": "Impressions",
            "ctr_current": "CTR",
            "position_current": "Position",
        }
    )}

    <h2>Page Gainers</h2>
    {html_table_from_df(page_gainers,
        ["page", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }
    )}

    <h2>Page Losers</h2>
    {html_table_from_df(page_losers,
        ["page", "clicks_previous", "clicks_current", "clicks_change"],
        {
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
        }
    )}
</div>
</body>
</html>
"""
    with open("weekly_summary.html", "w", encoding="utf-8") as f:
        f.write(html_output)


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
        previous_end
    )

    write_html_summary(
        query_comparison_df,
        page_comparison_df,
        ai_analysis,
        current_start,
        current_end,
        previous_start,
        previous_end
    )

    print("Saved weekly_summary.md and weekly_summary.html")
    print("Saved query and page comparison outputs")


if __name__ == "__main__":
    main()
