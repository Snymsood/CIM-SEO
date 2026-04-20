from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
from weasyprint import HTML
import pandas as pd
import requests
import os
import html

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
KEY_FILE = "gsc-key.json"
SITE_URL = os.environ["GSC_PROPERTY"]
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"
TRACKED_PAGES_FILE = "tracked_pages.csv"


def get_service():
    credentials = service_account.Credentials.from_service_account_file(
        KEY_FILE,
        scopes=SCOPES,
    )
    return build("searchconsole", "v1", credentials=credentials)


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

    response = service.searchanalytics().query(
        siteUrl=SITE_URL,
        body=request
    ).execute()

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
    ).fillna(0)

    merged["clicks_change"] = merged["clicks_current"] - merged["clicks_previous"]
    merged["impressions_change"] = merged["impressions_current"] - merged["impressions_previous"]
    merged["ctr_change"] = merged["ctr_current"] - merged["ctr_previous"]
    merged["position_change"] = merged["position_current"] - merged["position_previous"]

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

    return merged.sort_values(
        by=["priority", "clicks_current", "impressions_current"],
        ascending=[True, False, False]
    )


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
        return f"+{value:.2f}"
    return f"{value:.2f}"


def format_delta_int(value):
    if value > 0:
        return f"+{value:.0f}"
    return f"{value:.0f}"


def build_executive_read(comparison_df):
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


def build_ai_analysis(comparison_df, current_start, current_end, previous_start, previous_end):
    if not GROQ_API_KEY:
        return "AI executive analysis was skipped because GROQ_API_KEY is not configured."

    top_table = comparison_df[[
        "page", "category", "priority", "clicks_current", "impressions_current",
        "position_current", "clicks_change", "position_change"
    ]].head(15)

    prompt = f"""
You are writing a concise corporate landing page monitoring analysis for SEO stakeholders.

Write:
1. Executive Summary
2. Page Performance Gains
3. Page Risks
4. Recommended Actions

Requirements:
- professional corporate tone
- concise and readable
- under 350 words
- do not invent data
- focus on landing page movement and visibility changes
- avoid hype

Current period: {current_start} to {current_end}
Previous period: {previous_start} to {previous_end}

Tracked landing page data:
{top_table.to_csv(index=False)}
"""

    try:
        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write precise weekly SEO landing page summaries."},
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
        lower_col = col.lower()
        if "ctr" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.2%}" if pd.notnull(x) else "")
        elif "position" in lower_col and "change" not in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.2f}" if pd.notnull(x) and x != 0 else "")
        elif "position" in lower_col and "change" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x) if pd.notnull(x) else "")
        elif "change" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta_int(x) if pd.notnull(x) else "")
        elif any(token in lower_col for token in ["click", "impression"]):
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.0f}" if pd.notnull(x) else "")
        else:
            work[col] = work[col].fillna("").astype(str)

    header = "| " + " | ".join(work.columns) + " |"
    separator = "| " + " | ".join(["---"] * len(work.columns)) + " |"
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in work.values.tolist()]
    return "\n".join([header, separator] + rows)


def html_table_from_df(df, columns, rename_map=None):
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
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x) if pd.notnull(x) else "")
        elif "change" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta_int(x) if pd.notnull(x) else "")
        elif any(token in lower_col for token in ["click", "impression"]):
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.0f}" if pd.notnull(x) else "")
        else:
            work[col] = work[col].fillna("").astype(str)

    header_html = "".join(f"<th>{html.escape(str(col))}</th>" for col in work.columns)
    body_rows = []
    for row in work.values.tolist():
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in row)
        body_rows.append(f"<tr>{cells}</tr>")

    return f"""
    <table>
      <thead><tr>{header_html}</tr></thead>
      <tbody>{''.join(body_rows)}</tbody>
    </table>
    """


