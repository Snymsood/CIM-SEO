from datetime import date, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import OpenAI
from weasyprint import HTML
import matplotlib.pyplot as plt
import pandas as pd
import requests
import os
import html
import json
import math

from pdf_report_formatter import get_pdf_css, html_table_from_df, build_card

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
KEY_FILE = "gsc-key.json"
SITE_URL = os.environ["GSC_PROPERTY"]

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"
CONFIG_FILE = "content_audit_config.csv"


def get_service():
    credentials = service_account.Credentials.from_service_account_file(
        KEY_FILE,
        scopes=SCOPES,
    )
    return build("searchconsole", "v1", credentials=credentials)


def load_config():
    df = pd.read_csv(CONFIG_FILE)
    df["rule_type"] = df["rule_type"].astype(str).str.strip()
    df["value"] = df["value"].astype(str).str.strip()
    df["notes"] = df["notes"].fillna("").astype(str).str.strip()
    return df


def get_config_values(config_df, rule_type):
    return config_df.loc[config_df["rule_type"] == rule_type, "value"].tolist()


def get_config_number(config_df, rule_type, default_value):
    values = get_config_values(config_df, rule_type)
    if not values:
        return default_value
    try:
        return float(values[0])
    except Exception:
        return default_value


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
            "clicks": float(row.get("clicks", 0)),
            "impressions": float(row.get("impressions", 0)),
            "ctr": float(row.get("ctr", 0)),
            "position": float(row.get("position", 0)),
        })

    if not data:
        return pd.DataFrame(columns=["page", "clicks", "impressions", "ctr", "position"])

    return pd.DataFrame(data)


def normalize_page_groups(df):
    if df.empty:
        return df.copy()

    work = df.copy()
    work["page"] = work["page"].astype(str).str.strip()
    return work.groupby("page", as_index=False).agg({
        "clicks": "sum",
        "impressions": "sum",
        "ctr": "mean",
        "position": "mean",
    })


def apply_page_rules(df, config_df):
    if df.empty:
        return df.copy()

    include_prefixes = get_config_values(config_df, "include_prefix")
    exclude_prefixes = get_config_values(config_df, "exclude_prefix")
    exclude_contains = get_config_values(config_df, "exclude_contains")

    work = df.copy()
    work["is_included"] = True

    if include_prefixes:
        include_mask = pd.Series(False, index=work.index)
        for prefix in include_prefixes:
            include_mask = include_mask | work["page"].str.startswith(prefix, na=False)
        work["is_included"] = include_mask

    for prefix in exclude_prefixes:
        work.loc[work["page"].str.startswith(prefix, na=False), "is_included"] = False

    for fragment in exclude_contains:
        work.loc[work["page"].str.contains(fragment, case=False, na=False, regex=False), "is_included"] = False

    return work[work["is_included"]].drop(columns=["is_included"])


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

    merged = pd.merge(current_df, previous_df, on="page", how="outer").fillna(0)

    merged["clicks_change"] = merged["clicks_current"] - merged["clicks_previous"]
    merged["impressions_change"] = merged["impressions_current"] - merged["impressions_previous"]
    merged["ctr_change"] = merged["ctr_current"] - merged["ctr_previous"]
    merged["position_change"] = merged["position_current"] - merged["position_previous"]

    return merged




def clamp_0_100(value):
    return max(0, min(100, value))


def score_candidates(comparison_df, config_df):
    if comparison_df.empty:
        return comparison_df.copy()

    min_impressions = get_config_number(config_df, "min_impressions", 50)
    max_clicks_low = get_config_number(config_df, "max_clicks_for_low_performance", 25)
    min_position_low = get_config_number(config_df, "min_position_for_low_performance", 8)

    work = comparison_df.copy()
    work = work[work["impressions_current"] >= min_impressions].copy()

    if work.empty:
        return work

    work["clicks_score"] = work["clicks_current"].map(
        lambda x: clamp_0_100((1 - min(x / max_clicks_low, 1)) * 100 if max_clicks_low > 0 else 0)
    )
    work["position_score"] = work["position_current"].map(
        lambda x: clamp_0_100(min(((x - min_position_low) / 10) * 100, 100) if x > 0 else 0)
    )
    work["ctr_score"] = work["ctr_current"].map(
        lambda x: clamp_0_100((1 - min(x / 0.03, 1)) * 100)
    )
    work["traffic_decline_score"] = work.apply(
        lambda row: clamp_0_100(abs(safe_pct_change(row["clicks_current"], row["clicks_previous"])) or 0)
        if row["clicks_current"] < row["clicks_previous"] else 0,
        axis=1,
    )

    work["low_performance_score"] = (
        work["clicks_score"] * 0.35 +
        work["position_score"] * 0.30 +
        work["ctr_score"] * 0.20 +
        work["traffic_decline_score"] * 0.15
    ).round(1)

    work["recommended_action"] = work.apply(classify_action, axis=1)
    work["reason"] = work.apply(build_reason, axis=1)

    return work.sort_values(
        by=["low_performance_score", "impressions_current"],
        ascending=[False, False]
    )


