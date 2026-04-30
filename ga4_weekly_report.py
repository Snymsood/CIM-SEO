from datetime import date, timedelta
from openai import OpenAI
import pandas as pd
import requests
import os
import html
import json

from google_sheets_db import append_to_sheet
from pdf_report_formatter import html_table_from_df
from html_report_utils import (
    mm_html_shell, mm_kpi_card, mm_kpi_grid, mm_section, mm_report_section,
    mm_col_header, mm_exec_bullets, mm_ai_block,
    generate_self_contained_html, upload_html_to_monday,
)
from seo_utils import get_weekly_date_windows
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
KEY_FILE = "gsc-key.json"
PROPERTY_ID = os.environ["GA4_PROPERTY_ID"]

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")

MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"


def get_ga4_client():
    credentials = service_account.Credentials.from_service_account_file(
        KEY_FILE,
        scopes=SCOPES,
    )
    return BetaAnalyticsDataClient(credentials=credentials)


def run_report(client, dimensions, metrics, start_date, end_date, limit=100):
    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        limit=limit,
    )
    return client.run_report(request)


def response_to_df(response, dimensions, metrics):
    rows = []
    for row in response.rows:
        record = {}
        for i, dim in enumerate(dimensions):
            record[dim] = row.dimension_values[i].value
        for i, met in enumerate(metrics):
            record[met] = row.metric_values[i].value
        rows.append(record)
    return pd.DataFrame(rows)


def get_summary_metrics(client, start_date, end_date):
    metrics = [
        "activeUsers",
        "sessions",
        "engagedSessions",
        "engagementRate",
        "averageSessionDuration",
        "eventCount",
    ]
    response = run_report(
        client,
        dimensions=[],
        metrics=metrics,
        start_date=start_date,
        end_date=end_date,
        limit=1,
    )

    if not response.rows:
        return {m: 0 for m in metrics}

    row = response.rows[0]
    values = {}
    for i, metric in enumerate(metrics):
        values[metric] = row.metric_values[i].value
    return values


def get_top_landing_pages(client, start_date, end_date):
    dimensions = ["landingPage"]
    metrics = ["sessions", "activeUsers", "engagementRate", "averageSessionDuration", "eventCount"]
    response = run_report(client, dimensions, metrics, start_date, end_date, limit=25)
    return response_to_df(response, dimensions, metrics)


def get_top_channels(client, start_date, end_date):
    dimensions = ["sessionDefaultChannelGroup"]
    metrics = ["sessions", "activeUsers", "engagementRate"]
    response = run_report(client, dimensions, metrics, start_date, end_date, limit=15)
    return response_to_df(response, dimensions, metrics)


def get_device_split(client, start_date, end_date):
    dimensions = ["deviceCategory"]
    metrics = ["sessions", "activeUsers", "engagementRate"]
    response = run_report(client, dimensions, metrics, start_date, end_date, limit=10)
    return response_to_df(response, dimensions, metrics)


def get_country_split(client, start_date, end_date):
    dimensions = ["country"]
    metrics = ["sessions", "activeUsers", "engagementRate"]
    response = run_report(client, dimensions, metrics, start_date, end_date, limit=15)
    return response_to_df(response, dimensions, metrics)


def prepare_summary_comparison(current_summary, previous_summary):
    rows = []
    for metric in current_summary.keys():
        current_value = float(current_summary[metric])
        previous_value = float(previous_summary.get(metric, 0))
        rows.append({
            "metric": metric,
            "current": current_value,
            "previous": previous_value,
            "change": current_value - previous_value,
        })
    return pd.DataFrame(rows)