def write_markdown_summary(comparison_df, ai_analysis, current_start, current_end, previous_start, previous_end):
    executive_read = build_executive_read(comparison_df)

    top_pages = comparison_df.sort_values(by=["clicks_current", "impressions_current"], ascending=[False, False]).head(25)
    biggest_gainers = comparison_df.sort_values(by="clicks_change", ascending=False).head(15)
    biggest_losers = comparison_df.sort_values(by="clicks_change", ascending=True).head(15)
    position_gainers = comparison_df[comparison_df["position_improved"]].sort_values(by="position_change", ascending=True).head(15)
    position_losers = comparison_df[comparison_df["position_declined"]].sort_values(by="position_change", ascending=False).head(15)
    lost_visibility = comparison_df[comparison_df["lost_visibility"]].head(15)

    lines = []
    lines.append("# Critical Landing Pages to Monitor")
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
    lines.append("## Top Tracked Landing Pages")
    lines.append("")
    lines.append(md_table_from_df(
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
    ))

    lines.append("")
    lines.append("## Biggest Traffic Gainers")
    lines.append("")
    lines.append(md_table_from_df(
        biggest_gainers,
        ["page", "clicks_previous", "clicks_current", "clicks_change", "impressions_current"],
        {
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
            "impressions_current": "Impressions",
        }
    ))

    lines.append("")
    lines.append("## Biggest Traffic Losers")
    lines.append("")
    lines.append(md_table_from_df(
        biggest_losers,
        ["page", "clicks_previous", "clicks_current", "clicks_change", "impressions_current"],
        {
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
            "impressions_current": "Impressions",
        }
    ))

    lines.append("")
    lines.append("## Best Position Improvements")
    lines.append("")
    lines.append(md_table_from_df(
        position_gainers,
        ["page", "position_previous", "position_current", "position_change", "clicks_current"],
        {
            "page": "Page",
            "position_previous": "Prev Position",
            "position_current": "Current Position",
            "position_change": "Position Δ",
            "clicks_current": "Clicks",
        }
    ))

    lines.append("")
    lines.append("## Biggest Position Declines")
    lines.append("")
    lines.append(md_table_from_df(
        position_losers,
        ["page", "position_previous", "position_current", "position_change", "clicks_current"],
        {
            "page": "Page",
            "position_previous": "Prev Position",
            "position_current": "Current Position",
            "position_change": "Position Δ",
            "clicks_current": "Clicks",
        }
    ))

    lines.append("")
    lines.append("## Lost Visibility")
    lines.append("")
    lines.append(md_table_from_df(
        lost_visibility,
        ["page", "category", "priority", "impressions_previous", "impressions_current"],
        {
            "page": "Page",
            "category": "Category",
            "priority": "Priority",
            "impressions_previous": "Prev Impressions",
            "impressions_current": "Current Impressions",
        }
    ))

    with open("landing_pages_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_html_summary(comparison_df, ai_analysis, current_start, current_end, previous_start, previous_end):
    executive_read = build_executive_read(comparison_df)

    top_pages = comparison_df.sort_values(by=["clicks_current", "impressions_current"], ascending=[False, False]).head(25)
    biggest_gainers = comparison_df.sort_values(by="clicks_change", ascending=False).head(15)
    biggest_losers = comparison_df.sort_values(by="clicks_change", ascending=True).head(15)
    position_gainers = comparison_df[comparison_df["position_improved"]].sort_values(by="position_change", ascending=True).head(15)
    position_losers = comparison_df[comparison_df["position_declined"]].sort_values(by="position_change", ascending=False).head(15)
    lost_visibility = comparison_df[comparison_df["lost_visibility"]].head(15)

    def card(title, value, sub):
        return f"""
        <div class="card">
            <div class="label">{html.escape(title)}</div>
            <div class="value">{html.escape(value)}</div>
            <div class="sub">{html.escape(sub)}</div>
        </div>
        """

    visible_now = int((comparison_df["impressions_current"] > 0).sum())
    improved_count = int(comparison_df["position_improved"].sum())
    declined_count = int(comparison_df["position_declined"].sum())
    total_clicks = int(comparison_df["clicks_current"].sum())

    html_output = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Critical Landing Pages to Monitor</title>
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
        word-break: break-word;
    }}
    th {{
        background: #111827;
        color: white;
        font-size: 13px;
    }}
    tr:nth-child(even) td {{
        background: #f9fafb;
    }}
    .ai-block {{
        white-space: pre-wrap;
        line-height: 1.5;
    }}
