import asyncio
import aiohttp
from datetime import date
from openai import OpenAI
import pandas as pd
import requests
import os
import html
import json
import matplotlib

from google_sheets_db import append_to_sheet
from pdf_report_formatter import html_table_from_df
from html_report_utils import (
    mm_html_shell, mm_kpi_card, mm_kpi_grid, mm_section, mm_report_section,
    mm_col_header, mm_chart_wrap, mm_chart_row_2, mm_exec_bullets, mm_ai_block,
    generate_self_contained_html, upload_html_to_monday,
)
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")

TRACKED_PAGES_FILE = "tracked_speed_pages.csv"
SNAPSHOT_FILE = "site_speed_latest_snapshot.csv"
HISTORY_FILE = "site_speed_history.csv"
CHARTS_DIR = Path("site_speed_charts")

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"
PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


# ---------- data collection ----------
def load_tracked_pages():
    df = pd.read_csv(TRACKED_PAGES_FILE)
    df["page"] = df["page"].astype(str).str.strip()
    df["category"] = df["category"].astype(str).str.strip()
    df["priority"] = df["priority"].astype(str).str.strip()
    return df


def get_nested(data, path, default=None):
    current = data
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def get_audit_numeric(data, audit_key):
    value = get_nested(data, ["lighthouseResult", "audits", audit_key, "numericValue"], None)
    return float(value) if value is not None else None


def get_performance_score(data):
    score = get_nested(data, ["lighthouseResult", "categories", "performance", "score"], None)
    return float(score) * 100 if score is not None else None


def get_field_metric(data, metric_key):
    metric = get_nested(data, ["loadingExperience", "metrics", metric_key], None)
    if not metric:
        metric = get_nested(data, ["originLoadingExperience", "metrics", metric_key], None)
    if not metric:
        return None, None
    return metric.get("percentile"), metric.get("category")


async def fetch_pagespeed_async(session, url, strategy="mobile"):
    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
        "key": PAGESPEED_API_KEY,
    }
    async with session.get(PAGESPEED_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=180)) as response:
        if not response.ok:
            text = await response.text()
            print(f"PSI error for {strategy} {url}: {response.status} {text}", flush=True)
            response.raise_for_status()
        return await response.json()


def build_page_record(page_meta, strategy, data):
    lcp_field, lcp_field_category = get_field_metric(data, "LARGEST_CONTENTFUL_PAINT_MS")
    inp_field, inp_field_category = get_field_metric(data, "INTERACTION_TO_NEXT_PAINT")
    cls_field, cls_field_category = get_field_metric(data, "CUMULATIVE_LAYOUT_SHIFT_SCORE")
    fcp_field, fcp_field_category = get_field_metric(data, "FIRST_CONTENTFUL_PAINT_MS")

    return {
        "date": date.today().isoformat(),
        "page": page_meta["page"],
        "category": page_meta["category"],
        "priority": page_meta["priority"],
        "strategy": strategy,
        "performance_score": get_performance_score(data),
        "lcp_lab_ms": get_audit_numeric(data, "largest-contentful-paint"),
        "fcp_lab_ms": get_audit_numeric(data, "first-contentful-paint"),
        "tbt_lab_ms": get_audit_numeric(data, "total-blocking-time"),
        "cls_lab": get_audit_numeric(data, "cumulative-layout-shift"),
        "speed_index_ms": get_audit_numeric(data, "speed-index"),
        "lcp_field_ms": lcp_field,
        "lcp_field_category": lcp_field_category,
        "inp_field_ms": inp_field,
        "inp_field_category": inp_field_category,
        "cls_field": cls_field,
        "cls_field_category": cls_field_category,
        "fcp_field_ms": fcp_field,
        "fcp_field_category": fcp_field_category,
    }


