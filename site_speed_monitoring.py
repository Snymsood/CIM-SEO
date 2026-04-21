from datetime import date
from openai import OpenAI
from weasyprint import HTML
import pandas as pd
import requests
import os
import html
import json

PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")

TRACKED_PAGES_FILE = "tracked_speed_pages.csv"
SNAPSHOT_FILE = "site_speed_latest_snapshot.csv"
HISTORY_FILE = "site_speed_history.csv"

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"
PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


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
    value = get_nested(
        data,
        ["lighthouseResult", "audits", audit_key, "numericValue"],
        None
    )
    return float(value) if value is not None else None


def get_performance_score(data):
    score = get_nested(
        data,
        ["lighthouseResult", "categories", "performance", "score"],
        None
    )
    return float(score) * 100 if score is not None else None


def get_field_metric(data, metric_key):
    metric = get_nested(
        data,
        ["loadingExperience", "metrics", metric_key],
        None
    )
    if not metric:
        metric = get_nested(
            data,
            ["originLoadingExperience", "metrics", metric_key],
            None
        )

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

        work = pd.merge(
            current_df,
            previous_small,
            on=["page", "strategy"],
            how="left"
        )

    work["performance_score_change"] = work["performance_score"] - work["performance_score_previous"]
    work["lcp_lab_ms_change"] = work["lcp_lab_ms"] - work["lcp_lab_ms_previous"]
    work["inp_field_ms_change"] = work["inp_field_ms"] - work["inp_field_ms_previous"]
    work["cls_field_change"] = work["cls_field"] - work["cls_field_previous"]

    return work


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


def build_executive_read(comparison_df):
    mobile = comparison_df[comparison_df["strategy"] == "mobile"].copy()

    lines = []
    if mobile.empty:
        return ["No mobile PageSpeed data was available."]

    avg_score = mobile["performance_score"].mean()
    poor_lcp = mobile[mobile["lcp_field_category"] == "SLOW"]
    poor_inp = mobile[mobile["inp_field_category"] == "SLOW"]
    poor_cls = mobile[mobile["cls_field_category"] == "SLOW"]

    lines.append(f"Average mobile performance score across tracked pages was {avg_score:.1f}.")
    lines.append(f"{len(poor_lcp)} tracked pages showed poor field LCP.")
    lines.append(f"{len(poor_inp)} tracked pages showed poor field INP.")
    lines.append(f"{len(poor_cls)} tracked pages showed poor field CLS.")

    improved = mobile[mobile["performance_score_change"] > 0].shape[0]
    declined = mobile[mobile["performance_score_change"] < 0].shape[0]

    if improved > declined:
        lines.append("More pages improved in performance score than declined versus the previous run.")
    elif declined > improved:
        lines.append("More pages declined in performance score than improved versus the previous run.")
    else:
        lines.append("Performance score movement was mixed across the tracked pages.")

    return lines


def build_ai_analysis(comparison_df):
    if not GROQ_API_KEY:
        return "AI executive analysis was skipped because GROQ_API_KEY is not configured."

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
- under 300 words
- do not invent data
- focus on Core Web Vitals and performance risk

Tracked page speed data:
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
                {"role": "system", "content": "You write precise weekly technical SEO summaries."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI executive analysis failed, so the report fell back to deterministic output only. Error: {str(e)}"


def html_table_from_df(df, columns, rename_map=None):
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


def write_html_summary(comparison_df, ai_analysis):
    mobile = comparison_df[comparison_df["strategy"] == "mobile"].sort_values(
        by=["priority", "performance_score"],
        ascending=[True, False]
    )
    desktop = comparison_df[comparison_df["strategy"] == "desktop"].sort_values(
        by=["priority", "performance_score"],
        ascending=[True, False]
    )

    executive_read = build_executive_read(comparison_df)

    def card(title, value, sub):
        return f'''
        <div class="card">
            <div class="label">{html.escape(title)}</div>
            <div class="value">{html.escape(value)}</div>
            <div class="sub">{html.escape(sub)}</div>
        </div>
        '''

    html_output = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Site Speed Monitoring</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 0; padding: 32px; background: #f5f7fb; color: #1f2937; }}
.container {{ max-width: 1200px; margin: 0 auto; }}
h2 {{ margin-top: 32px; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
.grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin:20px 0 28px 0; }}
.card, .panel {{ background:white; border-radius:12px; padding:18px; box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
.panel {{ margin-bottom:20px; }}
.label {{ font-size:12px; text-transform:uppercase; color:#6b7280; margin-bottom:10px; }}
.value {{ font-size:28px; font-weight:700; margin-bottom:6px; }}
.sub {{ font-size:13px; color:#6b7280; }}
table {{ width:100%; border-collapse:collapse; background:white; border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08); margin-bottom:24px; }}
th, td {{ text-align:left; padding:12px 14px; border-bottom:1px solid #e5e7eb; vertical-align:top; word-break:break-word; }}
th {{ background:#111827; color:white; font-size:13px; }}
tr:nth-child(even) td {{ background:#f9fafb; }}
.ai-block {{ white-space:pre-wrap; line-height:1.5; }}
</style>
</head>
<body>
<div class="container">
<h1>Site Speed Monitoring</h1>

<div class="panel">
<h2>Executive Read</h2>
<ul>{''.join(f"<li>{html.escape(line)}</li>" for line in executive_read)}</ul>
</div>

<div class="panel">
<h2>AI Executive Analysis</h2>
<div class="ai-block">{html.escape(ai_analysis)}</div>
</div>

<div class="grid">
{card("Tracked URLs", str(comparison_df['page'].nunique()), "mobile + desktop tested")}
{card("Mobile Avg Score", format_num(mobile['performance_score'].mean(), 1), "PageSpeed performance")}
{card("Desktop Avg Score", format_num(desktop['performance_score'].mean(), 1), "PageSpeed performance")}
{card("Poor Mobile LCP", str((mobile['lcp_field_category'] == 'SLOW').sum()), "field data pages")}
</div>

<h2>Mobile Results</h2>
{html_table_from_df(
    mobile,
    ["page", "category", "priority", "performance_score", "performance_score_change", "lcp_lab_ms", "inp_field_ms", "cls_field"],
    {
        "page": "Page",
        "category": "Category",
        "priority": "Priority",
        "performance_score": "Score",
        "performance_score_change": "Score Δ",
        "lcp_lab_ms": "LCP Lab (ms)",
        "inp_field_ms": "INP Field (ms)",
        "cls_field": "CLS Field",
    }
)}

<h2>Desktop Results</h2>
{html_table_from_df(
    desktop,
    ["page", "category", "priority", "performance_score", "performance_score_change", "lcp_lab_ms", "tbt_lab_ms", "cls_lab"],
    {
        "page": "Page",
        "category": "Category",
        "priority": "Priority",
        "performance_score": "Score",
        "performance_score_change": "Score Δ",
        "lcp_lab_ms": "LCP Lab (ms)",
        "tbt_lab_ms": "TBT Lab (ms)",
        "cls_lab": "CLS Lab",
    }
)}
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

    ai_analysis = build_ai_analysis(comparison_df)
    write_html_summary(comparison_df, ai_analysis)
    generate_pdf()
    persist_snapshots(current_df)

    try:
        upload_pdf_to_monday("site_speed_summary.pdf")
    except Exception as e:
        print(f"monday upload step failed: {e}")

    print("Saved site speed outputs.")


if __name__ == "__main__":
    main()