</style>
</head>
<body>
<div class="container">
    <h1>Critical Landing Pages to Monitor</h1>
    <div class="muted">Current period: {current_start} to {current_end} | Previous period: {previous_start} to {previous_end}</div>

    <div class="panel">
        <h2>Executive Read</h2>
        <ul>{''.join(f"<li>{html.escape(line)}</li>" for line in executive_read)}</ul>
    </div>

    <div class="panel">
        <h2>AI Executive Analysis</h2>
        <div class="ai-block">{html.escape(ai_analysis)}</div>
    </div>

    <h2>KPI Snapshot</h2>
    <div class="grid">
        {card("Visible Pages", str(visible_now), "tracked pages with impressions")}
        {card("Total Clicks", str(total_clicks), "across tracked landing pages")}
        {card("Position Improvements", str(improved_count), "pages with better avg position")}
        {card("Position Declines", str(declined_count), "pages with weaker avg position")}
    </div>

    <h2>Top Tracked Landing Pages</h2>
    {html_table_from_df(
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
    )}

    <h2>Biggest Traffic Gainers</h2>
    {html_table_from_df(
        biggest_gainers,
        ["page", "clicks_previous", "clicks_current", "clicks_change", "impressions_current"],
        {
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
            "impressions_current": "Impressions",
        }
    )}

    <h2>Biggest Traffic Losers</h2>
    {html_table_from_df(
        biggest_losers,
        ["page", "clicks_previous", "clicks_current", "clicks_change", "impressions_current"],
        {
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Current Clicks",
            "clicks_change": "Δ",
            "impressions_current": "Impressions",
        }
    )}

    <h2>Best Position Improvements</h2>
    {html_table_from_df(
        position_gainers,
        ["page", "position_previous", "position_current", "position_change", "clicks_current"],
        {
            "page": "Page",
            "position_previous": "Prev Position",
            "position_current": "Current Position",
            "position_change": "Position Δ",
            "clicks_current": "Clicks",
        }
    )}

    <h2>Biggest Position Declines</h2>
    {html_table_from_df(
        position_losers,
        ["page", "position_previous", "position_current", "position_change", "clicks_current"],
        {
            "page": "Page",
            "position_previous": "Prev Position",
            "position_current": "Current Position",
            "position_change": "Position Δ",
            "clicks_current": "Clicks",
        }
    )}

    <h2>Lost Visibility</h2>
    {html_table_from_df(
        lost_visibility,
        ["page", "category", "priority", "impressions_previous", "impressions_current"],
        {
            "page": "Page",
            "category": "Category",
            "priority": "Priority",
            "impressions_previous": "Prev Impressions",
            "impressions_current": "Current Impressions",
        }
    )}
</div>
</body>
</html>
"""
    with open("landing_pages_summary.html", "w", encoding="utf-8") as f:
        f.write(html_output)


def generate_pdf():
    HTML("landing_pages_summary.html").write_pdf("landing_pages_summary.pdf")
    print("Saved landing_pages_summary.pdf")


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
        "body": "Critical landing pages PDF report attached.",
    }

    update_response = requests.post(
        MONDAY_API_URL,
        headers={
            "Authorization": MONDAY_API_TOKEN,
            "Content-Type": "application/json",
        },
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

    import json

    with open(pdf_path, "rb") as f:
        response = requests.post(
            MONDAY_FILE_API_URL,
            headers={
                "Authorization": MONDAY_API_TOKEN,
            },
            data={
                "query": file_query,
                "variables": json.dumps({
                    "update_id": str(update_id),
                    "file": None
                }),
                "map": json.dumps({
                    "pdf": ["variables.file"]
                }),
            },
            files={
                "pdf": ("critical-landing-pages-to-monitor.pdf", f, "application/pdf")
            },
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
    tracked_df = load_tracked_pages()

    current_end = date.today() - timedelta(days=1)
    current_start = current_end - timedelta(days=6)

    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)

    current_page_df = fetch_page_data(service, current_start, current_end, row_limit=1000)
    previous_page_df = fetch_page_data(service, previous_start, previous_end, row_limit=1000)

    current_snapshot_df = build_page_snapshot(tracked_df, current_page_df)
    previous_snapshot_df = build_page_snapshot(tracked_df, previous_page_df)

    comparison_df = prepare_comparison(current_snapshot_df, previous_snapshot_df)

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

    ai_analysis = build_ai_analysis(
        comparison_df,
        current_start,
        current_end,
        previous_start,
        previous_end
    )

    write_markdown_summary(
        comparison_df,
        ai_analysis,
        current_start,
        current_end,
        previous_start,
        previous_end
    )
    write_html_summary(
        comparison_df,
        ai_analysis,
        current_start,
        current_end,
        previous_start,
        previous_end
    )

    generate_pdf()

    try:
        upload_pdf_to_monday("landing_pages_summary.pdf")
    except Exception as e:
        print(f"monday upload step failed: {e}")

    print("Saved landing page outputs.")


if __name__ == "__main__":
    main()