async def process_page_strategy(session, page_meta, strategy):
    try:
        data = await fetch_pagespeed_async(session, page_meta["page"], strategy=strategy)
        print(f"Fetched {strategy} PSI for {page_meta['page']}", flush=True)
        return build_page_record(page_meta, strategy, data)
    except Exception as e:
        print(f"Failed PSI for {strategy} {page_meta['page']}: {e}", flush=True)
        return {
            "date": date.today().isoformat(),
            "page": page_meta["page"],
            "category": page_meta["category"],
            "priority": page_meta["priority"],
            "strategy": strategy,
            "performance_score": None,
            "lcp_lab_ms": None,
            "fcp_lab_ms": None,
            "tbt_lab_ms": None,
            "cls_lab": None,
            "speed_index_ms": None,
            "lcp_field_ms": None,
            "lcp_field_category": None,
            "inp_field_ms": None,
            "inp_field_category": None,
            "cls_field": None,
            "cls_field_category": None,
            "fcp_field_ms": None,
            "fcp_field_category": None,
        }


async def collect_snapshot_async(tracked_df):
    records = []
    conn = aiohttp.TCPConnector(limit=10) # 10 concurrent to respect API limits
    async with aiohttp.ClientSession(connector=conn) as session:
        tasks = []
        for _, row in tracked_df.iterrows():
            page_meta = row.to_dict()
            for strategy in ["mobile", "desktop"]:
                tasks.append(process_page_strategy(session, page_meta, strategy))
        
        results = await asyncio.gather(*tasks)
        records.extend(results)
    return pd.DataFrame(records)


def collect_snapshot(tracked_df):
    return asyncio.run(collect_snapshot_async(tracked_df))


def load_previous_snapshot():
    if os.path.exists(SNAPSHOT_FILE):
        return pd.read_csv(SNAPSHOT_FILE)
    return pd.DataFrame()


def prepare_comparison(current_df, previous_df):
    if previous_df.empty:
        work = current_df.copy()
        work["performance_score_previous"] = None
        work["lcp_lab_ms_previous"] = None
        work["inp_field_ms_previous"] = None
        work["cls_field_previous"] = None
    else:
        previous_small = previous_df[[
            "page", "strategy", "performance_score", "lcp_lab_ms", "inp_field_ms", "cls_field"
        ]].rename(columns={
            "performance_score": "performance_score_previous",
            "lcp_lab_ms": "lcp_lab_ms_previous",
            "inp_field_ms": "inp_field_ms_previous",
            "cls_field": "cls_field_previous",
        })
        work = pd.merge(current_df, previous_small, on=["page", "strategy"], how="left")

    work["performance_score_change"] = work["performance_score"] - work["performance_score_previous"]
    work["lcp_lab_ms_change"] = work["lcp_lab_ms"] - work["lcp_lab_ms_previous"]
    work["inp_field_ms_change"] = work["inp_field_ms"] - work["inp_field_ms_previous"]
    work["cls_field_change"] = work["cls_field"] - work["cls_field_previous"]
    return work




def shorten_url(url, max_len=70):
    text = str(url).replace("https://", "").replace("http://", "")
    return text if len(text) <= max_len else text[:max_len - 3] + "..."


def priority_rank(priority):
    priority = str(priority).lower()
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 9)


# ---------- commentary ----------
def build_executive_read(comparison_df):
    mobile = comparison_df[comparison_df["strategy"] == "mobile"].copy()
    lines = []
    if mobile.empty:
        return ["No mobile site speed data was available."]

    scored_mobile = mobile[pd.notnull(mobile["performance_score"])].copy()
    avg_score = scored_mobile["performance_score"].mean() if not scored_mobile.empty else 0
    poor_lcp = mobile[mobile["lcp_field_category"] == "SLOW"]
    poor_inp = mobile[mobile["inp_field_category"] == "SLOW"]
    poor_cls = mobile[mobile["cls_field_category"] == "SLOW"]

    lines.append(f"Average mobile performance score across tracked pages was {avg_score:.1f}.")
    lines.append(f"{len(poor_lcp)} tracked pages showed poor field LCP.")
    lines.append(f"{len(poor_inp)} tracked pages showed poor field INP.")
    lines.append(f"{len(poor_cls)} tracked pages showed poor field CLS.")

    valid_changes = mobile[pd.notnull(mobile["performance_score_change"])].copy()
    improved = valid_changes[valid_changes["performance_score_change"] > 0].shape[0]
    declined = valid_changes[valid_changes["performance_score_change"] < 0].shape[0]
    if improved > declined:
        lines.append("More pages improved in performance score than declined versus the previous run.")
    elif declined > improved:
        lines.append("More pages declined in performance score than improved versus the previous run.")
    else:
        lines.append("Performance score movement was mixed across the tracked pages.")
    return lines