def classify_action(row):
    clicks = row["clicks_current"]
    impressions = row["impressions_current"]
    ctr = row["ctr_current"]
    position = row["position_current"]

    if impressions >= 100 and (position >= 8 or ctr < 0.02):
        return "Refresh"

    if impressions < 150 and clicks < 10 and ctr < 0.02:
        return "Archive"

    if clicks < 15 and position >= 10:
        return "Archive"

    return "Refresh"


def build_reason(row):
    reasons = []

    if row["position_current"] >= 8:
        reasons.append("weak average ranking position")
    if row["ctr_current"] < 0.02:
        reasons.append("low click-through rate")
    if row["clicks_current"] < 10:
        reasons.append("low click volume")
    if row["clicks_current"] < row["clicks_previous"]:
        reasons.append("traffic declined versus prior period")

    if not reasons:
        reasons.append("underperforming relative to thresholds")

    return "; ".join(reasons)


def choose_monthly_candidate(scored_df, config_df):
    selection_count = int(get_config_number(config_df, "monthly_selection_count", 1))
    if scored_df.empty:
        return pd.DataFrame(), scored_df

    selected = scored_df.head(selection_count).copy()
    return selected, scored_df


def build_executive_commentary(selected_df, scored_df, current_start, current_end, previous_start, previous_end):
    if selected_df.empty:
        return [
            "No eligible low-performance page met the configured monthly audit thresholds.",
            "The current rules may be too restrictive or the evaluated page set may be too small."
        ]

    selected = selected_df.iloc[0]
    action = selected["recommended_action"]
    page = selected["page"]

    lines = [
        f"This month's audit recommendation identifies one low-performance page for {action.lower()}.",
        f"The selected page is {page}.",
        f"It recorded {selected['clicks_current']:.0f} clicks and {selected['impressions_current']:.0f} impressions during {current_start} to {current_end}.",
        f"The page's average position was {selected['position_current']:.2f} with a CTR of {selected['ctr_current']:.2%}.",
        f"Primary rationale: {selected['reason']}."
    ]

    if not scored_df.empty:
        lines.append(f"{len(scored_df)} pages met the evaluation criteria for this monthly review.")

    return lines


def build_executive_analysis(selected_df, scored_df, current_start, current_end, previous_start, previous_end):
    if selected_df.empty:
        return "No page qualified for a monthly refresh-or-archive recommendation under the current audit rules."

    if not GROQ_API_KEY:
        return (
            "This month's recommendation highlights one low-performance page based on "
            "visibility, click volume, click-through rate, ranking position, and period-over-period movement."
        )

    selected = selected_df[[
        "page", "recommended_action", "low_performance_score", "clicks_current",
        "impressions_current", "ctr_current", "position_current", "reason"
    ]]

    comparison_sample = scored_df.head(10)[[
        "page", "recommended_action", "low_performance_score", "clicks_current",
        "impressions_current", "ctr_current", "position_current"
    ]]

    prompt = f"""
You are preparing a concise corporate content audit summary.

Write:
1. Executive Summary
2. Why This Page Was Selected
3. Recommended Next Step
4. Editorial Considerations

Requirements:
- professional executive tone
- no mention of AI, automation, or models
- under 250 words
- do not invent data
- position the recommendation as a monthly content governance decision

Current period: {current_start} to {current_end}
Previous period: {previous_start} to {previous_end}

Selected page:
{selected.to_csv(index=False)}

Top candidate sample:
{comparison_sample.to_csv(index=False)}
"""

    try:
        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write precise executive SEO content audit summaries."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content.strip()
        return content if content else "Monthly content audit summary generated with deterministic rules."
    except Exception:
        return "This month's recommendation was generated using the configured content audit thresholds and comparative performance signals."


def create_bar_chart(labels, values, title, xlabel, output_path, positive_better=True):
    plt.figure(figsize=(11, 4.5))
    positions = list(range(len(labels)))
    plt.barh(positions, values)
    plt.yticks(positions, labels, fontsize=9)
    plt.xlabel(xlabel)
    plt.title(title, fontsize=14, pad=14)
    plt.gca().invert_yaxis()
    plt.tight_layout()
    plt.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close()


