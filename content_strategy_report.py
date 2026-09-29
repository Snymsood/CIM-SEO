#!/usr/bin/env python3
"""Content Strategy report for the Web Content Manager.

This report converts existing SEO, analytics, content audit, internal linking,
and Mailchimp outputs into a content-management view: which content performs,
which formats work, where distribution is succeeding, and what should happen
next.
"""

from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import urlparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

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


MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID") or os.getenv("MONDAY_CONTENT_STRATEGY_ITEM_ID")
CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

C_NAVY = "#212878"
C_TEAL = "#2A9D8F"
C_CORAL = "#E76F51"
C_AMBER = "#D97706"
C_GREEN = "#059669"
C_SLATE = "#6C757D"
C_BORDER = "#E2E8F0"


def _load(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _num(series, default=0):
    return pd.to_numeric(series, errors="coerce").fillna(default)


def infer_category(url: str) -> str:
    lower = str(url).lower()
    if "magazine.cim.org" in lower:
        return "Magazine"
    if "convention.cim.org" in lower or "/events" in lower or "/calendar" in lower:
        return "Events"
    if "mrmr.cim.org" in lower or "/technical-resources" in lower or "/library" in lower:
        return "Technical Library"
    if "memo.cim.org" in lower:
        return "Regional News"
    if "/professional-development" in lower or "/short-courses" in lower:
        return "Education"
    if "/membership" in lower:
        return "Membership"
    if "/scholarships" in lower or "/student" in lower:
        return "Student/Scholarships"
    if "/news" in lower or "/press-releases" in lower:
        return "News/Press"
    if "/awards" in lower:
        return "Awards"
    if lower.rstrip("/") in {"https://www.cim.org", "https://cim.org"}:
        return "Homepage"
    return "Other"


def infer_format(url: str) -> str:
    lower = str(url).lower()
    path = urlparse(lower).path
    if path.endswith(".pdf"):
        return "PDF/resource"
    if "magazine.cim.org" in lower:
        return "Magazine article"
    if "convention.cim.org" in lower or "/events" in lower:
        return "Event page"
    if "/news" in lower or "/press" in lower:
        return "News"
    if "/professional-development" in lower or "/short-courses" in lower:
        return "Education page"
    if "/membership" in lower:
        return "Membership page"
    if "/library" in lower or "/technical-resources" in lower or "mrmr.cim.org" in lower:
        return "Technical resource"
    if lower.rstrip("/") in {"https://www.cim.org", "https://cim.org"}:
        return "Homepage"
    return "Web page"


def _canonical_series(df: pd.DataFrame, source_col: str, target_col: str = "page_canonical") -> pd.DataFrame:
    work = df.copy()
    if source_col in work.columns:
        work[target_col] = work[source_col].apply(canonicalize_url)
    return work


def build_gsc_page_signals() -> pd.DataFrame:
    gsc = _load("tracked_pages_comparison.csv")
    if gsc.empty:
        gsc = _load("weekly_pages_comparison.csv")
    if gsc.empty:
        return pd.DataFrame(columns=["page_canonical"])

    page_col = "page" if "page" in gsc.columns else gsc.columns[0]
    gsc = _canonical_series(gsc, page_col)
    rename = {
        "clicks_current": "gsc_clicks",
        "clicks": "gsc_clicks",
        "impressions_current": "gsc_impressions",
        "impressions": "gsc_impressions",
        "ctr_current": "gsc_ctr",
        "ctr": "gsc_ctr",
        "position_current": "gsc_position",
        "position": "gsc_position",
        "clicks_change": "gsc_clicks_change",
        "impressions_change": "gsc_impressions_change",
    }
    keep = ["page_canonical"]
    for old, new in rename.items():
        if old in gsc.columns:
            gsc[new] = _num(gsc[old])
            keep.append(new)
    return gsc[keep].groupby("page_canonical", as_index=False).sum(numeric_only=True)


def build_ga4_page_signals() -> pd.DataFrame:
    ga4 = _load("ga4_pages_comparison.csv")
    if ga4.empty:
        ga4 = _load("ga4_top_landing_pages.csv")
    if ga4.empty:
        return pd.DataFrame(columns=["page_canonical"])

    page_col = "landingPage" if "landingPage" in ga4.columns else ga4.columns[0]
    ga4 = _canonical_series(ga4, page_col)
    rename = {
        "sessions_current": "ga4_sessions",
        "sessions": "ga4_sessions",
        "activeUsers_current": "ga4_active_users",
        "activeUsers": "ga4_active_users",
        "engagementRate_current": "ga4_engagement_rate",
        "engagementRate": "ga4_engagement_rate",
        "averageSessionDuration_current": "ga4_avg_duration",
        "averageSessionDuration": "ga4_avg_duration",
        "sessions_change": "ga4_sessions_change",
    }
    keep = ["page_canonical"]
    for old, new in rename.items():
        if old in ga4.columns:
            ga4[new] = _num(ga4[old])
            keep.append(new)
    aggregations = {col: "sum" for col in keep if col != "page_canonical"}
    for col in ("ga4_engagement_rate", "ga4_avg_duration"):
        if col in aggregations:
            aggregations[col] = "mean"
    return ga4[keep].groupby("page_canonical", as_index=False).agg(aggregations)


def build_mailchimp_signals() -> pd.DataFrame:
    clicks = _load("mailchimp_link_clicks.csv")
    if clicks.empty or "url_canonical" not in clicks.columns:
        return pd.DataFrame(columns=["page_canonical"])

    clicks["page_canonical"] = clicks["url_canonical"].fillna("").astype(str)
    clicks["email_unique_clicks"] = _num(clicks.get("unique_clicks", 0))
    clicks["email_total_clicks"] = _num(clicks.get("total_clicks", 0))
    grouped = clicks.groupby("page_canonical", as_index=False).agg(
        email_unique_clicks=("email_unique_clicks", "sum"),
        email_total_clicks=("email_total_clicks", "sum"),
        mailchimp_campaigns=("campaign_id", "nunique"),
        mailchimp_subjects=("subject_line", lambda s: " | ".join(dict.fromkeys([str(x) for x in s.dropna().head(3)]))),
    )
    return grouped


def build_internal_link_signals() -> pd.DataFrame:
    internal = _load("internal_linking_page_summary.csv")
    if internal.empty:
        return pd.DataFrame(columns=["page_canonical"])
    page_col = "url" if "url" in internal.columns else "page" if "page" in internal.columns else internal.columns[0]
    internal = _canonical_series(internal, page_col)
    for col in ["outlinks", "inlinks", "generic_anchor_links"]:
        if col in internal.columns:
            internal[col] = _num(internal[col])
    keep = [c for c in ["page_canonical", "outlinks", "inlinks", "generic_anchor_links"] if c in internal.columns]
    return internal[keep].groupby("page_canonical", as_index=False).sum(numeric_only=True)


def build_content_audit_signals() -> pd.DataFrame:
    audit = _load("content_audit_candidates.csv")
    if audit.empty:
        return pd.DataFrame(columns=["page_canonical"])
    page_col = "page" if "page" in audit.columns else audit.columns[0]
    audit = _canonical_series(audit, page_col)
    keep = ["page_canonical"]
    for col in ["recommended_action", "reason", "low_performance_score"]:
        if col in audit.columns:
            keep.append(col)
    return audit[keep].drop_duplicates("page_canonical")


def build_strategy_scorecard() -> pd.DataFrame:
    frames = [
        build_gsc_page_signals(),
        build_ga4_page_signals(),
        build_mailchimp_signals(),
        build_internal_link_signals(),
        build_content_audit_signals(),
    ]

    scorecard = pd.DataFrame(columns=["page_canonical"])
    for frame in frames:
        if frame.empty or "page_canonical" not in frame.columns:
            continue
        if scorecard.empty:
            scorecard = frame.copy()
        else:
            scorecard = scorecard.merge(frame, on="page_canonical", how="outer")

    if scorecard.empty:
        return scorecard

    for col in [
        "gsc_clicks", "gsc_impressions", "gsc_ctr", "gsc_position",
        "ga4_sessions", "ga4_engagement_rate", "ga4_avg_duration",
        "email_unique_clicks", "email_total_clicks", "mailchimp_campaigns",
        "inlinks", "outlinks", "low_performance_score",
    ]:
        if col not in scorecard.columns:
            scorecard[col] = 0
        scorecard[col] = _num(scorecard[col])

    scorecard["category"] = scorecard["page_canonical"].apply(infer_category)
    scorecard["content_format"] = scorecard["page_canonical"].apply(infer_format)

    def pct_rank(col):
        if scorecard[col].sum() == 0:
            return pd.Series([0] * len(scorecard), index=scorecard.index)
        return scorecard[col].rank(pct=True).fillna(0)

    visibility = pct_rank("gsc_impressions") * 35 + pct_rank("gsc_clicks") * 20
    engagement = pct_rank("ga4_sessions") * 20 + scorecard["ga4_engagement_rate"].clip(0, 1) * 15
    distribution = pct_rank("email_unique_clicks") * 20 + pct_rank("inlinks") * 10
    risk_penalty = scorecard["low_performance_score"].clip(0, 100) * 0.25

    scorecard["strategy_score"] = (visibility + engagement + distribution - risk_penalty).clip(0, 100).round(1)

    def classify(row):
        if row["email_unique_clicks"] > 0 and row["ga4_engagement_rate"] < 0.35:
            return "Email interest, weak on-site engagement"
        if row["gsc_impressions"] >= 100 and row["gsc_ctr"] < 0.025:
            return "Search visibility, low CTR"
        if row["strategy_score"] >= 70 and row["ga4_engagement_rate"] >= 0.45:
            return "Content champion"
        if row["email_unique_clicks"] == 0 and row["gsc_impressions"] > 200:
            return "Distribution gap"
        if row["low_performance_score"] >= 60:
            return "Refresh candidate"
        return "Monitor"

    scorecard["strategy_status"] = scorecard.apply(classify, axis=1)
    scorecard = scorecard.sort_values("strategy_score", ascending=False)
    return scorecard


def build_opportunities(scorecard: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if scorecard.empty:
        return pd.DataFrame(columns=["priority", "page", "content_format", "category", "opportunity", "recommended_action", "evidence"])

    for _, row in scorecard.iterrows():
        page = row["page_canonical"]
        status = row["strategy_status"]
        action = None
        if status == "Search visibility, low CTR":
            action = "Rewrite title/meta and align intro copy with the query promise."
        elif status == "Email interest, weak on-site engagement":
            action = "Review landing-page layout, CTA clarity, and above-the-fold relevance for email visitors."
        elif status == "Distribution gap":
            action = "Add this page to newsletter, homepage module, or related-content placements."
        elif status == "Refresh candidate":
            action = "Refresh content, improve structure, and validate whether it should stay in active rotation."
        elif status == "Content champion":
            action = "Repurpose into newsletter, social, homepage, or related-resource placements."

        if not action:
            continue
        rows.append({
            "priority": round(float(row["strategy_score"]), 1),
            "page": page,
            "content_format": row["content_format"],
            "category": row["category"],
            "opportunity": status,
            "recommended_action": action,
            "evidence": (
                f"{row['gsc_impressions']:,.0f} impressions, {row['gsc_clicks']:,.0f} search clicks, "
                f"{row['ga4_sessions']:,.0f} sessions, {row['email_unique_clicks']:,.0f} email clicks"
            ),
        })
    return pd.DataFrame(rows).sort_values("priority", ascending=False).head(40)


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


def chart_format_performance(scorecard: pd.DataFrame):
    if scorecard.empty:
        fig, ax = plt.subplots(figsize=(12, 4.8))
        ax.text(0.5, 0.5, "No content strategy data available.", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "content_strategy_format_performance.png")
    grouped = scorecard.groupby("content_format").agg(
        sessions=("ga4_sessions", "sum"),
        search_clicks=("gsc_clicks", "sum"),
        email_clicks=("email_unique_clicks", "sum"),
    ).sort_values("sessions")
    fig, ax = plt.subplots(figsize=(12, 5.2))
    ax.barh(grouped.index, grouped["sessions"], color=C_NAVY, label="Sessions")
    ax.barh(grouped.index, grouped["search_clicks"], color=C_TEAL, left=grouped["sessions"], label="Search clicks")
    ax.barh(grouped.index, grouped["email_clicks"], color=C_AMBER, left=grouped["sessions"] + grouped["search_clicks"], label="Email clicks")
    ax.legend(frameon=False, fontsize=8)
    _style_ax(ax, "Performance by content format")
    fig.tight_layout()
    return _save(fig, "content_strategy_format_performance.png")


def chart_strategy_status(scorecard: pd.DataFrame):
    if scorecard.empty:
        fig, ax = plt.subplots(figsize=(12, 4.8))
        ax.text(0.5, 0.5, "No content strategy data available.", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "content_strategy_status.png")
    counts = scorecard["strategy_status"].value_counts().sort_values()
    colors = [C_GREEN if "champion" in idx.lower() else C_CORAL if "weak" in idx.lower() or "refresh" in idx.lower() else C_AMBER for idx in counts.index]
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.barh(counts.index, counts.values, color=colors)
    max_v = max(counts.max(), 1)
    for i, value in enumerate(counts.values):
        ax.text(value + max_v * 0.01, i, f"{value:,.0f}", va="center", fontsize=8)
    _style_ax(ax, "Content strategy statuses")
    fig.tight_layout()
    return _save(fig, "content_strategy_status.png")


def _table(df: pd.DataFrame, cols: list[str], labels: dict[str, str], max_rows=20) -> str:
    if df.empty:
        return "<p>No rows to display.</p>"
    rows = []
    for _, row in df.head(max_rows).iterrows():
        cells = []
        for col in cols:
            value = row.get(col, "")
            if col in {"page", "page_canonical"} and str(value).startswith("http"):
                value = f'<a href="{html.escape(str(value), quote=True)}">{html.escape(short_url(str(value), 76))}</a>'
            elif col in {"ga4_engagement_rate", "gsc_ctr"}:
                value = html.escape(_fmt_num(value, pct=True))
            elif col in {"strategy_score", "priority"}:
                value = html.escape(_fmt_num(value, 1))
            elif isinstance(value, (int, float)):
                value = html.escape(_fmt_num(value))
            else:
                value = html.escape(str(value))
            cells.append(f"<td>{value}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    heads = "".join(f"<th>{html.escape(labels.get(col, col))}</th>" for col in cols)
    return f"<table><thead><tr>{heads}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def write_html(scorecard: pd.DataFrame, opportunities: pd.DataFrame, start_date, end_date):
    chart_a = chart_format_performance(scorecard)
    chart_b = chart_strategy_status(scorecard)
    total_pages = len(scorecard)
    champions = int((scorecard["strategy_status"] == "Content champion").sum()) if not scorecard.empty else 0
    email_pages = int((scorecard["email_unique_clicks"] > 0).sum()) if not scorecard.empty else 0
    avg_score = float(scorecard["strategy_score"].mean()) if not scorecard.empty else 0

    kpis = mm_kpi_grid(
        mm_kpi_card("Pages Scored", total_pages, None),
        mm_kpi_card("Champions", champions, None),
        mm_kpi_card("Email-Supported Pages", email_pages, None),
        mm_kpi_card("Avg Strategy Score", avg_score, None, decimals=1),
    )

    body = (
        f'<div class="section" style="padding-top:0;">{kpis}</div><hr class="rule-thick">'
        + mm_section("Manager Readout", mm_report_section(
            "<ul class=\"exec-bullets\">"
            "<li>Use this report to decide what to refresh, promote, repurpose, or monitor.</li>"
            "<li>Scores blend search visibility, on-site engagement, email demand, and internal-link support.</li>"
            "<li>Mailchimp data is included when campaign link-click outputs are available for the same run.</li>"
            "</ul>"
        ))
        + mm_section("Format And Status", mm_report_section(
            mm_chart_wrap(str(chart_a), "Content format performance")
            + mm_chart_wrap(str(chart_b), "Content strategy statuses")
        ))
        + mm_section("Recommended Actions", mm_report_section(
            _table(
                opportunities,
                ["priority", "page", "content_format", "category", "opportunity", "recommended_action", "evidence"],
                {"priority": "Score", "page": "Page", "content_format": "Format", "category": "Category", "opportunity": "Opportunity", "recommended_action": "Action", "evidence": "Evidence"},
                max_rows=25,
            )
        ))
        + mm_section("Top Content Scorecard", mm_report_section(
            _table(
                scorecard,
                ["strategy_score", "page_canonical", "content_format", "category", "strategy_status", "gsc_impressions", "gsc_clicks", "ga4_sessions", "email_unique_clicks", "inlinks"],
                {"strategy_score": "Score", "page_canonical": "Page", "content_format": "Format", "category": "Category", "strategy_status": "Status", "gsc_impressions": "Impr.", "gsc_clicks": "Search Clicks", "ga4_sessions": "Sessions", "email_unique_clicks": "Email Clicks", "inlinks": "Inlinks"},
                max_rows=30,
            )
        ))
    )

    doc = mm_html_shell(
        title="Content Strategy Report",
        eyebrow="CIM Content Intelligence",
        headline="Content Strategy\nReport",
        meta_line=f"{start_date} to {end_date}",
        body_content=body,
    )
    Path("content_strategy_report.html").write_text(doc, encoding="utf-8")
    generate_self_contained_html("content_strategy_report.html", "content_strategy_report_final.html")


def upload_to_monday():
    upload_html_to_monday(
        "content_strategy_report_final.html",
        "content-strategy-report.html",
        body_text="Content Strategy report attached as self-contained HTML.",
        api_token=MONDAY_API_TOKEN,
        item_id=MONDAY_ITEM_ID,
    )


def main():
    print("Content Strategy Report - starting", flush=True)
    start_date, end_date, _, _ = get_weekly_date_windows()
    scorecard = build_strategy_scorecard()
    opportunities = build_opportunities(scorecard)

    scorecard.to_csv("content_strategy_scorecard.csv", index=False)
    opportunities.to_csv("content_strategy_opportunities.csv", index=False)
    write_html(scorecard, opportunities, start_date, end_date)
    upload_to_monday()
    print("Content Strategy Report - complete", flush=True)


if __name__ == "__main__":
    main()