def build_executive_read(summary_df):
    metric_map = {row["metric"]: row for _, row in summary_df.iterrows()}

    sessions_current = metric_map["sessions"]["current"]
    sessions_previous = metric_map["sessions"]["previous"]
    users_current = metric_map["activeUsers"]["current"]
    users_previous = metric_map["activeUsers"]["previous"]
    engagement_rate_current = metric_map["engagementRate"]["current"]
    engagement_rate_previous = metric_map["engagementRate"]["previous"]
    engaged_sessions_current = metric_map["engagedSessions"]["current"]
    engaged_sessions_previous = metric_map["engagedSessions"]["previous"]

    lines = []

    if sessions_current > sessions_previous:
        lines.append("Sessions increased week over week.")
    elif sessions_current < sessions_previous:
        lines.append("Sessions declined week over week.")
    else:
        lines.append("Sessions were flat week over week.")

    if users_current > users_previous:
        lines.append("Active users increased week over week.")
    elif users_current < users_previous:
        lines.append("Active users declined week over week.")
    else:
        lines.append("Active users were flat week over week.")

    if engagement_rate_current > engagement_rate_previous:
        lines.append("Engagement rate improved versus the prior period.")
    elif engagement_rate_current < engagement_rate_previous:
        lines.append("Engagement rate declined versus the prior period.")
    else:
        lines.append("Engagement rate was flat versus the prior period.")

    if engaged_sessions_current > engaged_sessions_previous:
        lines.append("Engaged sessions increased week over week.")
    elif engaged_sessions_current < engaged_sessions_previous:
        lines.append("Engaged sessions declined week over week.")
    else:
        lines.append("Engaged sessions were flat week over week.")

    return lines


def build_ai_analysis(summary_df, top_pages_df, top_channels_df, current_start, current_end, previous_start, previous_end):
    if not GROQ_API_KEY:
        return "AI executive analysis was skipped because GROQ_API_KEY is not configured."

    prompt = f"""
You are writing a concise corporate GA4 weekly performance summary for stakeholders.

Write:
1. Executive Summary
2. Positive Signals
3. Risks / Watchouts
4. Recommended Actions

Requirements:
- professional corporate tone
- under 350 words
- do not invent data
- focus on actual weekly movement

Current period: {current_start} to {current_end}
Previous period: {previous_start} to {previous_end}

Summary metrics:
{summary_df.to_csv(index=False)}

Top landing pages:
{top_pages_df.head(10).to_csv(index=False)}

Top channels:
{top_channels_df.head(10).to_csv(index=False)}
"""

    try:
        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write precise weekly GA4 stakeholder summaries."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI executive analysis failed, so the report fell back to deterministic output only. Error: {str(e)}"


