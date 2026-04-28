
from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
from weasyprint import HTML
import pandas as pd
import requests
import os
import html
import base64
from io import BytesIO
import matplotlib
from pdf_report_formatter import get_pdf_css, html_table_from_df, build_card
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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

    priority_order = {"high": 0, "medium": 1, "low": 2}
    merged["priority_order"] = merged["priority"].str.lower().map(priority_order).fillna(9)
    merged = merged.sort_values(
        by=["priority_order", "clicks_current", "impressions_current"],
        ascending=[True, False, False]
    ).drop(columns=["priority_order"])

    return merged





def short_page_label(url, max_len=52):
    if not isinstance(url, str):
        return ""
    label = url.replace("https://", "").replace("http://", "")
    if len(label) > max_len:
        return label[:max_len - 1] + "…"
    return label


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


def build_executive_commentary(comparison_df, current_start, current_end, previous_start, previous_end):
    if not GROQ_API_KEY:
        return "Executive commentary was unavailable because the commentary service was not configured."

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
- do not mention AI, models, or automation

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
                {"role": "system", "content": "You write precise weekly SEO landing page summaries."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content.strip()
        return content if content else "Executive commentary could not be generated for this reporting period."
    except Exception as e:
        return f"Executive commentary could not be generated for this reporting period. Error: {str(e)}"


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
    return work.to_markdown(index=False)




def fig_to_base64(fig):
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    encoded = base64.b64encode(buffer.read()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def create_kpi_comparison_chart(comparison_df):
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

    fig, ax = plt.subplots(figsize=(11, 4.8))
    x = range(len(labels))
    width = 0.36
    ax.bar([i - width/2 for i in x], previous_vals, width=width, label="Previous", color="#c7d2fe")
    ax.bar([i + width/2 for i in x], current_vals, width=width, label="Current", color="#0f766e")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_title("Current Week vs Previous Week", fontsize=13, fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.legend(frameon=False)
    return fig_to_base64(fig)


def create_top_pages_chart(top_pages):
    work = top_pages.head(10).iloc[::-1].copy()
    labels = [short_page_label(v, 42) for v in work["page"]]
    vals = pd.to_numeric(work["clicks_current"], errors="coerce").fillna(0)

    fig, ax = plt.subplots(figsize=(11, 5.3))
    ax.barh(labels, vals, color="#2563eb")
    ax.set_title("Top Landing Pages by Clicks", fontsize=13, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.tick_params(axis='y', labelsize=8)
    return fig_to_base64(fig)


def create_traffic_change_chart(gainers, losers):
    gainers = gainers.head(5).copy()
    losers = losers.head(5).copy()

    labels = [short_page_label(v, 36) for v in list(losers["page"])[::-1] + list(gainers["page"])[::-1]]
    values = list(pd.to_numeric(losers["clicks_change"], errors="coerce").fillna(0))[::-1] + \
             list(pd.to_numeric(gainers["clicks_change"], errors="coerce").fillna(0))[::-1]
    colors = ["#ea580c" if v < 0 else "#0f766e" for v in values]

    fig, ax = plt.subplots(figsize=(11, 5.4))
    ax.barh(labels, values, color=colors)
    ax.axvline(0, color="#475569", linewidth=1)
    ax.set_title("Traffic Winners and Losers", fontsize=13, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.2)
    ax.tick_params(axis='y', labelsize=8)
    return fig_to_base64(fig)


def create_position_change_chart(position_gainers, position_losers):
    position_gainers = position_gainers.head(5).copy()
    position_losers = position_losers.head(5).copy()

    loser_vals = list(pd.to_numeric(position_losers["position_change"], errors="coerce").fillna(0))[::-1]
    gainer_vals = list(pd.to_numeric(position_gainers["position_change"], errors="coerce").fillna(0))[::-1]
    labels = [short_page_label(v, 36) for v in list(position_losers["page"])[::-1] + list(position_gainers["page"])[::-1]]
    values = loser_vals + gainer_vals
    colors = ["#dc2626" if v > 0 else "#059669" for v in values]

    fig, ax = plt.subplots(figsize=(11, 5.4))
    ax.barh(labels, values, color=colors)
    ax.axvline(0, color="#475569", linewidth=1)
    ax.set_title("Position Movement", fontsize=13, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.2)
    ax.tick_params(axis='y', labelsize=8)
    return fig_to_base64(fig)


def write_markdown_summary(comparison_df, executive_commentary, current_start, current_end, previous_start, previous_end):
    executive_read = build_executive_read(comparison_df)

    top_pages = comparison_df.sort_values(by=["clicks_current", "impressions_current"], ascending=[False, False]).head(25)
    biggest_gainers = comparison_df.sort_values(by="clicks_change", ascending=False).head(15)
    biggest_losers = comparison_df.sort_values(by="clicks_change", ascending=True).head(15)
    position_gainers = comparison_df[comparison_df["position_improved"]].sort_values(by="position_change", ascending=True).head(15)
    position_losers = comparison_df[comparison_df["position_declined"]].sort_values(by="position_change", ascending=False).head(15)
    lost_visibility = comparison_df[comparison_df["lost_visibility"]].head(15)

    lines = [
        "# Critical Landing Pages to Monitor",
        "",
        "## Executive Read",
        "",
    ]
    lines.extend([f"- {line}" for line in executive_read])
    lines.extend([
        "",
        "## Executive Commentary",
        "",
        executive_commentary,
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


def write_html_summary(comparison_df, executive_commentary, current_start, current_end, previous_start, previous_end):
    executive_read = build_executive_read(comparison_df)

    top_pages = comparison_df.sort_values(by=["clicks_current", "impressions_current"], ascending=[False, False]).head(25)
    biggest_gainers = comparison_df.sort_values(by="clicks_change", ascending=False).head(15)
    biggest_losers = comparison_df.sort_values(by="clicks_change", ascending=True).head(15)
    position_gainers = comparison_df[comparison_df["position_improved"]].sort_values(by="position_change", ascending=True).head(15)
    position_losers = comparison_df[comparison_df["position_declined"]].sort_values(by="position_change", ascending=False).head(15)
    lost_visibility = comparison_df[comparison_df["lost_visibility"]].head(15)

    visible_now = int((comparison_df["impressions_current"] > 0).sum())
    improved_count = int(comparison_df["position_improved"].sum())
    declined_count = int(comparison_df["position_declined"].sum())
    total_clicks = int(comparison_df["clicks_current"].sum())
    total_impressions = int(comparison_df["impressions_current"].sum())
    weighted_ctr = (comparison_df["clicks_current"].sum() / total_impressions) if total_impressions else 0
    avg_position = comparison_df.loc[comparison_df["impressions_current"] > 0, "position_current"].mean()
    avg_position = 0 if pd.isna(avg_position) else avg_position

    charts = {
        "kpi": create_kpi_comparison_chart(comparison_df),
        "top_pages": create_top_pages_chart(top_pages),
        "traffic_changes": create_traffic_change_chart(biggest_gainers, biggest_losers),
        "position_changes": create_position_change_chart(position_gainers, position_losers),
    }

    html_output = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Critical Landing Pages to Monitor</title>
<style>
{get_pdf_css()}
.chart-card {{
    background: #fff;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    padding: 12px;
    margin: 0 0 16px 0;
    page-break-inside: avoid;
}}
.chart-card img {{
    width: 100%;
    display: block;
}}
</style>
</head>
<body>
    <h1>Critical Landing Pages to Monitor</h1>
    <div class="muted">Reporting window: {current_start} to {current_end} | Prior period: {previous_start} to {previous_end}</div>

    <div class="panel">
        <h2>Executive Summary</h2>
        <ul>{''.join(f"<li>{html.escape(line)}</li>" for line in executive_read)}</ul>
        
        <h2>Executive Commentary</h2>
        <div class="ai-block">{html.escape(executive_commentary)}</div>
    </div>

    <h2>KPI Snapshot</h2>
    <div class="grid">
        {build_card("Visible Pages", visible_now, None)}
        {build_card("Total Clicks", total_clicks, None)}
        {build_card("Weighted CTR", weighted_ctr, None, is_pct=True)}
        {build_card("Avg Position", avg_position, None, decimals=2)}
    </div>
    <div class="grid" style="margin-top:16px;">
        {build_card("Position Improvements", improved_count, None)}
        {build_card("Position Declines", declined_count, None)}
        {build_card("Newly Visible", int(comparison_df["newly_visible"].sum()), None)}
        {build_card("Lost Visibility", int(comparison_df["lost_visibility"].sum()), None)}
    </div>

    <h2>Performance Overview</h2>
    <div class="chart-card"><img src="{charts['kpi']}" alt="Current Week vs Previous Week"></div>

    <div class="break-before"></div>
    <h2>Top Demand Drivers</h2>
    <div class="chart-card"><img src="{charts['top_pages']}" alt="Top landing pages by clicks"></div>

    <div class="break-before"></div>
    <h2>Traffic Winners and Losers</h2>
    <div class="chart-card"><img src="{charts['traffic_changes']}" alt="Traffic winners and losers"></div>

    <div class="break-before"></div>
    <h2>Position Movement</h2>
    <div class="chart-card"><img src="{charts['position_changes']}" alt="Position movement"></div>

    <div class="break-before"></div>
    <h2>Tracked Landing Pages</h2>
    {html_table_from_df(
        top_pages,
        ["page", "category", "priority", "clicks_current", "impressions_current", "ctr_current", "position_current", "clicks_change"],
        {{
            "page": "Page",
            "category": "Category",
            "priority": "Priority",
            "clicks_current": "Clicks",
            "impressions_current": "Impr",
            "ctr_current": "CTR",
            "position_current": "Pos",
            "clicks_change": "Clicks Δ",
        }}
    )}

    <h2>Biggest Traffic Gainers</h2>
    {html_table_from_df(
        biggest_gainers,
        ["page", "clicks_previous", "clicks_current", "clicks_change", "impressions_current"],
        {{
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Curr Clicks",
            "clicks_change": "Δ",
            "impressions_current": "Impr",
        }}
    )}

    <h2>Biggest Traffic Losers</h2>
    {html_table_from_df(
        biggest_losers,
        ["page", "clicks_previous", "clicks_current", "clicks_change", "impressions_current"],
        {{
            "page": "Page",
            "clicks_previous": "Prev Clicks",
            "clicks_current": "Curr Clicks",
            "clicks_change": "Δ",
            "impressions_current": "Impr",
        }}
    )}

    <div class="break-before"></div>
    <h2>Best Position Improvements</h2>
    {html_table_from_df(
        position_gainers,
        ["page", "position_previous", "position_current", "position_change", "clicks_current"],
        {{
            "page": "Page",
            "position_previous": "Prev Pos",
            "position_current": "Curr Pos",
            "position_change": "Pos Δ",
            "clicks_current": "Clicks",
        }}
    )}

    <h2>Biggest Position Declines</h2>
    {html_table_from_df(
        position_losers,
        ["page", "position_previous", "position_current", "position_change", "clicks_current"],
        {{
            "page": "Page",
            "position_previous": "Prev Pos",
            "position_current": "Curr Pos",
            "position_change": "Pos Δ",
            "clicks_current": "Clicks",
        }}
    )}

    <div class="break-before"></div>
    <h2>Lost Visibility</h2>
    {html_table_from_df(
        lost_visibility,
        ["page", "category", "priority", "impressions_previous", "impressions_current"],
        {{
            "page": "Page",
            "category": "Category",
            "priority": "Priority",
            "impressions_previous": "Prev Impr",
            "impressions_current": "Curr Impr",
        }}
    )}
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
            headers={"Authorization": MONDAY_API_TOKEN},
            data={
                "query": file_query,
                "variables": json.dumps({"update_id": str(update_id), "file": None}),
                "map": json.dumps({"pdf": ["variables.file"]}),
            },
            files={"pdf": ("critical-landing-pages-to-monitor.pdf", f, "application/pdf")},
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

    executive_commentary = build_executive_commentary(
        comparison_df,
        current_start,
        current_end,
        previous_start,
        previous_end
    )

    write_markdown_summary(
        comparison_df,
        executive_commentary,
        current_start,
        current_end,
        previous_start,
        previous_end
    )
    write_html_summary(
        comparison_df,
        executive_commentary,
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
