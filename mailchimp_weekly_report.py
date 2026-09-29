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
from bs4 import BeautifulSoup

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

NEWSLETTER_SEGMENTS = ["The Reporter", "Events", "CIM Magazine", "Other"]


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


def fetch_campaign_content(campaign_id: str) -> dict:
    try:
        return _request(f"/campaigns/{campaign_id}/content")
    except Exception as e:
        print(f"  Mailchimp content fetch failed for {campaign_id}: {e}", flush=True)
        return {}


def infer_newsletter_segment(row_or_text) -> str:
    if isinstance(row_or_text, pd.Series):
        text = " ".join([
            str(row_or_text.get("title", "")),
            str(row_or_text.get("subject_line", "")),
            str(row_or_text.get("from_name", "")),
        ]).lower()
    else:
        text = str(row_or_text).lower()

    if "reporter" in text or "cim news" in text:
        return "The Reporter"
    if "magazine" in text or "weekly mining news recap" in text or "cim mag" in text:
        return "CIM Magazine"
    if "event" in text or "events report" in text or "convention" in text or "symposium" in text or "cps" in text:
        return "Events"
    return "Other"


def is_meaningful_content_link(url: str) -> bool:
    lower = str(url).lower()
    if not lower.startswith(("http://", "https://")):
        return False
    blocked = (
        "list-manage.com",
        "mailchimp.com",
        "facebook.com",
        "twitter.com",
        "x.com",
        "linkedin.com",
        "instagram.com",
        "youtube.com",
        "unsubscribe",
        "preferences",
        "forward-to-friend",
        "campaign-archive.com",
    )
    return not any(fragment in lower for fragment in blocked)


