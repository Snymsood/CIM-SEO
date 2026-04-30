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
import matplotlib
from pdf_report_formatter import html_table_from_df, format_delta
from html_report_utils import (
    mm_html_shell, mm_kpi_card, mm_kpi_grid, mm_section, mm_report_section,
    mm_col_header, mm_chart_wrap, mm_exec_bullets, mm_ai_block,
    generate_self_contained_html, upload_html_to_monday,
)
from seo_utils import get_weekly_date_windows
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
KEY_FILE = "gsc-key.json"
SITE_URL = os.environ["GSC_PROPERTY"]
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")
CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

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
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x, decimals=2) if pd.notnull(x) else "")
        elif "change" in lower_col:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x, decimals=0) if pd.notnull(x) else "")
        elif any(token in lower_col for token in ["click", "impression"]):
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: f"{x:.0f}" if pd.notnull(x) else "")
        else:
            work[col] = work[col].fillna("").astype(str)
    return work.to_markdown(index=False)




def save_fig(fig, name):
    path = CHARTS_DIR / name
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return f"file://{path.absolute()}"


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
    return save_fig(fig, "landing_page_comparison.png")


def create_top_pages_chart(top_pages):
    work = top_pages.head(10).iloc[::-1].copy()
    labels = [short_page_label(v, 42) for v in work["page"]]
    vals = pd.to_numeric(work["clicks_current"], errors="coerce").fillna(0)

    fig, ax = plt.subplots(figsize=(11, 5.3))
    ax.barh(labels, vals, color="#2563eb")
    ax.set_title("Top Landing Pages by Clicks", fontsize=13, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.tick_params(axis='y', labelsize=8)
    return save_fig(fig, "landing_page_top_clicks.png")


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
    return save_fig(fig, "landing_page_traffic_changes.png")


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
    return save_fig(fig, "landing_page_position_changes.png")


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
    executive_read  = build_executive_read(comparison_df)
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

    charts = {
        "kpi":              create_kpi_comparison_chart(comparison_df),
        "top_pages":        create_top_pages_chart(top_pages),
        "traffic_changes":  create_traffic_change_chart(biggest_gainers, biggest_losers),
        "position_changes": create_position_change_chart(position_gainers, position_losers),
    }

    def tbl(df, cols, rename):
        return html_table_from_df(df, cols, rename) if not df.empty else "<p>No data.</p>"

    kpi_grid = mm_kpi_grid(
        mm_kpi_card("Visible Pages",  visible_now,  None),
        mm_kpi_card("Total Clicks",   total_clicks, None),
        mm_kpi_card("Weighted CTR",   weighted_ctr, None, is_pct=True),
        mm_kpi_card("Avg Position",   avg_position, None, decimals=2, lower_better=True),
    )

    body = (
        mm_section("Executive Summary",
            mm_report_section(mm_exec_bullets(executive_read) + mm_ai_block(executive_commentary))
        ) +
        f'<div class="section" style="padding-top:0;">{kpi_grid}</div>'
        '<hr class="rule-thick">' +
        mm_section("Performance Overview",
            mm_report_section(mm_chart_wrap(charts["kpi"], "Current vs previous week"))
        ) +
        mm_section("Top Demand Drivers",
            mm_report_section(mm_chart_wrap(charts["top_pages"], "Top landing pages by clicks"))
        ) +
        mm_section("Traffic Winners and Losers",
            mm_report_section(mm_chart_wrap(charts["traffic_changes"], "Traffic winners and losers"))
        ) +
        mm_section("Position Movement",
            mm_report_section(mm_chart_wrap(charts["position_changes"], "Position movement"))
        ) +
        mm_section("Tracked Landing Pages",
            mm_report_section(tbl(top_pages,
                ["page","category","priority","clicks_current","impressions_current","ctr_current","position_current","clicks_change"],
                {"page":"Page","category":"Category","priority":"Priority","clicks_current":"Clicks","impressions_current":"Impr",
                 "ctr_current":"CTR","position_current":"Pos","clicks_change":"Clicks Δ"}
            ))
        ) +
        mm_section("Biggest Traffic Gainers",
            mm_report_section(tbl(biggest_gainers,
                ["page","clicks_previous","clicks_current","clicks_change","impressions_current"],
                {"page":"Page","clicks_previous":"Prev Clicks","clicks_current":"Curr Clicks","clicks_change":"Δ","impressions_current":"Impr"}
            ))
        ) +
        mm_section("Biggest Traffic Losers",
            mm_report_section(tbl(biggest_losers,
                ["page","clicks_previous","clicks_current","clicks_change","impressions_current"],
                {"page":"Page","clicks_previous":"Prev Clicks","clicks_current":"Curr Clicks","clicks_change":"Δ","impressions_current":"Impr"}
            ))
        ) +
        mm_section("Best Position Improvements",
            mm_report_section(tbl(position_gainers,
                ["page","position_previous","position_current","position_change","clicks_current"],
                {"page":"Page","position_previous":"Prev Pos","position_current":"Curr Pos","position_change":"Pos Δ","clicks_current":"Clicks"}
            ))
        ) +
        mm_section("Biggest Position Declines",
            mm_report_section(tbl(position_losers,
                ["page","position_previous","position_current","position_change","clicks_current"],
                {"page":"Page","position_previous":"Prev Pos","position_current":"Curr Pos","position_change":"Pos Δ","clicks_current":"Clicks"}
            ))
        ) +
        mm_section("Lost Visibility",
            mm_report_section(tbl(lost_visibility,
                ["page","category","priority","impressions_previous","impressions_current"],
                {"page":"Page","category":"Category","priority":"Priority","impressions_previous":"Prev Impr","impressions_current":"Curr Impr"}
            ))
        )
    )

    doc = mm_html_shell(
        title="Critical Landing Pages Performance",
        eyebrow="Google Search Console",
        headline="Critical Landing\nPages",
        meta_line=f"{current_start} → {current_end} / prev {previous_start} → {previous_end}",
        body_content=body,
    )
    with open("landing_pages_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("Saved landing_pages_summary.html")


def generate_self_contained():
    generate_self_contained_html("landing_pages_summary.html", "landing_pages_summary_final.html")


def upload_to_monday():
    upload_html_to_monday(
        "landing_pages_summary_final.html",
        "critical-landing-pages.html",
        body_text="Critical Landing Pages Report attached as self-contained HTML.",
    )


def main():
    service = get_service()
    tracked_df = load_tracked_pages()

    current_start, current_end, previous_start, previous_end = get_weekly_date_windows()

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

    write_markdown_summary(comparison_df, executive_commentary, current_start, current_end, previous_start, previous_end)
    write_html_summary(comparison_df, executive_commentary, current_start, current_end, previous_start, previous_end)
    generate_self_contained()

    try:
        upload_to_monday()
    except Exception as e:
        print(f"monday upload step failed: {e}")

    print("Saved landing page outputs.")


if __name__ == "__main__":
    main()