def build_commentary(comparison_df):
    if not GROQ_API_KEY:
        return (
            "Performance risks remain concentrated in a small set of key pages. "
            "The current review highlights where load speed, layout stability, and interaction responsiveness "
            "are most likely to affect user experience and search visibility."
        )

    mobile = comparison_df[comparison_df["strategy"] == "mobile"].copy()
    top_table = mobile[[
        "page", "category", "priority", "performance_score",
        "performance_score_change", "lcp_lab_ms", "inp_field_ms", "cls_field"
    ]].head(15)

    prompt = f"""
You are writing a concise corporate site speed monitoring summary for SEO stakeholders.

Write:
1. Executive Summary
2. Major Risks
3. Improvement Opportunities
4. Recommended Actions

Requirements:
- professional corporate tone
- under 220 words
- do not invent data
- focus on Core Web Vitals and performance risk
- do not mention AI or automation
- do not use markdown formatting symbols like ** or numbered headings
- use short paragraphs only

Tracked page speed data:
{top_table.to_csv(index=False)}
"""

    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write precise weekly technical SEO summaries."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Executive commentary could not be generated for this run. Error: {str(e)}"


def commentary_to_html(text):
    if not text:
        return '<p>No executive commentary was available for this run.</p>'

    paragraphs = []
    current_list = []

    def flush_list():
        nonlocal current_list
        if current_list:
            paragraphs.append("<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in current_list) + "</ul>")
            current_list = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush_list()
            continue
        line = line.replace("**", "")
        if line[:2].isdigit() and line[1] == ".":
            line = line[2:].strip()
        if line.startswith(("- ", "• ")):
            current_list.append(line[2:].strip())
        else:
            flush_list()
            paragraphs.append(f"<p>{html.escape(line)}</p>")

    flush_list()
    return "".join(paragraphs)





# ---------- charts ----------
def ensure_charts_dir():
    CHARTS_DIR.mkdir(exist_ok=True)


def save_chart(fig, filename):
    path = CHARTS_DIR / filename
    fig.savefig(path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def build_charts(comparison_df):
    ensure_charts_dir()
    charts = {}

    mobile = comparison_df[(comparison_df["strategy"] == "mobile") & pd.notnull(comparison_df["performance_score"])].copy()
    desktop = comparison_df[(comparison_df["strategy"] == "desktop") & pd.notnull(comparison_df["performance_score"])].copy()

    fig, ax = plt.subplots(figsize=(11.2, 4.8))
    categories = ["Avg Score", "Poor LCP", "Poor INP", "Poor CLS"]
    mobile_vals = [
        mobile["performance_score"].mean() if not mobile.empty else 0,
        (mobile["lcp_field_category"] == "SLOW").sum(),
        (mobile["inp_field_category"] == "SLOW").sum(),
        (mobile["cls_field_category"] == "SLOW").sum(),
    ]
    desktop_vals = [
        desktop["performance_score"].mean() if not desktop.empty else 0,
        (desktop["lcp_field_category"] == "SLOW").sum(),
        (desktop["inp_field_category"] == "SLOW").sum(),
        (desktop["cls_field_category"] == "SLOW").sum(),
    ]
    x = range(len(categories))
    width = 0.34
    ax.bar([i - width / 2 for i in x], mobile_vals, width=width, label="Mobile", color="#2563eb")
    ax.bar([i + width / 2 for i in x], desktop_vals, width=width, label="Desktop", color="#14b8a6")
    ax.set_xticks(list(x))
    ax.set_xticklabels(categories)
    ax.set_title("Mobile vs Desktop Site Speed Snapshot", fontsize=14, pad=14)
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.legend(frameon=False)
    charts["overview"] = save_chart(fig, "overview.png")

    mobile_top = mobile.sort_values(by="performance_score", ascending=False).head(10).copy()
    fig, ax = plt.subplots(figsize=(11.2, 5.2))
    ax.barh([shorten_url(u, 42) for u in mobile_top["page"]], mobile_top["performance_score"], color="#2563eb")
    ax.set_title("Top Mobile Performance Scores", fontsize=14, pad=14)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.invert_yaxis()
    charts["top_mobile"] = save_chart(fig, "top_mobile_scores.png")

    worst_lcp = mobile.sort_values(by="lcp_lab_ms", ascending=False).head(10).copy()
    fig, ax = plt.subplots(figsize=(11.2, 5.2))
    ax.barh([shorten_url(u, 42) for u in worst_lcp["page"]], worst_lcp["lcp_lab_ms"], color="#dc2626")
    ax.set_title("Highest Mobile LCP Pages", fontsize=14, pad=14)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.invert_yaxis()
    charts["worst_lcp"] = save_chart(fig, "highest_mobile_lcp.png")

    score_change = mobile[pd.notnull(mobile["performance_score_change"])].copy()
    if not score_change.empty and score_change["performance_score_change"].abs().sum() > 0:
        score_change = score_change.sort_values(by="performance_score_change", ascending=False).head(12)
        fig, ax = plt.subplots(figsize=(11.2, 5.2))
        colors = ["#14b8a6" if x >= 0 else "#f97316" for x in score_change["performance_score_change"]]
        ax.barh([shorten_url(u, 42) for u in score_change["page"]], score_change["performance_score_change"], color=colors)
        ax.set_title("Mobile Score Winners and Losers", fontsize=14, pad=14)
        ax.axvline(0, color="#475569", linewidth=1)
        ax.grid(axis="x", linestyle="--", alpha=0.25)
        ax.invert_yaxis()
        charts["score_change"] = save_chart(fig, "score_change.png")
    else:
        charts["score_change"] = None

    return charts


def img_tag(path, alt):
    if not path:
        return '<div class="empty-state">Not enough prior-run baseline data was available for this chart.</div>'
    return f'<img src="{path.as_posix()}" alt="{html.escape(alt)}" style="width:100%; display:block; border-radius:16px;">'


# ---------- report ----------
def write_html_summary(comparison_df, commentary):
    clean   = comparison_df[pd.notnull(comparison_df["performance_score"])].copy()
    mobile  = clean[clean["strategy"] == "mobile"].copy()
    desktop = clean[clean["strategy"] == "desktop"].copy()
    mobile["priority_rank"]  = mobile["priority"].map(priority_rank)
    desktop["priority_rank"] = desktop["priority"].map(priority_rank)
    mobile  = mobile.sort_values(["priority_rank","performance_score"], ascending=[True,False]).drop(columns=["priority_rank"])
    desktop = desktop.sort_values(["priority_rank","performance_score"], ascending=[True,False]).drop(columns=["priority_rank"])

    executive_read = build_executive_read(comparison_df)
    charts         = build_charts(comparison_df)
    commentary_html = mm_ai_block(commentary)

    mobile_main    = mobile.head(10).copy()
    desktop_main   = desktop.head(10).copy()
    appendix_mobile  = mobile.iloc[10:].copy()
    appendix_desktop = desktop.iloc[10:].copy()

    mobile_cols   = ["page","category","priority","performance_score","performance_score_change","lcp_field_ms","inp_field_ms","cls_field"]
    mobile_rename = {"page":"Page","category":"Category","priority":"Priority","performance_score":"Score","performance_score_change":"Score Δ","lcp_field_ms":"LCP (ms)","inp_field_ms":"INP (ms)","cls_field":"CLS"}
    desktop_cols  = ["page","category","priority","performance_score","performance_score_change","lcp_lab_ms","tbt_lab_ms","cls_lab"]
    desktop_rename= {"page":"Page","category":"Category","priority":"Priority","performance_score":"Score","performance_score_change":"Score Δ","lcp_lab_ms":"LCP Lab (ms)","tbt_lab_ms":"TBT Lab (ms)","cls_lab":"CLS Lab"}

    def tbl(df, cols, rename):
        return html_table_from_df(df, cols, rename) if not df.empty else "<p>No data.</p>"

    def chart_img(path, alt):
        if not path:
            return '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">No baseline data available for this chart.</p>'
        return mm_chart_wrap(path, alt)

    kpi_grid = mm_kpi_grid(
        mm_kpi_card("Tracked URLs",      comparison_df['page'].nunique(), None),
        mm_kpi_card("Mobile Avg Score",  mobile['performance_score'].mean() if not mobile.empty else 0, None, decimals=1),
        mm_kpi_card("Desktop Avg Score", desktop['performance_score'].mean() if not desktop.empty else 0, None, decimals=1),
        mm_kpi_card("Poor Mobile LCP",   int((mobile['lcp_field_category'] == 'SLOW').sum()) if not mobile.empty else 0, None),
    )

    body = (
        mm_section("Executive Overview",
            mm_report_section(mm_exec_bullets(executive_read) + commentary_html)
        ) +
        f'<div class="section" style="padding-top:0;">{kpi_grid}</div>'
        '<hr class="rule-thick">' +
        mm_section("Performance Overview",
            mm_report_section(chart_img(charts['overview'], 'Site speed overview'))
        ) +
        mm_section("Top Mobile Performance Scores",
            mm_report_section(chart_img(charts['top_mobile'], 'Top mobile scores'))
        ) +
        mm_section("Highest Mobile LCP Pages",
            mm_report_section(chart_img(charts['worst_lcp'], 'Highest mobile LCP'))
        ) +
        mm_section("Mobile Score Movement",
            mm_report_section(chart_img(charts.get('score_change'), 'Mobile score winners and losers'))
        ) +
        mm_section("Mobile Results",
            mm_report_section(tbl(mobile_main, mobile_cols, mobile_rename))
        ) +
        mm_section("Desktop Results",
            mm_report_section(tbl(desktop_main, desktop_cols, desktop_rename))
        ) +
        mm_section("Appendix — Additional Mobile Rows",
            mm_report_section(tbl(appendix_mobile, mobile_cols, mobile_rename))
        ) +
        mm_section("Appendix — Additional Desktop Rows",
            mm_report_section(tbl(appendix_desktop, desktop_cols, desktop_rename))
        )
    )

    doc = mm_html_shell(
        title="Site Speed Monitoring",
        eyebrow="CIM SEO — Core Web Vitals",
        headline="Site Speed\nMonitoring",
        meta_line=f"Generated {date.today().isoformat()}",
        body_content=body,
    )
    with open("site_speed_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("Saved site_speed_summary.html")


def generate_self_contained():
    generate_self_contained_html("site_speed_summary.html", "site_speed_summary_final.html")


def upload_to_monday():
    upload_html_to_monday(
        "site_speed_summary_final.html",
        "site-speed-monitoring.html",
        body_text="Site Speed Monitoring Report attached as self-contained HTML.",
    )


def persist_snapshots(current_df):
    current_df.to_csv(SNAPSHOT_FILE, index=False)
    if os.path.exists(HISTORY_FILE):
        history_df = pd.read_csv(HISTORY_FILE)
        history_df = pd.concat([history_df, current_df], ignore_index=True)
    else:
        history_df = current_df.copy()
    history_df.to_csv(HISTORY_FILE, index=False)


def main():
    tracked_df = load_tracked_pages()
    current_df = collect_snapshot(tracked_df)
    previous_df = load_previous_snapshot()
    comparison_df = prepare_comparison(current_df, previous_df)

    current_df.to_csv("site_speed_current_snapshot.csv", index=False)
    comparison_df.to_csv("site_speed_comparison.csv", index=False)

    append_to_sheet(current_df, "Site_Speed_Snapshot")
    append_to_sheet(comparison_df, "Site_Speed_Comparison")

    commentary = build_commentary(comparison_df)
    write_html_summary(comparison_df, commentary)
    generate_self_contained()
    persist_snapshots(current_df)

    try:
        upload_to_monday()
    except Exception as e:
        print(f"monday upload step failed: {e}")

    print("Saved site speed outputs.")


if __name__ == "__main__":
    main()
