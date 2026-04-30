from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
import pandas as pd
import requests
import os
import html
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
TRACKED_KEYWORDS_FILE = "tracked_keywords.csv"
CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

ACCENT = "#0f4c81"
ACCENT_2 = "#2f7d8c"
ACCENT_3 = "#d06b43"
ACCENT_4 = "#6a8caf"
TEXT = "#1f2937"
MUTED = "#6b7280"
BG = "#f4f6fb"
CARD = "#ffffff"
BORDER = "#d8dee9"


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


def fetch_query_data(service, start_date, end_date, row_limit=1000):
    request = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["query"],
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
            "query": str(row["keys"][0]).strip().lower(),
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0),
            "position": row.get("position", 0),
        })

    if not data:
        return pd.DataFrame(columns=["query", "clicks", "impressions", "ctr", "position"])

    return pd.DataFrame(data)


def build_keyword_snapshot(tracked_df, query_df):
    merged = pd.merge(
        tracked_df,
        query_df,
        left_on="keyword",
        right_on="query",
        how="left"
    )

    merged["clicks"] = merged["clicks"].fillna(0)
    merged["impressions"] = merged["impressions"].fillna(0)
    merged["ctr"] = merged["ctr"].fillna(0)
    merged["position"] = merged["position"].fillna(0)

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
    ).fillna(0)

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




def build_executive_read(comparison_df):
    lines = []

    visible_now = comparison_df[comparison_df["impressions_current"] > 0]
    improved = comparison_df[comparison_df["ranking_improved"]]
    declined = comparison_df[comparison_df["ranking_declined"]]
    entered_top_3 = comparison_df[comparison_df["entered_top_3"]]
    entered_top_10 = comparison_df[comparison_df["entered_top_10"]]
    lost_visibility = comparison_df[comparison_df["lost_visibility"]]

    lines.append(f"{len(visible_now)} tracked keywords generated visibility this week.")

    if len(improved) > len(declined):
        lines.append("More tracked keywords improved in average position than declined.")
    elif len(improved) < len(declined):
        lines.append("More tracked keywords declined in average position than improved.")
    else:
        lines.append("Ranking movement was mixed across the tracked keyword set.")

    if not entered_top_3.empty:
        lines.append(f"{len(entered_top_3)} tracked keywords entered the top 3.")
    if not entered_top_10.empty:
        lines.append(f"{len(entered_top_10)} tracked keywords entered the top 10.")
    if not lost_visibility.empty:
        lines.append(f"{len(lost_visibility)} tracked keywords lost visibility week over week.")

    high_priority = comparison_df[comparison_df["priority"].str.lower() == "high"]
    if not high_priority.empty:
        avg_pos = high_priority.loc[high_priority["position_current"] > 0, "position_current"]
        if not avg_pos.empty:
            lines.append(f"High-priority keywords averaged position {avg_pos.mean():.2f} this week.")

    return lines


def build_executive_commentary(comparison_df, current_start, current_end, previous_start, previous_end):
    if not GROQ_API_KEY:
        return "Executive commentary was unavailable for this run."

    top_table = comparison_df[[
        "keyword", "category", "priority", "clicks_current", "impressions_current",
        "position_current", "clicks_change", "position_change"
    ]].head(15)

    prompt = f"""
You are writing concise executive commentary for a manually prepared keyword ranking report.

Write:
1. Executive Summary
2. Ranking Improvements
3. Ranking Risks
4. Recommended Actions

Requirements:
- professional corporate tone
- concise and readable
- under 300 words
- do not mention AI, models, automation, or system-generated analysis
- do not invent data
- focus on ranking movement and visibility changes
- write as if this is part of a manually produced executive report

Current period: {current_start} to {current_end}
Previous period: {previous_start} to {previous_end}

Tracked keyword data:
{top_table.to_csv(index=False)}
"""

    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write precise weekly SEO executive commentary."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content.strip()
        return content if content else "Executive commentary was unavailable for this run."
    except Exception:
        return "Executive commentary was unavailable for this run."


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

    header = "| " + " | ".join(work.columns) + " |"
    separator = "| " + " | ".join(["---"] * len(work.columns)) + " |"
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in work.values.tolist()]
    return "\n".join([header, separator] + rows)




def save_fig(fig, name):
    path = CHARTS_DIR / name
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path.absolute())


def make_barh_chart(df, label_col, value_col, title, color, top_n=10):
    if df.empty:
        return ""
    chart_df = df.head(top_n).copy().iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.barh(chart_df[label_col], chart_df[value_col], color=color)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.spines[['top', 'right']].set_visible(False)
    ax.tick_params(axis='y', labelsize=9)
    ax.tick_params(axis='x', labelsize=9)
    fig.tight_layout()
    return save_fig(fig, "keyword_ranking_overview.png")


