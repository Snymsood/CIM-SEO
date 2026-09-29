#!/usr/bin/env python3
"""Mailchimp weekly content performance report.

Pulls aggregate campaign/report/link-click data only. It intentionally avoids
subscriber-level activity so the output remains content-focused and privacy
safe for broad reporting.
"""

from __future__ import annotations

import html
import os
import re
from datetime import datetime, time, timezone
from pathlib import Path
from urllib.parse import urlparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests

from html_report_utils import (
    generate_self_contained_html,
    mm_chart_wrap,
    mm_html_shell,
    mm_kpi_card,
    mm_kpi_grid,
    mm_report_section,
    mm_section,
    upload_html_to_monday,
)
from reporting_ops import canonicalize_url
from seo_utils import get_weekly_date_windows, short_url


MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY", "")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX", "")
MAILCHIMP_AUDIENCE_ID = os.getenv("MAILCHIMP_AUDIENCE_ID", "")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID") or os.getenv("MONDAY_MAILCHIMP_ITEM_ID")

CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

C_NAVY = "#212878"
C_TEAL = "#2A9D8F"
C_CORAL = "#E76F51"
C_AMBER = "#D97706"
C_SLATE = "#6C757D"
C_BORDER = "#E2E8F0"


def _server_prefix() -> str:
    if MAILCHIMP_SERVER_PREFIX:
        return MAILCHIMP_SERVER_PREFIX.strip()
    if "-" in MAILCHIMP_API_KEY:
        return MAILCHIMP_API_KEY.rsplit("-", 1)[-1]
    return ""


def _base_url() -> str:
    prefix = _server_prefix()
    if not prefix:
        raise RuntimeError("MAILCHIMP_API_KEY must include a data-center suffix like -us6, or set MAILCHIMP_SERVER_PREFIX.")
    return f"https://{prefix}.api.mailchimp.com/3.0"