def write_html_summary(summary_df, top_pages_df, top_channels_df, device_df, country_df, ai_analysis, current_start, current_end, previous_start, previous_end):
    executive_read = build_executive_read(summary_df)
    metric_map = {row["metric"]: row for _, row in summary_df.iterrows()}

    kpi_grid = mm_kpi_grid(
        mm_kpi_card("Active Users",      metric_map['activeUsers']['current'],      metric_map['activeUsers']['previous']),
        mm_kpi_card("Sessions",          metric_map['sessions']['current'],          metric_map['sessions']['previous']),
        mm_kpi_card("Engaged Sessions",  metric_map['engagedSessions']['current'],  metric_map['engagedSessions']['previous']),
        mm_kpi_card("Engagement Rate",   metric_map['engagementRate']['current'],   metric_map['engagementRate']['previous'], is_pct=True),
    )

    bullets_html = mm_exec_bullets(executive_read)
    ai_html      = mm_ai_block(ai_analysis)

    def tbl(df, cols, rename):
        return html_table_from_df(df, cols, rename) if not df.empty else "<p>No data.</p>"

    body = (
        mm_section("Executive Summary",
            mm_report_section(bullets_html + ai_html)
        ) +
        f'<div class="section" style="padding-top:0;">{kpi_grid}</div>'
        '<hr class="rule-thick">' +
        mm_section("Top Landing Pages",
            mm_report_section(tbl(
                top_pages_df.head(15),
                ["landingPage","sessions","activeUsers","engagementRate","averageSessionDuration","eventCount"],
                {"landingPage":"Landing Page","sessions":"Sessions","activeUsers":"Users",
                 "engagementRate":"Eng Rate","averageSessionDuration":"Avg Dur","eventCount":"Events"}
            ))
        ) +
        mm_section("Channels",
            mm_report_section(tbl(
                top_channels_df,
                ["sessionDefaultChannelGroup","sessions","activeUsers","engagementRate"],
                {"sessionDefaultChannelGroup":"Channel","sessions":"Sessions","activeUsers":"Users","engagementRate":"Eng Rate"}
            ))
        ) +
        mm_section("Device Split",
            mm_report_section(tbl(
                device_df,
                ["deviceCategory","sessions","activeUsers","engagementRate"],
                {"deviceCategory":"Device","sessions":"Sessions","activeUsers":"Users","engagementRate":"Eng Rate"}
            ))
        ) +
        mm_section("Country Split",
            mm_report_section(tbl(
                country_df.head(15),
                ["country","sessions","activeUsers","engagementRate"],
                {"country":"Country","sessions":"Sessions","activeUsers":"Users","engagementRate":"Eng Rate"}
            ))
        )
    )

    doc = mm_html_shell(
        title="GA4 Weekly Performance Report",
        eyebrow="Google Analytics 4",
        headline="Weekly Performance\nReport",
        meta_line=f"{current_start} → {current_end} / prev {previous_start} → {previous_end}",
        body_content=body,
    )
    with open("ga4_weekly_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("Saved ga4_weekly_summary.html")


def generate_self_contained():
    generate_self_contained_html("ga4_weekly_summary.html", "ga4_weekly_summary_final.html")


def upload_to_monday():
    upload_html_to_monday(
        "ga4_weekly_summary_final.html",
        "ga4-weekly-report.html",
        body_text="GA4 Weekly Performance Report attached as self-contained HTML.",
    )


def main():
    client = get_ga4_client()

    current_start, current_end, previous_start, previous_end = get_weekly_date_windows()

    current_summary = get_summary_metrics(client, current_start.isoformat(), current_end.isoformat())
    previous_summary = get_summary_metrics(client, previous_start.isoformat(), previous_end.isoformat())
    summary_df = prepare_summary_comparison(current_summary, previous_summary)

    top_pages_df = get_top_landing_pages(client, current_start.isoformat(), current_end.isoformat())
    top_channels_df = get_top_channels(client, current_start.isoformat(), current_end.isoformat())
    device_df = get_device_split(client, current_start.isoformat(), current_end.isoformat())
    country_df = get_country_split(client, current_start.isoformat(), current_end.isoformat())

    summary_df.to_csv("ga4_summary_comparison.csv", index=False)
    top_pages_df.to_csv("ga4_top_landing_pages.csv", index=False)
    top_channels_df.to_csv("ga4_top_channels.csv", index=False)
    device_df.to_csv("ga4_device_split.csv", index=False)
    country_df.to_csv("ga4_country_split.csv", index=False)

    append_to_sheet(summary_df, "GA4_Summary")
    append_to_sheet(top_pages_df, "GA4_Top_Pages")
    append_to_sheet(top_channels_df, "GA4_Top_Channels")
    append_to_sheet(device_df, "GA4_Device_Split")
    append_to_sheet(country_df, "GA4_Country_Split")

    ai_analysis = build_ai_analysis(
        summary_df,
        top_pages_df,
        top_channels_df,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )

    write_html_summary(
        summary_df, top_pages_df, top_channels_df, device_df, country_df,
        ai_analysis, current_start, current_end, previous_start, previous_end,
    )
    generate_self_contained()
    try:
        upload_to_monday()
    except Exception as e:
        print(f"monday upload step failed: {e}")

    print("Saved GA4 outputs.")


if __name__ == "__main__":
    main()