def create_score_chart(selected_df, output_path):
    if selected_df.empty:
        return

    selected = selected_df.iloc[0]
    labels = ["Clicks Risk", "Position Risk", "CTR Risk", "Traffic Decline Risk", "Overall Score"]
    values = [
        selected["clicks_score"],
        selected["position_score"],
        selected["ctr_score"],
        selected["traffic_decline_score"],
        selected["low_performance_score"],
    ]

    plt.figure(figsize=(11, 4.5))
    plt.bar(labels, values)
    plt.ylim(0, 100)
    plt.ylabel("Score")
    plt.title("Selected Page Risk Profile", fontsize=14, pad=14)
    plt.tight_layout()
    plt.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close()


def shorten_page_label(url):
    label = url.replace("https://", "").replace("http://", "")
    if len(label) > 65:
        return label[:62] + "..."
    return label


def generate_charts(selected_df, scored_df):
    if scored_df.empty:
        return

    top_candidates = scored_df.head(10).copy()
    candidate_labels = [shorten_page_label(x) for x in top_candidates["page"].tolist()]
    create_bar_chart(
        candidate_labels,
        top_candidates["low_performance_score"].tolist(),
        "Top Low-Performance Candidates",
        "Low-Performance Score",
        "content_audit_top_candidates.png",
    )

    create_bar_chart(
        candidate_labels,
        top_candidates["impressions_current"].tolist(),
        "Candidate Visibility",
        "Impressions",
        "content_audit_candidate_impressions.png",
    )

    create_bar_chart(
        candidate_labels,
        top_candidates["clicks_current"].tolist(),
        "Candidate Click Volume",
        "Clicks",
        "content_audit_candidate_clicks.png",
    )

    create_score_chart(selected_df, "content_audit_selected_score.png")


def build_table_html(df, columns, rename_map=None):
    if df.empty:
        return '<div class="empty-state">No rows to display.</div>'
    return html_table_from_df(df, columns, rename_map)