def extract_content_links(campaign_id: str, campaign: pd.Series) -> pd.DataFrame:
    content = fetch_campaign_content(campaign_id)
    html_blob = "\n".join(
        str(content.get(key, ""))
        for key in ("html", "archive_html")
        if content.get(key)
    )
    if not html_blob:
        return pd.DataFrame(columns=[
            "campaign_id", "url", "url_canonical", "link_position",
            "anchor_text", "is_top_story", "newsletter_segment",
        ])

    soup = BeautifulSoup(html_blob, "html.parser")
    rows = []
    seen = set()
    for a in soup.find_all("a", href=True):
        url = a.get("href", "").strip()
        if not is_meaningful_content_link(url):
            continue
        canonical = canonicalize_url(url)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        rows.append({
            "campaign_id": campaign_id,
            "url": url,
            "url_canonical": canonical,
            "link_position": len(rows) + 1,
            "anchor_text": a.get_text(" ", strip=True)[:180],
            "is_top_story": len(rows) == 0,
            "newsletter_segment": infer_newsletter_segment(campaign),
        })
    return pd.DataFrame(rows)


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
    content_link_frames = []
    for _, campaign in campaigns_df.iterrows():
        campaign_id = str(campaign["campaign_id"])
        segment = infer_newsletter_segment(campaign)
        report = fetch_campaign_report(campaign_id)
        opens = report.get("opens", {})
        clicks = report.get("clicks", {})
        ecommerce = report.get("ecommerce", {})
        report_rows.append({
            "campaign_id": campaign_id,
            "newsletter_segment": segment,
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
            click_df["newsletter_segment"] = segment
            click_df["link_format"] = click_df["url"].apply(infer_link_format)
            click_frames.append(click_df)
        content_links_df = extract_content_links(campaign_id, campaign)
        if not content_links_df.empty:
            content_link_frames.append(content_links_df)

    report_df = pd.DataFrame(report_rows)
    click_df = pd.concat(click_frames, ignore_index=True) if click_frames else pd.DataFrame(
        columns=["campaign_id", "url", "url_canonical", "total_clicks", "unique_clicks", "newsletter_segment", "link_format"]
    )
    content_links_df = pd.concat(content_link_frames, ignore_index=True) if content_link_frames else pd.DataFrame(
        columns=["campaign_id", "url", "url_canonical", "link_position", "anchor_text", "is_top_story", "newsletter_segment"]
    )
    if not click_df.empty and not content_links_df.empty:
        click_df = click_df.merge(
            content_links_df[["campaign_id", "url_canonical", "link_position", "anchor_text", "is_top_story"]],
            on=["campaign_id", "url_canonical"],
            how="left",
        )
    return report_df, click_df, content_links_df


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


def build_segment_summary(campaigns_df: pd.DataFrame, reports_df: pd.DataFrame, clicks_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "newsletter_segment", "primary_metric", "campaigns_sent", "emails_sent",
        "avg_open_rate", "avg_click_rate", "avg_click_to_open_rate",
        "total_clicks", "unique_clicks", "unique_clicked_links",
        "top_story_unique_clicks", "top_story_click_rate",
        "magazine_site_unique_clicks", "event_link_unique_clicks",
        "unsubscribed", "abuse_reports",
    ]
    if campaigns_df.empty:
        return pd.DataFrame(columns=columns)

    campaigns = campaigns_df.copy()
    campaigns["newsletter_segment"] = campaigns.apply(infer_newsletter_segment, axis=1)
    report = reports_df.copy()
    if "newsletter_segment" not in report.columns and not report.empty:
        report = report.merge(campaigns[["campaign_id", "newsletter_segment"]], on="campaign_id", how="left")
    clicks = clicks_df.copy()
    if "newsletter_segment" not in clicks.columns and not clicks.empty:
        clicks = clicks.merge(campaigns[["campaign_id", "newsletter_segment"]], on="campaign_id", how="left")

    rows = []
    for segment in NEWSLETTER_SEGMENTS:
        seg_campaigns = campaigns[campaigns["newsletter_segment"] == segment]
        seg_reports = report[report["newsletter_segment"] == segment] if not report.empty else pd.DataFrame()
        seg_clicks = clicks[clicks["newsletter_segment"] == segment] if not clicks.empty else pd.DataFrame()
        if seg_campaigns.empty and seg_reports.empty and seg_clicks.empty:
            continue

        emails_sent = pd.to_numeric(seg_reports.get("emails_sent", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
        unique_opens = pd.to_numeric(seg_reports.get("unique_opens", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
        unique_clicks = pd.to_numeric(seg_reports.get("unique_clicks", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
        total_clicks = pd.to_numeric(seg_reports.get("clicks_total", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
        if total_clicks == 0 and not seg_clicks.empty:
            total_clicks = pd.to_numeric(seg_clicks.get("total_clicks", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
        if unique_clicks == 0 and not seg_clicks.empty:
            unique_clicks = pd.to_numeric(seg_clicks.get("unique_clicks", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()

        top_story_clicks = 0
        if not seg_clicks.empty and "is_top_story" in seg_clicks.columns:
            top_story_clicks = pd.to_numeric(
                seg_clicks.loc[seg_clicks["is_top_story"].fillna(False).astype(bool), "unique_clicks"],
                errors="coerce",
            ).fillna(0).sum()

        magazine_clicks = 0
        event_clicks = 0
        if not seg_clicks.empty:
            magazine_clicks = pd.to_numeric(
                seg_clicks.loc[seg_clicks["url_canonical"].astype(str).str.contains("magazine.cim.org", case=False, na=False), "unique_clicks"],
                errors="coerce",
            ).fillna(0).sum()
            event_clicks = pd.to_numeric(
                seg_clicks.loc[
                    seg_clicks["link_format"].astype(str).str.contains("Event", case=False, na=False)
                    | seg_clicks["url_canonical"].astype(str).str.contains("convention|events|symposium", case=False, na=False),
                    "unique_clicks",
                ],
                errors="coerce",
            ).fillna(0).sum()

        primary = {
            "The Reporter": "Open rate + top-story clicks",
            "Events": "Click rate / click-to-open rate",
            "CIM Magazine": "Magazine click-throughs",
        }.get(segment, "Open and click health")
        rows.append({
            "newsletter_segment": segment,
            "primary_metric": primary,
            "campaigns_sent": len(seg_campaigns),
            "emails_sent": emails_sent,
            "avg_open_rate": pd.to_numeric(seg_reports.get("open_rate", pd.Series(dtype=float)), errors="coerce").fillna(0).mean() if not seg_reports.empty else 0,
            "avg_click_rate": pd.to_numeric(seg_reports.get("click_rate", pd.Series(dtype=float)), errors="coerce").fillna(0).mean() if not seg_reports.empty else 0,
            "avg_click_to_open_rate": (unique_clicks / unique_opens) if unique_opens else 0,
            "total_clicks": total_clicks,
            "unique_clicks": unique_clicks,
            "unique_clicked_links": seg_clicks["url_canonical"].nunique() if not seg_clicks.empty and "url_canonical" in seg_clicks.columns else 0,
            "top_story_unique_clicks": top_story_clicks,
            "top_story_click_rate": (top_story_clicks / unique_opens) if unique_opens else 0,
            "magazine_site_unique_clicks": magazine_clicks,
            "event_link_unique_clicks": event_clicks,
            "unsubscribed": pd.to_numeric(seg_reports.get("unsubscribed", pd.Series(dtype=float)), errors="coerce").fillna(0).sum() if not seg_reports.empty else 0,
            "abuse_reports": pd.to_numeric(seg_reports.get("abuse_reports", pd.Series(dtype=float)), errors="coerce").fillna(0).sum() if not seg_reports.empty else 0,
        })
    return pd.DataFrame(rows, columns=columns)


def build_top_story_clicks(campaigns_df: pd.DataFrame, clicks_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "campaign_id", "send_time", "newsletter_segment", "subject_line",
        "top_story_url", "top_story_anchor_text", "top_story_unique_clicks",
        "top_story_total_clicks",
    ]
    if campaigns_df.empty or clicks_df.empty or "is_top_story" not in clicks_df.columns:
        return pd.DataFrame(columns=columns)
    campaigns = campaigns_df.copy()
    campaigns["newsletter_segment"] = campaigns.apply(infer_newsletter_segment, axis=1)
    top = clicks_df[clicks_df["is_top_story"].fillna(False).astype(bool)].copy()
    if top.empty:
        return pd.DataFrame(columns=columns)
    out = top.merge(
        campaigns[["campaign_id", "send_time", "newsletter_segment", "subject_line"]],
        on="campaign_id",
        how="left",
        suffixes=("", "_campaign"),
    )
    out = out.rename(columns={
        "url": "top_story_url",
        "anchor_text": "top_story_anchor_text",
        "unique_clicks": "top_story_unique_clicks",
        "total_clicks": "top_story_total_clicks",
    })
    out["top_story_unique_clicks"] = pd.to_numeric(out["top_story_unique_clicks"], errors="coerce").fillna(0)
    out["top_story_total_clicks"] = pd.to_numeric(out["top_story_total_clicks"], errors="coerce").fillna(0)
    grouped = out.groupby(
        ["campaign_id", "send_time", "newsletter_segment", "subject_line", "top_story_url"],
        as_index=False,
        dropna=False,
    ).agg(
        top_story_anchor_text=("top_story_anchor_text", "first"),
        top_story_unique_clicks=("top_story_unique_clicks", "sum"),
        top_story_total_clicks=("top_story_total_clicks", "sum"),
    )
    return grouped[[c for c in columns if c in grouped.columns]]


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


def chart_segment_primary_metrics(segment_df: pd.DataFrame):
    if segment_df.empty:
        fig, ax = plt.subplots(figsize=(12, 4.8))
        ax.text(0.5, 0.5, "No segment data for this period.", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "mailchimp_segment_primary_metrics.png")

    rows = []
    for _, row in segment_df.iterrows():
        segment = row["newsletter_segment"]
        if segment == "The Reporter":
            value = row.get("avg_open_rate", 0)
            label = "Open rate"
        elif segment == "Events":
            value = row.get("avg_click_to_open_rate", 0)
            label = "Click-to-open"
        elif segment == "CIM Magazine":
            value = row.get("avg_click_to_open_rate", 0)
            label = "Click-to-open"
        else:
            value = row.get("avg_click_rate", 0)
            label = "Click rate"
        rows.append({"segment": segment, "value": value, "label": label})
    plot_df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(12, 4.8))
    colors = [C_NAVY, C_TEAL, C_AMBER, C_SLATE][:len(plot_df)]
    bars = ax.barh(plot_df["segment"], plot_df["value"], color=colors)
    max_v = max(float(plot_df["value"].max()), 0.01)
    for bar, (_, row) in zip(bars, plot_df.iterrows()):
        ax.text(bar.get_width() + max_v * 0.02, bar.get_y() + bar.get_height() / 2, f"{row['label']}: {row['value']:.1%}", va="center", fontsize=8)
    ax.set_xlim(0, max_v * 1.35)
    _style_ax(ax, "Primary success metric by newsletter")
    fig.tight_layout()
    return _save(fig, "mailchimp_segment_primary_metrics.png")


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


def segment_readout(segment: str, segment_df: pd.DataFrame) -> str:
    if segment_df.empty or segment not in set(segment_df["newsletter_segment"]):
        return f"<p>No {html.escape(segment)} campaigns were sent in this period.</p>"
    row = segment_df[segment_df["newsletter_segment"] == segment].iloc[0]
    if segment == "The Reporter":
        body = (
            f"Primary read: open rate {_fmt_num(row['avg_open_rate'], pct=True)} because the subject line needs to draw readers into a utility-driven newsletter. "
            f"Top-story tracking: {_fmt_num(row['top_story_unique_clicks'])} unique clicks, {_fmt_num(row['top_story_click_rate'], pct=True)} of unique opens."
        )
    elif segment == "Events":
        body = (
            f"Primary read: click-through quality. Click rate {_fmt_num(row['avg_click_rate'], pct=True)} and click-to-open {_fmt_num(row['avg_click_to_open_rate'], pct=True)}. "
            f"Event-link unique clicks: {_fmt_num(row['event_link_unique_clicks'])}."
        )
    elif segment == "CIM Magazine":
        body = (
            f"Primary read: movement to CIM Magazine. Click-to-open {_fmt_num(row['avg_click_to_open_rate'], pct=True)} with {_fmt_num(row['magazine_site_unique_clicks'])} unique clicks to magazine URLs."
        )
    else:
        body = (
            f"General read: open rate {_fmt_num(row['avg_open_rate'], pct=True)}, click rate {_fmt_num(row['avg_click_rate'], pct=True)}, "
            f"{_fmt_num(row['unique_clicks'])} unique clicks."
        )
    return f"<p>{html.escape(body)}</p>"


def write_html(campaigns_df, reports_df, clicks_df, content_links_df, summary_df, segment_df, top_story_df, start_date, end_date):
    summary = summary_df.iloc[0].to_dict()
    chart_a = chart_campaign_rates(campaigns_df, reports_df)
    chart_b = chart_link_formats(clicks_df)
    chart_c = chart_segment_primary_metrics(segment_df)

    kpis = mm_kpi_grid(
        mm_kpi_card("Campaigns", summary["campaigns_sent"], None),
        mm_kpi_card("Emails Sent", summary["emails_sent"], None),
        mm_kpi_card("Avg Open Rate", summary["avg_open_rate"], None, is_pct=True),
        mm_kpi_card("Avg Click Rate", summary["avg_click_rate"], None, is_pct=True),
    )

    top_links = clicks_df.sort_values("unique_clicks", ascending=False) if not clicks_df.empty and "unique_clicks" in clicks_df.columns else clicks_df
    campaign_table = campaigns_df.merge(reports_df, on="campaign_id", how="left") if not campaigns_df.empty else pd.DataFrame()
    if "newsletter_segment_x" in campaign_table.columns:
        campaign_table["newsletter_segment"] = campaign_table["newsletter_segment_x"]
    elif "newsletter_segment_y" in campaign_table.columns:
        campaign_table["newsletter_segment"] = campaign_table["newsletter_segment_y"]
    elif "newsletter_segment" not in campaign_table.columns and not campaign_table.empty:
        campaign_table["newsletter_segment"] = campaign_table.apply(infer_newsletter_segment, axis=1)

    body = (
        f'<div class="section" style="padding-top:0;">{kpis}</div><hr class="rule-thick">'
        + mm_section("Executive Readout", mm_report_section(
            "<ul class=\"exec-bullets\">"
            f"<li>{_fmt_num(summary['total_clicks'])} total link clicks across {_fmt_num(summary['unique_clicked_links'])} unique clicked links.</li>"
            "<li>Use the linked-content table to identify which articles, resources, events, and landing pages deserve follow-up distribution.</li>"
            "<li>Subscriber-level activity is intentionally excluded; this report is aggregate and content-focused.</li>"
            "</ul>"
        ))
        + mm_section("Newsletter-Specific Readout", mm_report_section(
            mm_chart_wrap(str(chart_c), "Primary metrics by newsletter")
            + _table(
                segment_df,
                ["newsletter_segment", "primary_metric", "campaigns_sent", "emails_sent", "avg_open_rate", "avg_click_rate", "avg_click_to_open_rate", "top_story_unique_clicks", "magazine_site_unique_clicks", "event_link_unique_clicks"],
                {"newsletter_segment": "Newsletter", "primary_metric": "Primary metric", "campaigns_sent": "Campaigns", "emails_sent": "Emails", "avg_open_rate": "Open", "avg_click_rate": "Click", "avg_click_to_open_rate": "CTOR", "top_story_unique_clicks": "Top Story Clicks", "magazine_site_unique_clicks": "Magazine Clicks", "event_link_unique_clicks": "Event Clicks"},
                max_rows=10,
            )
        ))
        + mm_section("The Reporter", mm_report_section(
            segment_readout("The Reporter", segment_df)
            + _table(
                top_story_df[top_story_df["newsletter_segment"] == "The Reporter"] if not top_story_df.empty and "newsletter_segment" in top_story_df.columns else pd.DataFrame(),
                ["send_time", "subject_line", "top_story_url", "top_story_unique_clicks", "top_story_total_clicks"],
                {"send_time": "Sent", "subject_line": "Subject", "top_story_url": "Top Story URL", "top_story_unique_clicks": "Unique Clicks", "top_story_total_clicks": "Total Clicks"},
                max_rows=8,
            )
        ))
        + mm_section("Events Newsletter", mm_report_section(
            segment_readout("Events", segment_df)
            + _table(
                top_links[top_links["newsletter_segment"] == "Events"] if not top_links.empty and "newsletter_segment" in top_links.columns else pd.DataFrame(),
                ["url", "link_format", "unique_clicks", "total_clicks", "subject_line"],
                {"url": "URL", "link_format": "Format", "unique_clicks": "Unique Clicks", "total_clicks": "Total Clicks", "subject_line": "Campaign"},
                max_rows=12,
            )
        ))
        + mm_section("CIM Magazine Newsletter", mm_report_section(
            segment_readout("CIM Magazine", segment_df)
            + _table(
                top_links[top_links["newsletter_segment"] == "CIM Magazine"] if not top_links.empty and "newsletter_segment" in top_links.columns else pd.DataFrame(),
                ["url", "link_format", "unique_clicks", "total_clicks", "subject_line"],
                {"url": "URL", "link_format": "Format", "unique_clicks": "Unique Clicks", "total_clicks": "Total Clicks", "subject_line": "Campaign"},
                max_rows=12,
            )
        ))
        + mm_section("Campaign Performance", mm_report_section(
            mm_chart_wrap(str(chart_a), "Mailchimp campaign rates")
            + _table(
                campaign_table.sort_values("send_time", ascending=False) if not campaign_table.empty else campaign_table,
                ["send_time", "newsletter_segment", "subject_line", "emails_sent", "open_rate", "click_rate", "unique_clicks"],
                {"send_time": "Sent", "newsletter_segment": "Newsletter", "subject_line": "Subject", "emails_sent": "Emails", "open_rate": "Open", "click_rate": "Click", "unique_clicks": "Unique Clicks"},
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
            "unique_clicks", "newsletter_segment", "link_format",
        ])
        content_links_df = pd.DataFrame(columns=[
            "campaign_id", "url", "url_canonical", "link_position",
            "anchor_text", "is_top_story", "newsletter_segment",
        ])
        summary_df = build_summary(campaigns_df, reports_df, clicks_df)
        segment_df = build_segment_summary(campaigns_df, reports_df, clicks_df)
        top_story_df = build_top_story_clicks(campaigns_df, clicks_df)
        campaigns_df.to_csv("mailchimp_campaigns.csv", index=False)
        reports_df.to_csv("mailchimp_campaign_reports.csv", index=False)
        clicks_df.to_csv("mailchimp_link_clicks.csv", index=False)
        content_links_df.to_csv("mailchimp_content_links.csv", index=False)
        segment_df.to_csv("mailchimp_segment_summary.csv", index=False)
        top_story_df.to_csv("mailchimp_top_story_clicks.csv", index=False)
        summary_df.to_csv("mailchimp_weekly_summary.csv", index=False)
        write_html(campaigns_df, reports_df, clicks_df, content_links_df, summary_df, segment_df, top_story_df, start_date, end_date)
        upload_to_monday()
        print("Mailchimp Weekly Content Report - complete with empty artifacts", flush=True)
        return

    campaigns_df = fetch_campaigns(start_date, end_date)
    if not campaigns_df.empty:
        campaigns_df["newsletter_segment"] = campaigns_df.apply(infer_newsletter_segment, axis=1)
    reports_df, clicks_df, content_links_df = flatten_reports(campaigns_df) if not campaigns_df.empty else (
        pd.DataFrame(),
        pd.DataFrame(columns=["campaign_id", "url", "url_canonical", "total_clicks", "unique_clicks", "link_format"]),
        pd.DataFrame(columns=["campaign_id", "url", "url_canonical", "link_position", "anchor_text", "is_top_story", "newsletter_segment"]),
    )
    summary_df = build_summary(campaigns_df, reports_df, clicks_df)
    segment_df = build_segment_summary(campaigns_df, reports_df, clicks_df)
    top_story_df = build_top_story_clicks(campaigns_df, clicks_df)

    campaigns_df.to_csv("mailchimp_campaigns.csv", index=False)
    reports_df.to_csv("mailchimp_campaign_reports.csv", index=False)
    clicks_df.to_csv("mailchimp_link_clicks.csv", index=False)
    content_links_df.to_csv("mailchimp_content_links.csv", index=False)
    segment_df.to_csv("mailchimp_segment_summary.csv", index=False)
    top_story_df.to_csv("mailchimp_top_story_clicks.csv", index=False)
    summary_df.to_csv("mailchimp_weekly_summary.csv", index=False)

    write_html(campaigns_df, reports_df, clicks_df, content_links_df, summary_df, segment_df, top_story_df, start_date, end_date)
    upload_to_monday()
    print("Mailchimp Weekly Content Report - complete", flush=True)


if __name__ == "__main__":
    main()
