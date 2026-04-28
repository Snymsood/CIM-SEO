from datetime import date
from openai import OpenAI
from weasyprint import HTML
import pandas as pd
import requests
import os
import html
import json
import matplotlib
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


def fetch_pagespeed(url, strategy="mobile"):
    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
        "key": PAGESPEED_API_KEY,
    }
    response = requests.get(PAGESPEED_API_URL, params=params, timeout=180)
    if not response.ok:
        print(f"PSI error for {strategy} {url}: {response.status_code} {response.text}", flush=True)
    response.raise_for_status()
    return response.json()


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


def collect_snapshot(tracked_df):
    records = []
    for _, row in tracked_df.iterrows():
        page_meta = row.to_dict()
        for strategy in ["mobile", "desktop"]:
            try:
                data = fetch_pagespeed(page_meta["page"], strategy=strategy)
                records.append(build_page_record(page_meta, strategy, data))
                print(f"Fetched {strategy} PSI for {page_meta['page']}", flush=True)
            except Exception as e:
                print(f"Failed PSI for {strategy} {page_meta['page']}: {e}", flush=True)
                records.append({
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
                })
    return pd.DataFrame(records)


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


# ---------- formatting ----------
def format_num(value, decimals=0):
    if pd.isna(value):
        return ""
    return f"{value:.{decimals}f}"


def format_delta(value, decimals=0):
    if pd.isna(value):
        return ""
    if value > 0:
        return f"+{value:.{decimals}f}"
    return f"{value:.{decimals}f}"


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


# ---------- tables ----------
def html_table_from_df(df, columns, rename_map=None):
    if df.empty:
        return '<div class="empty-state">No rows were available for this section.</div>'

    work = df[columns].copy()
    if rename_map:
        work = work.rename(columns=rename_map)

    for col in work.columns:
        lower = col.lower()
        if "score" in lower:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_num(x, 1))
        elif "change" in lower:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_delta(x, 1))
        elif any(token in lower for token in ["lcp", "fcp", "inp", "tbt", "speed_index"]):
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_num(x, 0))
        elif "cls" in lower:
            work[col] = pd.to_numeric(work[col], errors="coerce").map(lambda x: format_num(x, 3))
        else:
            work[col] = work[col].fillna("").astype(str)

    header_html = "".join(f"<th>{html.escape(str(col))}</th>" for col in work.columns)
    body_rows = []
    for row in work.values.tolist():
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in row)
        body_rows.append(f"<tr>{cells}</tr>")

    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


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
    clean = comparison_df[pd.notnull(comparison_df["performance_score"])].copy()
    mobile = clean[clean["strategy"] == "mobile"].copy()
    desktop = clean[clean["strategy"] == "desktop"].copy()
    mobile["priority_rank"] = mobile["priority"].map(priority_rank)
    desktop["priority_rank"] = desktop["priority"].map(priority_rank)
    mobile = mobile.sort_values(by=["priority_rank", "performance_score"], ascending=[True, False]).drop(columns=["priority_rank"]) 
    desktop = desktop.sort_values(by=["priority_rank", "performance_score"], ascending=[True, False]).drop(columns=["priority_rank"]) 

    executive_read = build_executive_read(comparison_df)
    charts = build_charts(comparison_df)
    commentary_html = commentary_to_html(commentary)

    # Keep main body concise for PDF readability
    mobile_main = mobile.head(10).copy()
    desktop_main = desktop.head(10).copy()
    appendix_mobile = mobile.iloc[10:].copy()
    appendix_desktop = desktop.iloc[10:].copy()

    def card(title, value, sub, tone="blue"):
        tone_map = {
            "blue": ("#dbeafe", "#1d4ed8"),
            "teal": ("#ccfbf1", "#0f766e"),
            "gold": ("#fef3c7", "#b45309"),
            "rose": ("#ffe4e6", "#be123c"),
        }
        bg, accent = tone_map[tone]
        return f'''
        <div class="card" style="background:{bg}; border-top:6px solid {accent};">
            <div class="label">{html.escape(title)}</div>
            <div class="value">{html.escape(value)}</div>
            <div class="sub">{html.escape(sub)}</div>
        </div>
        '''

    mobile_cols = ["page", "category", "priority", "performance_score", "performance_score_change", "lcp_lab_ms", "inp_field_ms", "cls_field"]
    mobile_rename = {"page": "Page", "category": "Category", "priority": "Priority", "performance_score": "Score", "performance_score_change": "Score Δ", "lcp_lab_ms": "LCP Lab (ms)", "inp_field_ms": "INP Field (ms)", "cls_field": "CLS Field"}

    desktop_cols = ["page", "category", "priority", "performance_score", "performance_score_change", "lcp_lab_ms", "tbt_lab_ms", "cls_lab"]
    desktop_rename = {"page": "Page", "category": "Category", "priority": "Priority", "performance_score": "Score", "performance_score_change": "Score Δ", "lcp_lab_ms": "LCP Lab (ms)", "tbt_lab_ms": "TBT Lab (ms)", "cls_lab": "CLS Lab"}

    app_mobile_cols = ["page", "category", "priority", "performance_score", "lcp_lab_ms", "inp_field_ms", "cls_field"]
    app_mobile_rename = {"page": "Page", "category": "Category", "priority": "Priority", "performance_score": "Score", "lcp_lab_ms": "LCP Lab (ms)", "inp_field_ms": "INP Field (ms)", "cls_field": "CLS Field"}

    app_desktop_cols = ["page", "category", "priority", "performance_score", "lcp_lab_ms", "tbt_lab_ms", "cls_lab"]
    app_desktop_rename = {"page": "Page", "category": "Category", "priority": "Priority", "performance_score": "Score", "lcp_lab_ms": "LCP Lab (ms)", "tbt_lab_ms": "TBT Lab (ms)", "cls_lab": "CLS Lab"}

    html_output = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Site Speed Monitoring</title>