def _request(path: str, params: dict | None = None) -> dict:
    if not MAILCHIMP_API_KEY:
        raise RuntimeError("MAILCHIMP_API_KEY is not configured.")
    response = requests.get(
        f"{_base_url()}{path}",
        auth=("cim-seo-reporting", MAILCHIMP_API_KEY),
        params=params or {},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _iso_start(dt) -> str:
    return datetime.combine(dt, time.min, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_end(dt) -> str:
    return datetime.combine(dt, time.max, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_campaigns(start_date, end_date) -> pd.DataFrame:
    params = {
        "status": "sent",
        "since_send_time": _iso_start(start_date),
        "before_send_time": _iso_end(end_date),
        "count": 1000,
        "sort_field": "send_time",
        "sort_dir": "DESC",
    }
    if MAILCHIMP_AUDIENCE_ID:
        params["list_id"] = MAILCHIMP_AUDIENCE_ID

    payload = _request("/campaigns", params=params)
    rows = []
    for campaign in payload.get("campaigns", []):
        settings = campaign.get("settings", {})
        recipients = campaign.get("recipients", {})
        rows.append({
            "campaign_id": campaign.get("id", ""),
            "web_id": campaign.get("web_id", ""),
            "type": campaign.get("type", ""),
            "status": campaign.get("status", ""),
            "send_time": campaign.get("send_time", ""),
            "emails_sent": recipients.get("recipient_count", 0),
            "subject_line": settings.get("subject_line", ""),
            "title": settings.get("title", ""),
            "from_name": settings.get("from_name", ""),
            "archive_url": campaign.get("archive_url", ""),
        })
    return pd.DataFrame(rows)


def fetch_campaign_report(campaign_id: str) -> dict:
    try:
        return _request(f"/reports/{campaign_id}")
    except Exception as e:
        print(f"  Mailchimp report fetch failed for {campaign_id}: {e}", flush=True)
        return {}


def fetch_click_details(campaign_id: str) -> pd.DataFrame:
    try:
        payload = _request(f"/reports/{campaign_id}/click-details", params={"count": 1000})
    except Exception as e:
        print(f"  Mailchimp click-details fetch failed for {campaign_id}: {e}", flush=True)
        return pd.DataFrame()

    rows = []
    for item in payload.get("urls_clicked", []):
        url = item.get("url", "")
        rows.append({
            "campaign_id": campaign_id,
            "url": url,
            "url_canonical": canonicalize_url(url),
            "total_clicks": item.get("total_clicks", 0),
            "unique_clicks": item.get("unique_clicks", 0),
            "click_percentage": item.get("click_percentage", 0),
            "unique_click_percentage": item.get("unique_click_percentage", 0),
            "last_click": item.get("last_click", ""),
        })
    return pd.DataFrame(rows)


def infer_link_format(url: str) -> str:
    lower = str(url).lower()
    path = urlparse(lower).path
    if path.endswith(".pdf"):
        return "PDF/resource"
    if "magazine.cim.org" in lower:
        return "Magazine article"
    if "/events" in lower or "convention.cim.org" in lower:
        return "Event page"
    if "/news" in lower or "/press" in lower:
        return "News"
    if "/professional-development" in lower or "/short-courses" in lower:
        return "Education"
    if "/membership" in lower:
        return "Membership"
    if "/library" in lower or "/technical-resources" in lower:
        return "Technical resource"
    if lower.startswith("mailto:"):
        return "Email link"
    if not re.match(r"^https?://", lower):
        return "Other"
    return "Web page"


def flatten_reports(campaigns_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    report_rows = []
    click_frames = []
    for _, campaign in campaigns_df.iterrows():
        campaign_id = str(campaign["campaign_id"])
        report = fetch_campaign_report(campaign_id)
        opens = report.get("opens", {})
        clicks = report.get("clicks", {})
        ecommerce = report.get("ecommerce", {})
        report_rows.append({
            "campaign_id": campaign_id,
            "emails_sent": report.get("emails_sent", campaign.get("emails_sent", 0)),
            "abuse_reports": report.get("abuse_reports", 0),
            "unsubscribed": report.get("unsubscribed", 0),
            "open_rate": opens.get("open_rate", 0),
            "opens_total": opens.get("opens_total", 0),
            "unique_opens": opens.get("unique_opens", 0),
            "click_rate": clicks.get("click_rate", 0),
            "clicks_total": clicks.get("clicks_total", 0),
            "unique_clicks": clicks.get("unique_clicks", 0),
            "total_revenue": ecommerce.get("total_revenue", 0),
        })
        click_df = fetch_click_details(campaign_id)
        if not click_df.empty:
            click_df["subject_line"] = campaign.get("subject_line", "")
            click_df["send_time"] = campaign.get("send_time", "")
            click_df["link_format"] = click_df["url"].apply(infer_link_format)
            click_frames.append(click_df)

    report_df = pd.DataFrame(report_rows)
    click_df = pd.concat(click_frames, ignore_index=True) if click_frames else pd.DataFrame(
        columns=["campaign_id", "url", "url_canonical", "total_clicks", "unique_clicks", "link_format"]
    )
    return report_df, click_df


def build_summary(campaigns_df: pd.DataFrame, reports_df: pd.DataFrame, clicks_df: pd.DataFrame) -> pd.DataFrame:
    if campaigns_df.empty:
        return pd.DataFrame([{
            "campaigns_sent": 0,
            "emails_sent": 0,
            "avg_open_rate": 0,
            "avg_click_rate": 0,
            "total_clicks": 0,
            "unique_clicked_links": 0,
        }])
    return pd.DataFrame([{
        "campaigns_sent": len(campaigns_df),
        "emails_sent": pd.to_numeric(reports_df.get("emails_sent", pd.Series(dtype=float)), errors="coerce").fillna(0).sum(),
        "avg_open_rate": pd.to_numeric(reports_df.get("open_rate", pd.Series(dtype=float)), errors="coerce").fillna(0).mean() if not reports_df.empty else 0,
        "avg_click_rate": pd.to_numeric(reports_df.get("click_rate", pd.Series(dtype=float)), errors="coerce").fillna(0).mean() if not reports_df.empty else 0,
        "total_clicks": pd.to_numeric(clicks_df.get("total_clicks", pd.Series(dtype=float)), errors="coerce").fillna(0).sum() if not clicks_df.empty else 0,
        "unique_clicked_links": clicks_df["url_canonical"].nunique() if not clicks_df.empty and "url_canonical" in clicks_df.columns else 0,
    }])


def _fmt_num(value, decimals=0, pct=False):
    try:
        value = float(value)
    except Exception:
        return "-"
    if pct:
        return f"{value:.1%}"
    if decimals:
        return f"{value:,.{decimals}f}"
    return f"{value:,.0f}"


def _style_ax(ax, title):
    ax.set_title(title, fontsize=10, fontweight="600", loc="left", color="#111")
    ax.tick_params(labelsize=8, colors="#555", length=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(C_BORDER)
    ax.spines["bottom"].set_color(C_BORDER)
    ax.grid(axis="x", linestyle="--", alpha=0.25, color=C_BORDER)


def _save(fig, filename):
    path = CHARTS_DIR / filename
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def chart_campaign_rates(campaigns_df: pd.DataFrame, reports_df: pd.DataFrame):
    if campaigns_df.empty or reports_df.empty:
        fig, ax = plt.subplots(figsize=(12, 4.8))
        ax.text(0.5, 0.5, "No Mailchimp campaign data for this period.", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "mailchimp_campaign_rates.png")

    df = campaigns_df[["campaign_id", "subject_line"]].merge(reports_df, on="campaign_id", how="left")
    df["label"] = df["subject_line"].fillna("").apply(lambda x: short_url(str(x), 42))
    df = df.tail(10)
    y = range(len(df))
    fig, ax = plt.subplots(figsize=(12, 5.4))
    ax.barh([i - 0.18 for i in y], df["open_rate"], height=0.34, color=C_NAVY, label="Open rate")
    ax.barh([i + 0.18 for i in y], df["click_rate"], height=0.34, color=C_TEAL, label="Click rate")
    ax.set_yticks(list(y))
    ax.set_yticklabels(df["label"])
    ax.legend(frameon=False, fontsize=8)
    ax.set_xlim(0, max(0.01, float(max(df["open_rate"].max(), df["click_rate"].max())) * 1.25))
    _style_ax(ax, "Campaign open and click rates")
    fig.tight_layout()
    return _save(fig, "mailchimp_campaign_rates.png")


def chart_link_formats(clicks_df: pd.DataFrame):
    if clicks_df.empty or "link_format" not in clicks_df.columns:
        fig, ax = plt.subplots(figsize=(12, 4.8))
        ax.text(0.5, 0.5, "No clicked links for this period.", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "mailchimp_link_formats.png")

    data = clicks_df.groupby("link_format")["unique_clicks"].sum().sort_values()
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.barh(data.index, data.values, color=C_AMBER)
    max_v = max(data.max(), 1)
    for i, value in enumerate(data.values):
        ax.text(value + max_v * 0.01, i, f"{value:,.0f}", va="center", fontsize=8)
    _style_ax(ax, "Unique clicks by linked content format")
    fig.tight_layout()
    return _save(fig, "mailchimp_link_formats.png")


def _table(df: pd.DataFrame, cols: list[str], labels: dict[str, str], max_rows=20) -> str:
    if df.empty:
        return "<p>No rows to display.</p>"
    rows = []
    for _, row in df.head(max_rows).iterrows():
        cells = []
        for col in cols:
            value = row.get(col, "")
            if "rate" in col or "percentage" in col:
                value = _fmt_num(value, pct=True)
            elif col.endswith("clicks") or col == "emails_sent":
                value = _fmt_num(value)
            else:
                value = str(value)
            if str(value).startswith("http"):
                label = html.escape(short_url(str(value), 72))
                value = f'<a href="{html.escape(str(value), quote=True)}">{label}</a>'
            else:
                value = html.escape(str(value))
            cells.append(f"<td>{value}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    heads = "".join(f"<th>{html.escape(labels.get(col, col))}</th>" for col in cols)
    return f"<table><thead><tr>{heads}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def write_html(campaigns_df, reports_df, clicks_df, summary_df, start_date, end_date):
    summary = summary_df.iloc[0].to_dict()
    chart_a = chart_campaign_rates(campaigns_df, reports_df)
    chart_b = chart_link_formats(clicks_df)

    kpis = mm_kpi_grid(
        mm_kpi_card("Campaigns", summary["campaigns_sent"], None),
        mm_kpi_card("Emails Sent", summary["emails_sent"], None),
        mm_kpi_card("Avg Open Rate", summary["avg_open_rate"], None, is_pct=True),
        mm_kpi_card("Avg Click Rate", summary["avg_click_rate"], None, is_pct=True),
    )

    top_links = clicks_df.sort_values("unique_clicks", ascending=False) if not clicks_df.empty and "unique_clicks" in clicks_df.columns else clicks_df
    campaign_table = campaigns_df.merge(reports_df, on="campaign_id", how="left") if not campaigns_df.empty else pd.DataFrame()

    body = (
        f'<div class="section" style="padding-top:0;">{kpis}</div><hr class="rule-thick">'
        + mm_section("Executive Readout", mm_report_section(
            "<ul class=\"exec-bullets\">"
            f"<li>{_fmt_num(summary['total_clicks'])} total link clicks across {_fmt_num(summary['unique_clicked_links'])} unique clicked links.</li>"
            "<li>Use the linked-content table to identify which articles, resources, events, and landing pages deserve follow-up distribution.</li>"
            "<li>Subscriber-level activity is intentionally excluded; this report is aggregate and content-focused.</li>"
            "</ul>"
        ))
        + mm_section("Campaign Performance", mm_report_section(
            mm_chart_wrap(str(chart_a), "Mailchimp campaign rates")
            + _table(
                campaign_table.sort_values("send_time", ascending=False) if not campaign_table.empty else campaign_table,
                ["send_time", "subject_line", "emails_sent", "open_rate", "click_rate", "unique_clicks"],
                {"send_time": "Sent", "subject_line": "Subject", "emails_sent": "Emails", "open_rate": "Open", "click_rate": "Click", "unique_clicks": "Unique Clicks"},
                max_rows=12,
            )
        ))
        + mm_section("Clicked Content", mm_report_section(
            mm_chart_wrap(str(chart_b), "Clicked content formats")
            + _table(
                top_links,
                ["url", "link_format", "unique_clicks", "total_clicks", "subject_line"],
                {"url": "URL", "link_format": "Format", "unique_clicks": "Unique Clicks", "total_clicks": "Total Clicks", "subject_line": "Campaign"},
                max_rows=25,
            )
        ))
    )

    doc = mm_html_shell(
        title="Mailchimp Weekly Content Report",
        eyebrow="CIM Content Intelligence",
        headline="Mailchimp Weekly\nContent Report",
        meta_line=f"{start_date} to {end_date}",
        body_content=body,
    )
    Path("mailchimp_weekly_summary.html").write_text(doc, encoding="utf-8")
    generate_self_contained_html("mailchimp_weekly_summary.html", "mailchimp_weekly_summary_final.html")


def upload_to_monday():
    upload_html_to_monday(
        "mailchimp_weekly_summary_final.html",
        "mailchimp-weekly-content-report.html",
        body_text="Mailchimp Weekly Content Report attached as self-contained HTML.",
        api_token=MONDAY_API_TOKEN,
        item_id=MONDAY_ITEM_ID,
    )


def main():
    print("Mailchimp Weekly Content Report - starting", flush=True)
    start_date, end_date, _, _ = get_weekly_date_windows()

    if not MAILCHIMP_API_KEY:
        print("MAILCHIMP_API_KEY is not configured; writing empty Mailchimp report artifacts.", flush=True)
        campaigns_df = pd.DataFrame(columns=[
            "campaign_id", "web_id", "type", "status", "send_time", "emails_sent",
            "subject_line", "title", "from_name", "archive_url",
        ])
        reports_df = pd.DataFrame(columns=[
            "campaign_id", "emails_sent", "open_rate", "opens_total",
            "unique_opens", "click_rate", "clicks_total", "unique_clicks",
        ])
        clicks_df = pd.DataFrame(columns=[
            "campaign_id", "url", "url_canonical", "total_clicks",
            "unique_clicks", "link_format",
        ])
        summary_df = build_summary(campaigns_df, reports_df, clicks_df)
        campaigns_df.to_csv("mailchimp_campaigns.csv", index=False)
        reports_df.to_csv("mailchimp_campaign_reports.csv", index=False)
        clicks_df.to_csv("mailchimp_link_clicks.csv", index=False)
        summary_df.to_csv("mailchimp_weekly_summary.csv", index=False)
        write_html(campaigns_df, reports_df, clicks_df, summary_df, start_date, end_date)
        upload_to_monday()
        print("Mailchimp Weekly Content Report - complete with empty artifacts", flush=True)
        return

    campaigns_df = fetch_campaigns(start_date, end_date)
    reports_df, clicks_df = flatten_reports(campaigns_df) if not campaigns_df.empty else (
        pd.DataFrame(),
        pd.DataFrame(columns=["campaign_id", "url", "url_canonical", "total_clicks", "unique_clicks", "link_format"]),
    )
    summary_df = build_summary(campaigns_df, reports_df, clicks_df)

    campaigns_df.to_csv("mailchimp_campaigns.csv", index=False)
    reports_df.to_csv("mailchimp_campaign_reports.csv", index=False)
    clicks_df.to_csv("mailchimp_link_clicks.csv", index=False)
    summary_df.to_csv("mailchimp_weekly_summary.csv", index=False)

    write_html(campaigns_df, reports_df, clicks_df, summary_df, start_date, end_date)
    upload_to_monday()
    print("Mailchimp Weekly Content Report - complete", flush=True)


if __name__ == "__main__":
    main()
