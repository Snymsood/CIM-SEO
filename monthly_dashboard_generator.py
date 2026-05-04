#!/usr/bin/env python3
"""
Monthly Dashboard Generator

Generates the complete 8-page HTML dashboard for monthly SEO reporting.
Follows the MM design system (Playfair Display, JetBrains Mono, Source Serif 4).
Embeds all charts as base64 data URIs for self-contained HTML.
"""

import base64
import html as _html
import pandas as pd
from datetime import date
from pathlib import Path

from pdf_report_formatter import format_pct_change

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400'
    '&family=Source Serif+4:ital,wght@0,300;0,400;0,600;1,400'
    '&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">'
)

# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _embed_chart_as_base64(chart_path):
    """Convert chart PNG to base64 data URI."""
    if not chart_path or not Path(chart_path).exists():
        return ""
    
    with open(chart_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/png;base64,{data}"


def _kpi_card(label, curr, prev, lower_better=False, is_pct=False, decimals=0):
    """Render one inverted KPI card matching the MM design system."""
    curr_f = float(curr) if curr else 0
    prev_f = float(prev) if prev else 0
    curr_str = f"{curr_f:.{decimals}%}" if is_pct else f"{curr_f:,.{decimals}f}"
    prev_str = f"{prev_f:.{decimals}%}" if is_pct else f"{prev_f:,.{decimals}f}"
    delta_str = format_pct_change(curr_f, prev_f)
    
    if delta_str == "-":
        delta_html = '<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">—</span>'
    else:
        is_pos = delta_str.startswith("+")
        good   = (is_pos and not lower_better) or (not is_pos and lower_better)
        bg, fg = ("#000", "#fff") if good else ("#fff", "#000")
        delta_html = (
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;font-weight:700;'
            f'padding:2px 8px;background:{bg};color:{fg};border:1px solid #000;">{_html.escape(delta_str)}</span>'
        )
    
    return f"""
<div style="background:#000;color:#fff;padding:24px 20px;position:relative;overflow:hidden;border-right:2px solid #fff;">
  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.15em;color:#999;margin-bottom:12px;">{_html.escape(label)}</div>
  <div style="font-family:'Playfair Display',Georgia,serif;font-size:36px;font-weight:700;color:#fff;line-height:1;margin-bottom:10px;">{_html.escape(curr_str)}</div>
  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#999;margin-bottom:8px;">prev {_html.escape(prev_str)}</div>
  {delta_html}
</div>"""


def _img_tag(path, alt="chart"):
    """Return an img tag with base64-embedded chart."""
    base64_data = _embed_chart_as_base64(path)
    if not base64_data:
        return ""
    
    return (
        f'<div style="width:100%;margin-bottom:24px;">'
        f'<img src="{base64_data}" alt="{_html.escape(alt)}" '
        f'style="width:100%;display:block;border:2px solid #000;">'
        f'</div>'
    )


def _chart_row_2(path_a, alt_a, path_b, alt_b):
    """Two charts side by side."""
    base64_a = _embed_chart_as_base64(path_a)
    base64_b = _embed_chart_as_base64(path_b)
    
    a = (f'<div style="width:calc(50% - 10px);display:inline-block;vertical-align:top;">'
         f'<img src="{base64_a}" alt="{_html.escape(alt_a)}" style="width:100%;display:block;border:2px solid #000;"></div>') if base64_a else ""
    b = (f'<div style="width:calc(50% - 10px);display:inline-block;vertical-align:top;margin-left:20px;">'
         f'<img src="{base64_b}" alt="{_html.escape(alt_b)}" style="width:100%;display:block;border:2px solid #000;"></div>') if base64_b else ""
    
    if not a and not b:
        return ""
    return f'<div style="margin-bottom:24px;">{a}{b}</div>'


def _section(title, content, section_id=""):
    """Wrap content in a titled section with thick rule."""
    id_attr = f' id="{section_id}"' if section_id else ""
    return f"""
<div style="padding:40px 0;"{id_attr}>
  <div style="font-family:'Playfair Display',Georgia,serif;font-size:11px;font-weight:700;
              text-transform:uppercase;letter-spacing:0.15em;color:#000;margin-bottom:24px;
              display:flex;align-items:center;gap:16px;">
    <span style="display:inline-block;width:8px;height:8px;background:#000;flex-shrink:0;"></span>
    {_html.escape(title)}
  </div>
  <div style="background:#fff;border:2px solid #000;padding:28px 32px;">
    {content}
  </div>
</div>
<hr style="border:none;border-top:4px solid #000;margin:0;">"""


def _exec_bullets(bullets):
    """Render executive summary bullets."""
    if not bullets:
        return '<p style="font-family:\'Source Serif 4\',Georgia,serif;font-size:14px;color:#94A3B8;">No insights available.</p>'
    
    items = "".join(
        f'<li style="font-family:\'Source Serif 4\',Georgia,serif;font-size:14px;color:#000;'
        f'line-height:1.7;padding:10px 0 10px 20px;border-bottom:1px solid #E5E5E5;'
        f'position:relative;list-style:none;">'
        f'<span style="position:absolute;left:0;color:#525252;font-family:\'JetBrains Mono\',monospace;">—</span>'
        f'{_html.escape(b)}</li>'
        for b in bullets
    )
    return f'<ul style="margin:0;padding:0;">{items}</ul>'


def _panel_label(text):
    """Render a section label with horizontal rule."""
    return (
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;text-transform:uppercase;'
        f'letter-spacing:0.15em;color:#525252;margin-bottom:16px;display:flex;align-items:center;gap:12px;">'
        f'{_html.escape(text)}'
        f'<span style="flex:1;height:1px;background:#E5E5E5;display:inline-block;"></span></div>'
    )


def _fmt_cell(val, col=""):
    """Format a single table cell value."""
    col = col.lower()
    try:
        f = float(val)
        if f == 0:
            return "-"
        if "rate" in col or "ctr" in col or "engagement" in col:
            return f"{f:.2%}"
        if "position" in col:
            return f"{f:.1f}"
        if "score" in col:
            return f"{f:.0f}"
        return f"{f:,.0f}"
    except (ValueError, TypeError):
        s = str(val)
        return s[:47] + "..." if len(s) > 50 else s


def _build_html_table(df, cols, headers):
    """Build a styled HTML table from a DataFrame."""
    if df.empty:
        return '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#94A3B8;">No data available.</p>'
    
    rows_html = ""
    for _, row in df.iterrows():
        cells = "".join(
            f'<td style="padding:9px 12px;border-bottom:1px solid #E5E5E5;font-family:\'JetBrains Mono\',monospace;font-size:10px;white-space:nowrap;">'
            f'{_html.escape(_fmt_cell(row.get(c, ""), c))}</td>'
            for c in cols
        )
        rows_html += f"<tr>{cells}</tr>"
    
    header_cells = "".join(
        f'<th style="padding:10px 12px;background:#000;color:#fff;font-family:\'JetBrains Mono\',monospace;'
        f'font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;text-align:left;">'
        f'{_html.escape(h)}</th>'
        for h in headers
    )
    
    return (
        f'<table style="width:100%;border-collapse:collapse;table-layout:fixed;">'
        f'<thead><tr>{header_cells}</tr></thead>'
        f'<tbody>{rows_html}</tbody></table>'
    )


def _table_of_contents():
    """Generate table of contents with anchor links."""
    return """
<nav style="background:#F8FAFC;border:2px solid #000;padding:24px 32px;margin:40px 0;">
  <div style="font-family:'Playfair Display',Georgia,serif;font-size:16px;font-weight:700;margin-bottom:16px;">Table of Contents</div>
  <ol style="font-family:'Source Serif 4',Georgia,serif;font-size:14px;line-height:2;margin:0;padding-left:20px;">
    <li><a href="#executive-overview" style="color:#212878;text-decoration:none;">Executive Overview</a></li>
    <li><a href="#traffic-trends" style="color:#212878;text-decoration:none;">Traffic Trends &amp; Patterns</a></li>
    <li><a href="#search-performance" style="color:#212878;text-decoration:none;">Search Performance Deep Dive</a></li>
    <li><a href="#content-performance" style="color:#212878;text-decoration:none;">Content Performance Analysis</a></li>
    <li><a href="#content-categories" style="color:#212878;text-decoration:none;">Content Category Performance</a></li>
    <li><a href="#technical-health" style="color:#212878;text-decoration:none;">Technical Health &amp; Speed</a></li>
    <li><a href="#link-health" style="color:#212878;text-decoration:none;">Link Health &amp; Internal Architecture</a></li>
    <li><a href="#ai-innovation" style="color:#212878;text-decoration:none;">AI &amp; Innovation Metrics</a></li>
    <li><a href="#channel-audience" style="color:#212878;text-decoration:none;">Channel &amp; Audience Insights</a></li>
    <li><a href="#detailed-data" style="color:#212878;text-decoration:none;">Detailed Data Tables</a></li>
  </ol>
</nav>
"""


# ══════════════════════════════════════════════════════════════════════════════
# MAIN DASHBOARD GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def generate_monthly_dashboard(bullets, chart_paths, data, kpis, date_range):
    """
    Build the complete 8-page HTML dashboard.
    
    Args:
        bullets: List of executive summary bullet points
        chart_paths: Dict mapping chart names to file paths
        data: Dict of DataFrames with all monthly data
        kpis: Dict of KPI values (current, previous)
        date_range: Dict with current_start, current_end, previous_start, previous_end
    
    Returns:
        str: Path to generated HTML file
    """
    print("=" * 80)
    print("MONTHLY DASHBOARD GENERATION - STARTING")
    print("=" * 80)
    
    # Format dates
    current_month = date_range["current_start"].strftime("%B %Y")
    previous_month = date_range["previous_start"].strftime("%B %Y")
    today = date.today().strftime("%B %d, %Y")
    
    print(f"\nCurrent period:  {current_month}")
    print(f"Previous period: {previous_month}")
    print(f"Generated:       {today}")
    
    # Build KPI grid — 2 rows × 8 columns = 16 cards covering all data sources
    print("\n[1/9] Building KPI grid...")
    kpi_cards_row1 = (
        _kpi_card("Sessions",        kpis["sessions"]["curr"],        kpis["sessions"]["prev"]) +
        _kpi_card("Active Users",    kpis["users"]["curr"],           kpis["users"]["prev"]) +
        _kpi_card("Engagement Rate", kpis["engagement_rate"]["curr"], kpis["engagement_rate"]["prev"], is_pct=True, decimals=1) +
        _kpi_card("Avg Duration",    kpis["avg_duration"]["curr"],    kpis["avg_duration"]["prev"],    decimals=0) +
        _kpi_card("Bounce Rate",     kpis["bounce_rate"]["curr"],     kpis["bounce_rate"]["prev"],     lower_better=True, is_pct=True, decimals=1) +
        _kpi_card("Events/Session",  kpis["events_per_session"]["curr"], kpis["events_per_session"]["prev"], decimals=1) +
        _kpi_card("GSC Clicks",      kpis["clicks"]["curr"],          kpis["clicks"]["prev"]) +
        _kpi_card("GSC Impressions", kpis["impressions"]["curr"],     kpis["impressions"]["prev"])
    )
    kpi_cards_row2 = (
        _kpi_card("CTR",                  kpis["ctr"]["curr"],                          kpis["ctr"]["prev"],                          is_pct=True, decimals=2) +
        _kpi_card("Avg Position",         kpis["avg_position"]["curr"],                 kpis["avg_position"]["prev"],                 lower_better=True, decimals=1) +
        _kpi_card("Mobile Speed",         kpis.get("mobile_score", {}).get("curr", 0),  kpis.get("mobile_score", {}).get("prev", 0),  decimals=0) +
        _kpi_card("CWV Pass Rate",        kpis.get("cwv_pass_rate", {}).get("curr", 0), kpis.get("cwv_pass_rate", {}).get("prev", 0), is_pct=True, decimals=0) +
        _kpi_card("Broken Links",         kpis.get("broken_links", {}).get("curr", 0),  kpis.get("broken_links", {}).get("prev", 0),  lower_better=True) +
        _kpi_card("Internal Link Pages",  kpis.get("internal_link_pages", {}).get("curr", 0), kpis.get("internal_link_pages", {}).get("prev", 0)) +
        _kpi_card("AI Readiness",         kpis.get("ai_readiness_avg", {}).get("curr", 0), kpis.get("ai_readiness_avg", {}).get("prev", 0), decimals=2) +
        _kpi_card("Refresh Candidates",   kpis.get("content_refresh_candidates", {}).get("curr", 0), kpis.get("content_refresh_candidates", {}).get("prev", 0), lower_better=True)
    )

    kpi_grid = (
        f'<div style="display:grid;grid-template-columns:repeat(8,1fr);border:2px solid #000;margin-bottom:2px;">'
        f'{kpi_cards_row1}</div>'
        f'<div style="display:grid;grid-template-columns:repeat(8,1fr);border:2px solid #000;border-top:none;margin-bottom:0;">'
        f'{kpi_cards_row2}</div>'
    )
    
    # Build tables
    print("[2/9] Building data tables...")
    ga4_pages   = data.get("ga4_pages",   pd.DataFrame())
    gsc_queries = data.get("gsc_queries", pd.DataFrame())
    gsc_pages   = data.get("gsc_pages",   pd.DataFrame())
    broken_link_data     = data.get("broken_links",       pd.DataFrame())
    content_category_data = data.get("content_categories", pd.DataFrame())

    # GA4 landing pages table
    page_col = "landingPage" if "landingPage" in ga4_pages.columns else (ga4_pages.columns[0] if not ga4_pages.empty else "page")
    ga4_tbl = _build_html_table(
        ga4_pages.head(25),
        [page_col, "sessions", "activeUsers", "engagementRate"],
        ["Landing Page", "Sessions", "Users", "Engagement Rate"]
    )

    # GSC queries table
    q_col   = "query"              if "query"              in gsc_queries.columns else (gsc_queries.columns[0] if not gsc_queries.empty else "query")
    c_col   = "clicks_current"     if "clicks_current"     in gsc_queries.columns else "clicks"
    i_col   = "impressions_current"if "impressions_current"in gsc_queries.columns else "impressions"
    p_col   = "position_current"   if "position_current"   in gsc_queries.columns else "position"
    ctr_col = "ctr_current"        if "ctr_current"        in gsc_queries.columns else "ctr"
    gsc_tbl = _build_html_table(
        gsc_queries.head(25),
        [q_col, c_col, i_col, ctr_col, p_col],
        ["Query", "Clicks", "Impressions", "CTR", "Position"]
    )

    # GSC pages table
    page_col_gsc = "page"               if "page"               in gsc_pages.columns else (gsc_pages.columns[0] if not gsc_pages.empty else "page")
    c_col_gsc    = "clicks_current"     if "clicks_current"     in gsc_pages.columns else "clicks"
    i_col_gsc    = "impressions_current"if "impressions_current"in gsc_pages.columns else "impressions"
    p_col_gsc    = "position_current"   if "position_current"   in gsc_pages.columns else "position"
    gsc_pages_tbl = _build_html_table(
        gsc_pages.head(25),
        [page_col_gsc, c_col_gsc, i_col_gsc, p_col_gsc],
        ["Page", "Clicks", "Impressions", "Position"]
    )

    # Broken links issues table (top 25 broken only)
    broken_issues_tbl = '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#94A3B8;">No broken link data available.</p>'
    if not broken_link_data.empty and "issue_type" in broken_link_data.columns:
        broken_df = broken_link_data[broken_link_data["issue_type"] == "broken"].head(25)
        if not broken_df.empty:
            src_col = "source_url" if "source_url" in broken_df.columns else broken_df.columns[0]
            tgt_col = "target_url" if "target_url" in broken_df.columns else broken_df.columns[1]
            broken_issues_tbl = _build_html_table(
                broken_df,
                [src_col, tgt_col, "status_code"],
                ["Source Page", "Broken Target", "Status"]
            )

    # Content category table
    cat_tbl = '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#94A3B8;">No content category data available.</p>'
    if not content_category_data.empty and "category" in content_category_data.columns:
        cat_cols    = [c for c in ["category", "sessions", "clicks", "impressions", "engagement_rate"] if c in content_category_data.columns]
        cat_headers = {"category": "Category", "sessions": "Sessions", "clicks": "Clicks",
                       "impressions": "Impressions", "engagement_rate": "Eng Rate"}
        cat_tbl = _build_html_table(
            content_category_data.sort_values("sessions", ascending=False) if "sessions" in content_category_data.columns else content_category_data,
            cat_cols,
            [cat_headers.get(c, c) for c in cat_cols]
        )
    
    # Build HTML body
    print("[3/9] Building HTML structure...")
    body = f"""
<header style="background:#000;color:#fff;padding:40px 48px;margin:0 -40px 0;position:relative;overflow:hidden;">
  <div style="font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:0.2em;color:#999;margin-bottom:12px;">CIM SEO Intelligence</div>
  <h1 style="font-family:'Playfair Display',Georgia,serif;font-size:clamp(28px,4vw,56px);font-weight:900;line-height:1;letter-spacing:-0.02em;color:#fff;margin-bottom:16px;">Monthly SEO<br>Master Report</h1>
  <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#666;letter-spacing:0.05em;">
    <span style="display:inline-block;width:24px;height:2px;background:#fff;vertical-align:middle;margin-right:16px;"></span>
    {current_month} vs {previous_month} &bull; Generated {today}
  </div>
</header>
<hr style="border:none;border-top:4px solid #000;margin:0;">

{_table_of_contents()}

<div id="executive-overview" style="padding:40px 0;">
  {kpi_grid}
</div>
<hr style="border:none;border-top:4px solid #000;margin:0;">

{_section("Executive Summary", _panel_label("Cross-Channel Analysis") + _exec_bullets(bullets), "executive-summary")}

{_section("Traffic Trends & Patterns",
    _img_tag(chart_paths.get("traffic_trend"),       "Monthly traffic trend") +
    _img_tag(chart_paths.get("channel_performance"), "Channel performance") +
    _img_tag(chart_paths.get("device_distribution"), "Device distribution"),
    "traffic-trends"
)}

{_section("Search Performance Deep Dive",
    _img_tag(chart_paths.get("search_funnel"),         "Search funnel") +
    _img_tag(chart_paths.get("top_movers_queries"),    "Top query movers") +
    _img_tag(chart_paths.get("ctr_by_position"),       "CTR by position") +
    _img_tag(chart_paths.get("top_queries"),           "Top queries") +
    _img_tag(chart_paths.get("top_pages"),             "Top pages") +
    _img_tag(chart_paths.get("impressions_vs_clicks"), "Impressions vs clicks"),
    "search-performance"
)}

{_section("Content Performance Analysis",
    _img_tag(chart_paths.get("ga4_landing_pages"),     "GA4 landing pages") +
    _img_tag(chart_paths.get("engagement_by_channel"), "Engagement by channel") +
    _img_tag(chart_paths.get("sessions_vs_clicks"),    "Landing page efficiency"),
    "content-performance"
)}

{_section("Content Category Performance",
    _img_tag(chart_paths.get("content_category_sessions"),   "Sessions by content category") +
    _img_tag(chart_paths.get("content_category_engagement"), "Content category ecosystem map"),
    "content-categories"
)}

{_section("Technical Health & Speed",
    _img_tag(chart_paths.get("core_web_vitals"),           "Core Web Vitals") +
    _img_tag(chart_paths.get("performance_distribution"),  "Performance distribution") +
    _img_tag(chart_paths.get("speed_traffic_correlation"), "Speed vs traffic") +
    _img_tag(chart_paths.get("technical_issues"),          "Technical issues"),
    "technical-health"
)}

{_section("Link Health & Internal Architecture",
    _img_tag(chart_paths.get("broken_link_issue_breakdown"), "Broken link issue breakdown") +
    _img_tag(chart_paths.get("broken_link_domain_health"),   "Broken links by domain") +
    _img_tag(chart_paths.get("internal_link_distribution"),  "Internal link distribution"),
    "link-health"
)}

{_section("AI & Innovation Metrics",
    _img_tag(chart_paths.get("ai_readiness"),     "AI readiness") +
    _img_tag(chart_paths.get("structured_data"),  "Structured data coverage") +
    _img_tag(chart_paths.get("content_freshness"),"Content freshness"),
    "ai-innovation"
)}

{_section("Channel & Audience Insights",
    _img_tag(chart_paths.get("device_comparison"),  "Device comparison") +
    _img_tag(chart_paths.get("channel_efficiency"), "Channel efficiency") +
    _img_tag(chart_paths.get("engagement_trend"),   "Engagement trend"),
    "channel-audience"
)}

{_section("Detailed Data Tables",
    _panel_label("Top 25 Landing Pages (GA4)") + ga4_tbl +
    "<br><br>" +
    _panel_label("Top 25 Search Queries (GSC)") + gsc_tbl +
    "<br><br>" +
    _panel_label("Top 25 Landing Pages (GSC)") + gsc_pages_tbl +
    "<br><br>" +
    _panel_label("Content Category Performance") + cat_tbl +
    "<br><br>" +
    _panel_label("Top 25 Broken Links (404/410)") + broken_issues_tbl,
    "detailed-data"
)}

<hr style="border:none;border-top:4px solid #000;margin:0;">
<footer style="padding:32px 0;display:flex;justify-content:space-between;align-items:center;">
  <span style="font-family:'Playfair Display',Georgia,serif;font-size:13px;font-weight:700;letter-spacing:0.05em;">CIM SEO Intelligence</span>
  <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#525252;text-transform:uppercase;letter-spacing:0.12em;">{current_month} Report &bull; Generated {today}</span>
</footer>
"""
    
    # Build complete HTML document
    print("[4/9] Assembling complete HTML...")
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CIM SEO Monthly Report — {current_month}</title>
{FONT_LINK}
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ background: #fff; scroll-behavior: smooth; }}
body {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 14px;
    color: #000;
    background: #fff;
    line-height: 1.625;
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 40px 80px;
}}
@media (max-width: 768px) {{
    body {{ padding: 0 20px 60px; }}
}}
a {{ color: #212878; transition: color 0.2s; }}
a:hover {{ color: #2A9D8F; }}
</style>
</head>
<body>
{body}
</body>
</html>"""
    
    # Save HTML file
    print("[5/9] Saving HTML file...")
    output_path = Path("monthly_dashboard.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    
    file_size = output_path.stat().st_size / (1024 * 1024)  # MB
    print(f"✓ Dashboard saved: {output_path} ({file_size:.2f} MB)")
    
    print("\n" + "=" * 80)
    print("MONTHLY DASHBOARD GENERATION - COMPLETE")
    print("=" * 80)
    
    return output_path


if __name__ == "__main__":
    # Test with sample data
    print("This script should be called from monthly_master_report.py")
    print("For testing, run: python monthly_master_report.py")