<style>
@page {{
    size: A4;
    margin: 0.55in;
}}
body {{ font-family: 'Times New Roman', Times, serif; margin: 0; padding: 0; background: #eef2ff; color: #1f2937; }}
.page {{ padding: 0; }}
.container {{ max-width: 1180px; margin: 0 auto; }}
.hero {{ background: linear-gradient(135deg, #1d4ed8 0%, #0f766e 100%); color: white; border-radius: 24px; padding: 32px 34px; margin-bottom: 26px; }}
.hero h1 {{ margin: 0 0 8px 0; font-size: 34px; }}
.hero p {{ margin: 0; font-size: 16px; line-height: 1.6; }}
h2 {{ margin: 0 0 14px 0; font-size: 24px; color: #0f172a; }}
.section {{ background: #ffffff; border-radius: 22px; padding: 26px 28px; margin-bottom: 24px; box-shadow: 0 10px 28px rgba(15, 23, 42, 0.07); page-break-inside: avoid; }}
.grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:18px; margin-top: 18px; margin-bottom: 8px; }}
.card {{ border-radius: 18px; padding: 18px 18px 20px 18px; min-height: 116px; }}
.label {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: #475569; margin-bottom: 10px; }}
.value {{ font-size: 30px; font-weight: 700; color: #0f172a; margin-bottom: 8px; }}
.sub {{ font-size: 14px; color: #334155; line-height: 1.5; }}
.two-col {{ display:grid; grid-template-columns: 0.95fr 1.05fr; gap: 22px; align-items: start; }}
ul {{ margin: 0; padding-left: 22px; line-height: 1.8; }}
.commentary {{ line-height: 1.75; font-size: 15px; color:#1e293b; background: #eff6ff; border-left: 6px solid #2563eb; border-radius: 16px; padding: 18px 20px; }}
.commentary p {{ margin: 0 0 12px 0; }}
.commentary p:last-child {{ margin-bottom: 0; }}
.commentary ul {{ margin: 8px 0 0 0; }}
.chart-panel {{ background: #f8fafc; border: 1px solid #dbe4f0; border-radius: 18px; padding: 16px; margin-top: 16px; page-break-inside: avoid; }}
.chart-row {{ margin-bottom: 22px; }}
table {{ width:100%; border-collapse:collapse; background:white; border-radius:18px; overflow:hidden; margin-top: 12px; table-layout: fixed; }}
th, td {{ text-align:left; padding:14px 12px; border-bottom:1px solid #e2e8f0; vertical-align:top; word-break:break-word; font-size: 13px; }}
th {{ background:#1e3a8a; color:white; font-size:12px; letter-spacing:0.05em; text-transform:uppercase; }}
tr:nth-child(even) td {{ background:#f8fafc; }}
thead {{ display: table-header-group; }}
tr {{ page-break-inside: avoid; }}
.footer-note {{ color:#64748b; font-size:12px; text-align:right; margin-top: 10px; }}
.empty-state {{ color:#64748b; font-style: italic; padding: 10px 0; }}
.page-break {{ page-break-before: always; }}
</style>
</head>
<body>
<div class="page">
<div class="container">
    <div class="hero">
        <h1>Site Speed Monitoring</h1>
        <p>Weekly technical performance review across tracked priority pages and subdomains.</p>
        <p>Prepared for stakeholder review • Generated {date.today().isoformat()}</p>
    </div>

    <div class="section">
        <div class="two-col">
            <div>
                <h2>Executive Overview</h2>
                <ul>{''.join(f'<li>{html.escape(line)}</li>' for line in executive_read)}</ul>
            </div>
            <div>
                <h2>Executive Commentary</h2>
                <div class="commentary">{commentary_html}</div>
            </div>
        </div>
        <div class="grid">
            {card("Tracked URLs", str(comparison_df['page'].nunique()), "mobile and desktop measurements collected", "blue")}
            {card("Mobile Avg Score", format_num(mobile['performance_score'].mean(), 1), "PageSpeed performance benchmark", "teal")}
            {card("Desktop Avg Score", format_num(desktop['performance_score'].mean(), 1), "PageSpeed performance benchmark", "gold")}
            {card("Poor Mobile LCP", str((mobile['lcp_field_category'] == 'SLOW').sum()), "pages with slow field LCP", "rose")}
        </div>
    </div>

    <div class="section">
        <h2>Performance Overview</h2>
        <div class="chart-row chart-panel">{img_tag(charts['overview'], 'Site speed overview')}</div>
    </div>

    <div class="section">
        <h2>Top Mobile Performance Scores</h2>
        <div class="chart-row chart-panel">{img_tag(charts['top_mobile'], 'Top mobile scores')}</div>
    </div>

    <div class="section">
        <h2>Highest Mobile LCP Pages</h2>
        <div class="chart-row chart-panel">{img_tag(charts['worst_lcp'], 'Highest mobile LCP')}</div>
    </div>

    <div class="section">
        <h2>Mobile Score Movement</h2>
        <div class="chart-row chart-panel">{img_tag(charts['score_change'], 'Mobile score winners and losers')}</div>
    </div>

    <div class="section page-break">
        <h2>Mobile Results</h2>
        {html_table_from_df(mobile_main, mobile_cols, mobile_rename)}
    </div>

    <div class="section">
        <h2>Desktop Results</h2>
        {html_table_from_df(desktop_main, desktop_cols, desktop_rename)}
    </div>

    <div class="section">
        <h2>Appendix</h2>
        <h3>Additional Mobile Rows</h3>
        {html_table_from_df(appendix_mobile, app_mobile_cols, app_mobile_rename)}
        <h3 style="margin-top:24px;">Additional Desktop Rows</h3>
        {html_table_from_df(appendix_desktop, app_desktop_cols, app_desktop_rename)}
        <div class="footer-note">Prepared for internal weekly monitoring.</div>
    </div>
</div>
</div>
</body>
</html>
"""
    with open("site_speed_summary.html", "w", encoding="utf-8") as f:
        f.write(html_output)


def generate_pdf():
    HTML("site_speed_summary.html").write_pdf("site_speed_summary.pdf")
    print("Saved site_speed_summary.pdf")


def persist_snapshots(current_df):
    current_df.to_csv(SNAPSHOT_FILE, index=False)
    if os.path.exists(HISTORY_FILE):
        history_df = pd.read_csv(HISTORY_FILE)
        history_df = pd.concat([history_df, current_df], ignore_index=True)
    else:
        history_df = current_df.copy()
    history_df.to_csv(HISTORY_FILE, index=False)


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
        "body": "Site speed PDF report attached.",
    }

    update_response = requests.post(
        MONDAY_API_URL,
        headers={"Authorization": MONDAY_API_TOKEN, "Content-Type": "application/json"},
        json={"query": update_query, "variables": update_variables},
        timeout=60,
    )
    update_response.raise_for_status()
    update_id = update_response.json()["data"]["create_update"]["id"]

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
            files={"pdf": ("site-speed-monitoring.pdf", f, "application/pdf")},
            timeout=120,
        )

    print("monday file upload status:", response.status_code)
    print("monday file upload response:", response.text)
    response.raise_for_status()
    print("Uploaded PDF to monday update.")


def main():
    tracked_df = load_tracked_pages()
    current_df = collect_snapshot(tracked_df)
    previous_df = load_previous_snapshot()
    comparison_df = prepare_comparison(current_df, previous_df)

    current_df.to_csv("site_speed_current_snapshot.csv", index=False)
    comparison_df.to_csv("site_speed_comparison.csv", index=False)

    commentary = build_commentary(comparison_df)
    write_html_summary(comparison_df, commentary)
    generate_pdf()
    persist_snapshots(current_df)

    try:
        upload_pdf_to_monday("site_speed_summary.pdf")
    except Exception as e:
        print(f"monday upload step failed: {e}")

    print("Saved site speed outputs.")


if __name__ == "__main__":
    main()