def write_markdown_summary(selected_df, scored_df, commentary_text, current_start, current_end, previous_start, previous_end):
    lines = []
    lines.append("# Monthly Content Audit Recommendation")
    lines.append("")
    lines.append(f"**Current period:** {current_start} to {current_end}")
    lines.append(f"**Previous period:** {previous_start} to {previous_end}")
    lines.append("")
    lines.append("## Executive Commentary")
    lines.append("")
    lines.append(commentary_text)
    lines.append("")

    if not selected_df.empty:
        selected = selected_df.iloc[0]
        lines.append("## Selected Page")
        lines.append("")
        lines.append(f"- Page: {selected['page']}")
        lines.append(f"- Recommendation: {selected['recommended_action']}")
        lines.append(f"- Low-Performance Score: {selected['low_performance_score']:.1f}")
        lines.append(f"- Clicks: {selected['clicks_current']:.0f}")
        lines.append(f"- Impressions: {selected['impressions_current']:.0f}")
        lines.append(f"- CTR: {selected['ctr_current']:.2%}")
        lines.append(f"- Position: {selected['position_current']:.2f}")
        lines.append(f"- Reason: {selected['reason']}")
        lines.append("")

    if not scored_df.empty:
        lines.append("## Top Candidate Set")
        lines.append("")
        lines.append(
            scored_df.head(10)[[
                "page", "recommended_action", "low_performance_score",
                "clicks_current", "impressions_current", "ctr_current", "position_current"
            ]].to_markdown(index=False)
        )

    with open("content_audit_schedule_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_html_summary(selected_df, scored_df, commentary_text, current_start, current_end, previous_start, previous_end):
    commentary_lines = [line.strip() for line in commentary_text.splitlines() if line.strip()]
    selected = selected_df.iloc[0] if not selected_df.empty else None
    top_candidates = scored_df.head(10).copy()

    selected_action = selected["recommended_action"] if selected is not None else "No Selection"
    selected_score = f"{selected['low_performance_score']:.1f}" if selected is not None else "n/a"
    selected_page = shorten_page_label(selected["page"]) if selected is not None else "No eligible page"
    candidate_count = len(scored_df)

    selected_table_html = build_table_html(
        selected_df,
        [
            "page", "recommended_action", "low_performance_score", "clicks_current",
            "impressions_current", "ctr_current", "position_current", "reason"
        ],
        {
            "page": "Page",
            "recommended_action": "Recommendation",
            "low_performance_score": "Score",
            "clicks_current": "Clicks",
            "impressions_current": "Impressions",
            "ctr_current": "CTR",
            "position_current": "Position",
            "reason": "Reason",
        }
    )

    candidate_table_html = build_table_html(
        top_candidates,
        [
            "page", "recommended_action", "low_performance_score", "clicks_current",
            "impressions_current", "ctr_current", "position_current"
        ],
        {
            "page": "Page",
            "recommended_action": "Recommendation",
            "low_performance_score": "Score",
            "clicks_current": "Clicks",
            "impressions_current": "Impressions",
            "ctr_current": "CTR",
            "position_current": "Position",
        }
    )

    html_output = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Monthly Content Audit Recommendation</title>
<style>
{get_pdf_css()}
.chart-block {{
    background: #fff;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    padding: 12px;
    margin: 0 0 16px 0;
    page-break-inside: avoid;
}}
.chart-block img {{
    width: 100%;
    height: auto;
    display: block;
}}
.badge {{
    display: inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.03em;
    margin: 6px 0 10px 0;
}}
.badge-refresh {{ background: #e8f4ff; color: #0f4c81; }}
.badge-archive {{ background: #fff0ec; color: #9e3b20; }}
.empty-state {{ color: #6b7280; font-style: italic; padding: 8px 0; }}
</style>
</head>
<body>
    <h1>Monthly Content Audit Recommendation</h1>
    <div class="muted">Current: {current_start} to {current_end} | Previous: {previous_start} to {previous_end}</div>

    <div class="panel">
        <h2>Executive Commentary</h2>
        <div class="ai-block">{''.join(f'<p>{html.escape(line)}</p>' for line in commentary_lines)}</div>
    </div>

    <h2>Monthly Selection Snapshot</h2>
    <div class="grid">
        {build_card("Selected Action", selected_action, None)}
        {build_card("Selected Score", selected_score, None)}
        {build_card("Candidate Set", candidate_count, None)}
    </div>

    <div class="panel">
        <h2>Selected Page Recommendation</h2>
        <div><strong>{html.escape(selected["recommended_action"] if selected is not None else "No page selected")}</strong></div>
        <div class="muted">{html.escape(selected["page"] if selected is not None else "")}</div>
        {"<span class='badge badge-refresh'>Refresh</span>" if selected is not None and selected["recommended_action"] == "Refresh" else ""}
        {"<span class='badge badge-archive'>Archive</span>" if selected is not None and selected["recommended_action"] == "Archive" else ""}
        {selected_table_html}
    </div>

    <div class="break-before"></div>
    <h2>Risk Profile</h2>
    <div class="chart-block">
        <img src="content_audit_selected_score.png" alt="Selected page risk profile">
    </div>

    <h2>Top Low-Performance Candidates</h2>
    <div class="chart-block">
        <img src="content_audit_top_candidates.png" alt="Top low-performance candidates">
    </div>

    <h2>Candidate Visibility</h2>
    <div class="chart-block">
        <img src="content_audit_candidate_impressions.png" alt="Candidate visibility">
    </div>

    <h2>Candidate Click Volume</h2>
    <div class="chart-block">
        <img src="content_audit_candidate_clicks.png" alt="Candidate click volume">
    </div>

    <h2>Candidate Comparison Table</h2>
    {candidate_table_html}
</body>
</html>
"""
    with open("content_audit_schedule_summary.html", "w", encoding="utf-8") as f:
        f.write(html_output)


def generate_pdf():
    HTML("content_audit_schedule_summary.html").write_pdf("content_audit_schedule_summary.pdf")
    print("Saved content_audit_schedule_summary.pdf")


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
        "body": "Content audit PDF report attached.",
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
            files={"pdf": ("content-audit-schedule.pdf", f, "application/pdf")},
            timeout=120,
        )

    print("monday file upload status:", response.status_code)
    print("monday file upload response:", response.text)
    response.raise_for_status()
    print("Uploaded PDF to monday update.")


def main():
    service = get_service()
    config_df = load_config()

    current_end = date.today() - timedelta(days=1)
    current_start = current_end - timedelta(days=27)

    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=27)

    current_df = fetch_page_data(service, current_start, current_end, row_limit=1000)
    previous_df = fetch_page_data(service, previous_start, previous_end, row_limit=1000)

    current_df = normalize_page_groups(apply_page_rules(current_df, config_df))
    previous_df = normalize_page_groups(apply_page_rules(previous_df, config_df))

    comparison_df = prepare_comparison(current_df, previous_df)
    scored_df = score_candidates(comparison_df, config_df)
    selected_df, candidate_df = choose_monthly_candidate(scored_df, config_df)

    commentary_text = build_executive_analysis(
        selected_df,
        candidate_df,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )

    comparison_df.to_csv("content_audit_page_comparison.csv", index=False)
    scored_df.to_csv("content_audit_candidates.csv", index=False)
    selected_df.to_csv("content_audit_selection.csv", index=False)

    generate_charts(selected_df, candidate_df)

    write_markdown_summary(
        selected_df,
        candidate_df,
        commentary_text,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )
    write_html_summary(
        selected_df,
        candidate_df,
        commentary_text,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )

    generate_pdf()

    try:
        upload_pdf_to_monday("content_audit_schedule_summary.pdf")
    except Exception as e:
        print(f"monday upload step failed: {e}")

    print("Saved content audit outputs.")


if __name__ == "__main__":
    main()