def make_diverging_position_chart(gainers_df, losers_df, label_col, value_col, title):
    g = gainers_df.head(6).copy()
    l = losers_df.head(6).copy()
    if g.empty and l.empty:
        return ""

    g = g[[label_col, value_col]].copy()
    l = l[[label_col, value_col]].copy()
    g[value_col] = g[value_col].abs()
    l[value_col] = -l[value_col].abs()
    plot_df = pd.concat([g, l], ignore_index=True)
    plot_df = plot_df.sort_values(by=value_col)

    colors = [ACCENT_3 if v < 0 else ACCENT_2 for v in plot_df[value_col]]

    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.barh(plot_df[label_col], plot_df[value_col], color=colors)
    ax.axvline(0, color="#444", linewidth=1)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.spines[['top', 'right']].set_visible(False)
    ax.tick_params(axis='y', labelsize=9)
    ax.tick_params(axis='x', labelsize=9)
    fig.tight_layout()
    return save_fig(fig, "keyword_ranking_winners_losers.png")


def make_kpi_comparison_chart(comparison_df):
    visible_now = int((comparison_df["impressions_current"] > 0).sum())
    visible_prev = int((comparison_df["impressions_previous"] > 0).sum())
    improved_count = int(comparison_df["ranking_improved"].sum())
    declined_count = int(comparison_df["ranking_declined"].sum())
    entered_top_10 = int(comparison_df["entered_top_10"].sum())
    entered_top_3 = int(comparison_df["entered_top_3"].sum())

    metrics = ["Visible", "Improved", "Declined", "Top 10", "Top 3"]
    prev_vals = [visible_prev, 0, 0, 0, 0]
    curr_vals = [visible_now, improved_count, declined_count, entered_top_10, entered_top_3]

    x = range(len(metrics))
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.bar([i - 0.18 for i in x], prev_vals, width=0.36, label="Previous", color="#b7c2d0")
    ax.bar([i + 0.18 for i in x], curr_vals, width=0.36, label="Current", color=ACCENT)
    ax.set_xticks(list(x))
    ax.set_xticklabels(metrics)
    ax.set_title("Keyword Visibility and Ranking Movement", fontsize=14, fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.legend(frameon=False)
    ax.spines[['top', 'right']].set_visible(False)
    fig.tight_layout()
    return save_fig(fig, "keyword_ranking_distribution.png")


def write_markdown_summary(comparison_df, commentary, current_start, current_end, previous_start, previous_end):
    executive_read = build_executive_read(comparison_df)

    top_keywords = comparison_df.sort_values(by=["clicks_current", "impressions_current"], ascending=[False, False]).head(15)
    biggest_gainers = comparison_df[comparison_df["ranking_improved"]].sort_values(by="position_change", ascending=True).head(15)
    biggest_losers = comparison_df[comparison_df["ranking_declined"]].sort_values(by="position_change", ascending=False).head(15)
    entered_top_3 = comparison_df[comparison_df["entered_top_3"]].head(15)
    entered_top_10 = comparison_df[comparison_df["entered_top_10"]].head(15)
    lost_visibility = comparison_df[comparison_df["lost_visibility"]].head(15)

    lines = []
    lines.append("# Weekly Keyword Ranking Review")
    lines.append("")
    lines.append("## Executive Read")
    lines.append("")
    for line in executive_read:
        lines.append(f"- {line}")
    lines.append("")
    lines.append("## Executive Commentary")
    lines.append("")
    lines.append(commentary)
    lines.append("")
    lines.append("## Reporting Window")
    lines.append("")
    lines.append(f"- Current period: {current_start} to {current_end}")
    lines.append(f"- Previous period: {previous_start} to {previous_end}")
    lines.append("")
    lines.append("## Top Tracked Keywords")
    lines.append("")
    lines.append(md_table_from_df(
        top_keywords,
        ["keyword", "category", "priority", "clicks_current", "impressions_current", "position_current", "position_change"],
        {
            "keyword": "Keyword",
            "category": "Category",
            "priority": "Priority",
            "clicks_current": "Clicks",
            "impressions_current": "Impressions",
            "position_current": "Current Position",
            "position_change": "WoW Position Δ",
        }
    ))
    lines.append("")
    lines.append("## Biggest Ranking Improvements")
    lines.append("")
    lines.append(md_table_from_df(biggest_gainers, ["keyword", "position_previous", "position_current", "position_change", "clicks_current"], {
        "keyword": "Keyword", "position_previous": "Prev Position", "position_current": "Current Position", "position_change": "Position Δ", "clicks_current": "Clicks"
    }))
    lines.append("")
    lines.append("## Biggest Ranking Declines")
    lines.append("")
    lines.append(md_table_from_df(biggest_losers, ["keyword", "position_previous", "position_current", "position_change", "clicks_current"], {
        "keyword": "Keyword", "position_previous": "Prev Position", "position_current": "Current Position", "position_change": "Position Δ", "clicks_current": "Clicks"
    }))
    lines.append("")
    lines.append("## Entered Top 3")
    lines.append("")
    lines.append(md_table_from_df(entered_top_3, ["keyword", "category", "priority", "position_previous", "position_current"], {
        "keyword": "Keyword", "category": "Category", "priority": "Priority", "position_previous": "Prev Position", "position_current": "Current Position"
    }))
    lines.append("")
    lines.append("## Entered Top 10")
    lines.append("")
    lines.append(md_table_from_df(entered_top_10, ["keyword", "category", "priority", "position_previous", "position_current"], {
        "keyword": "Keyword", "category": "Category", "priority": "Priority", "position_previous": "Prev Position", "position_current": "Current Position"
    }))
    lines.append("")
    lines.append("## Lost Visibility")
    lines.append("")
    lines.append(md_table_from_df(lost_visibility, ["keyword", "category", "priority", "impressions_previous", "impressions_current"], {
        "keyword": "Keyword", "category": "Category", "priority": "Priority", "impressions_previous": "Prev Impressions", "impressions_current": "Current Impressions"
    }))

    with open("keyword_ranking_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_html_summary(comparison_df, commentary, current_start, current_end, previous_start, previous_end):
    executive_read = build_executive_read(comparison_df)

    top_keywords    = comparison_df.sort_values(by=["clicks_current","impressions_current"], ascending=[False,False]).head(15)
    biggest_gainers = comparison_df[comparison_df["ranking_improved"]].sort_values(by="position_change", ascending=True).head(15)
    biggest_losers  = comparison_df[comparison_df["ranking_declined"]].sort_values(by="position_change", ascending=False).head(15)
    entered_top_3   = comparison_df[comparison_df["entered_top_3"]].head(15)
    entered_top_10  = comparison_df[comparison_df["entered_top_10"]].head(15)
    lost_visibility = comparison_df[comparison_df["lost_visibility"]].head(15)

    visible_now    = int((comparison_df["impressions_current"] > 0).sum())
    visible_prev   = int((comparison_df["impressions_previous"] > 0).sum())
    improved_count = int(comparison_df["ranking_improved"].sum())
    declined_count = int(comparison_df["ranking_declined"].sum())
    avg_pos_curr   = comparison_df.loc[comparison_df["position_current"] > 0, "position_current"].mean()
    avg_pos_prev   = comparison_df.loc[comparison_df["position_previous"] > 0, "position_previous"].mean()
    avg_pos_curr   = 0 if pd.isna(avg_pos_curr) else avg_pos_curr
    avg_pos_prev   = 0 if pd.isna(avg_pos_prev) else avg_pos_prev

    kpi_chart          = make_kpi_comparison_chart(comparison_df)
    top_keywords_chart = make_barh_chart(top_keywords, "keyword", "clicks_current", "Top Tracked Keywords by Clicks", ACCENT_2, 10)
    visibility_chart   = make_barh_chart(top_keywords, "keyword", "impressions_current", "Top Tracked Keywords by Impressions", ACCENT_4, 10)
    winners_losers_chart = make_diverging_position_chart(
        biggest_gainers.assign(delta=biggest_gainers["position_previous"] - biggest_gainers["position_current"]),
        biggest_losers.assign(delta=biggest_losers["position_previous"] - biggest_losers["position_current"]),
        "keyword", "delta", "Ranking Winners and Losers"
    )

    def tbl(df, cols, rename):
        return html_table_from_df(df, cols, rename) if not df.empty else "<p>No data.</p>"

    kpi_grid = mm_kpi_grid(
        mm_kpi_card("Visible Keywords",    visible_now,    visible_prev),
        mm_kpi_card("Ranking Improvements",improved_count, None),
        mm_kpi_card("Ranking Declines",    declined_count, None),
        mm_kpi_card("Avg Position",        avg_pos_curr,   avg_pos_prev, decimals=2, lower_better=True),
    )

    body = (
        mm_section("Executive Summary",
            mm_report_section(mm_exec_bullets(executive_read) + mm_ai_block(commentary))
        ) +
        f'<div class="section" style="padding-top:0;">{kpi_grid}</div>'
        '<hr class="rule-thick">' +
        mm_section("Performance Overview",
            mm_report_section(mm_chart_wrap(kpi_chart, "Keyword visibility and ranking movement"))
        ) +
        mm_section("Top Demand Drivers",
            mm_report_section(
                mm_chart_wrap(top_keywords_chart, "Top tracked keywords by clicks") +
                mm_chart_wrap(visibility_chart, "Top tracked keywords by impressions")
            )
        ) +
        mm_section("Winners and Losers",
            mm_report_section(mm_chart_wrap(winners_losers_chart, "Ranking winners and losers"))
        ) +
        mm_section("Top Tracked Keywords",
            mm_report_section(tbl(top_keywords,
                ["keyword","category","priority","clicks_current","impressions_current","position_current","position_change"],
                {"keyword":"Keyword","category":"Category","priority":"Priority","clicks_current":"Clicks",
                 "impressions_current":"Impr","position_current":"Pos","position_change":"Pos Δ"}
            ))
        ) +
        mm_section("Biggest Ranking Improvements",
            mm_report_section(tbl(biggest_gainers,
                ["keyword","position_previous","position_current","position_change","clicks_current"],
                {"keyword":"Keyword","position_previous":"Prev Pos","position_current":"Curr Pos","position_change":"Pos Δ","clicks_current":"Clicks"}
            ))
        ) +
        mm_section("Biggest Ranking Declines",
            mm_report_section(tbl(biggest_losers,
                ["keyword","position_previous","position_current","position_change","clicks_current"],
                {"keyword":"Keyword","position_previous":"Prev Pos","position_current":"Curr Pos","position_change":"Pos Δ","clicks_current":"Clicks"}
            ))
        ) +
        mm_section("Entered Top 3",
            mm_report_section(tbl(entered_top_3,
                ["keyword","category","priority","position_previous","position_current"],
                {"keyword":"Keyword","category":"Category","priority":"Priority","position_previous":"Prev Pos","position_current":"Curr Pos"}
            ))
        ) +
        mm_section("Entered Top 10",
            mm_report_section(tbl(entered_top_10,
                ["keyword","category","priority","position_previous","position_current"],
                {"keyword":"Keyword","category":"Category","priority":"Priority","position_previous":"Prev Pos","position_current":"Curr Pos"}
            ))
        ) +
        mm_section("Lost Visibility",
            mm_report_section(tbl(lost_visibility,
                ["keyword","category","priority","impressions_previous","impressions_current"],
                {"keyword":"Keyword","category":"Category","priority":"Priority","impressions_previous":"Prev Impr","impressions_current":"Curr Impr"}
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

    current_query_df = fetch_query_data(service, current_start, current_end, row_limit=1000)
    previous_query_df = fetch_query_data(service, previous_start, previous_end, row_limit=1000)

    current_snapshot_df = build_keyword_snapshot(tracked_df, current_query_df)
    previous_snapshot_df = build_keyword_snapshot(tracked_df, previous_query_df)

    comparison_df = prepare_comparison(current_snapshot_df, previous_snapshot_df)

    current_snapshot_df.to_csv("tracked_keywords_current_week.csv", index=False)
    previous_snapshot_df.to_csv("tracked_keywords_previous_week.csv", index=False)
    comparison_df.to_csv("tracked_keywords_comparison.csv", index=False)

    ranking_gainers = comparison_df[comparison_df["ranking_improved"]].sort_values(by="position_change", ascending=True)
    ranking_losers = comparison_df[comparison_df["ranking_declined"]].sort_values(by="position_change", ascending=False)
    top_3 = comparison_df[comparison_df["entered_top_3"]]
    top_10 = comparison_df[comparison_df["entered_top_10"]]

    ranking_gainers.to_csv("ranking_gainers.csv", index=False)
    ranking_losers.to_csv("ranking_losers.csv", index=False)
    top_3.to_csv("entered_top_3.csv", index=False)
    top_10.to_csv("entered_top_10.csv", index=False)

    commentary = build_executive_commentary(
        comparison_df,
        current_start,
        current_end,
        previous_start,
        previous_end
    )

    write_markdown_summary(comparison_df, commentary, current_start, current_end, previous_start, previous_end)
    write_html_summary(comparison_df, commentary, current_start, current_end, previous_start, previous_end)
    generate_self_contained()

    try:
        upload_to_monday()
    except Exception as e:
        print(f"monday upload step failed: {e}")

    print("Saved keyword ranking outputs.")


if __name__ == "__main__":
    main()
