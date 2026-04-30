import asyncio
import aiohttp
from datetime import date
from openai import OpenAI
import pandas as pd
import numpy as np
import requests
import os
import html as _html
import matplotlib
import matplotlib.patches as mpatches

from google_sheets_db import append_to_sheet
from pdf_report_formatter import format_num, format_delta
from html_report_utils import (
    mm_html_shell, mm_kpi_card, mm_kpi_grid, mm_section, mm_report_section,
    mm_col_header, mm_chart_wrap, mm_chart_row_2, mm_exec_bullets,
    generate_self_contained_html, upload_html_to_monday,
)
from seo_utils import short_url

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# Brand colour palette — never use raw hex strings inside functions
C_NAVY   = "#212878"   # Primary brand, bars, table headers
C_TEAL   = "#2A9D8F"   # Secondary accent, gainers, desktop bars
C_CORAL  = "#E76F51"   # Negative/losers, declining metrics
C_SLATE  = "#6C757D"   # Previous-period bars, neutral elements
C_GREEN  = "#059669"   # Positive deltas, good performance
C_RED    = "#DC2626"   # Negative deltas, critical issues
C_AMBER  = "#D97706"   # Warnings, medium-priority items
C_BORDER = "#E2E8F0"   # Borders, grid lines, dividers
C_LIGHT  = "#F1F5F9"   # Alternate row backgrounds, panel fills

# CWV field-data thresholds (ms / score)
TTFB_WARN_MS  = 600    # Google's "needs improvement" threshold
TTFB_POOR_MS  = 1800   # Google's "poor" threshold
LCP_GOOD_MS   = 2500
LCP_POOR_MS   = 4000
INP_GOOD_MS   = 200
INP_POOR_MS   = 500

# Opportunity audit keys to extract (estimated savings)
OPPORTUNITY_AUDITS = {
    "unused-javascript":        "Unused JavaScript",
    "unused-css-rules":         "Unused CSS",
    "render-blocking-resources":"Render-Blocking Resources",
    "uses-optimized-images":    "Unoptimised Images",
    "uses-responsive-images":   "Oversized Images",
    "offscreen-images":         "Offscreen Images",
}

PAGESPEED_API_KEY = os.getenv("PAGESPEED_API_KEY")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN  = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID    = os.getenv("MONDAY_ITEM_ID")

TRACKED_PAGES_FILE = "tracked_speed_pages.csv"
SNAPSHOT_FILE      = "site_speed_latest_snapshot.csv"
HISTORY_FILE       = "site_speed_history.csv"
CHARTS_DIR         = Path("site_speed_charts")

PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def load_tracked_pages():
    df = pd.read_csv(TRACKED_PAGES_FILE)
    df["page"]     = df["page"].astype(str).str.strip()
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


def get_category_score(data, category_key):
    score = get_nested(data, ["lighthouseResult", "categories", category_key, "score"], None)
    return round(float(score) * 100, 1) if score is not None else None


def get_field_metric(data, metric_key):
    """Return (percentile, category) from page-level or origin-level CrUX data."""
    metric = get_nested(data, ["loadingExperience", "metrics", metric_key], None)
    is_origin = False
    if not metric:
        metric = get_nested(data, ["originLoadingExperience", "metrics", metric_key], None)
        is_origin = True
    if not metric:
        return None, None, False
    return metric.get("percentile"), metric.get("category"), is_origin


def get_overall_field_category(data):
    """Return the overall CrUX category (FAST/AVERAGE/SLOW) for the page."""
    cat = get_nested(data, ["loadingExperience", "overall_category"], None)
    if not cat:
        cat = get_nested(data, ["originLoadingExperience", "overall_category"], None)
    return cat


def get_opportunity_savings(data, audit_key):
    """Return estimated savings in ms for an opportunity audit (None if not applicable)."""
    audit = get_nested(data, ["lighthouseResult", "audits", audit_key], None)
    if not audit:
        return None
    # Opportunity audits store savings in details.overallSavingsMs
    savings = get_nested(audit, ["details", "overallSavingsMs"], None)
    if savings is None:
        # Fallback: some audits use numericValue directly
        savings = audit.get("numericValue")
    if savings is None:
        return None
    return float(savings)


async def fetch_pagespeed_async(session, url, strategy="mobile"):
    params = {
        "url": url,
        "strategy": strategy,
        "category": ["performance", "accessibility"],
        "key": PAGESPEED_API_KEY,
    }
    async with session.get(
        PAGESPEED_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=180)
    ) as response:
        if not response.ok:
            text = await response.text()
            print(f"PSI error for {strategy} {url}: {response.status} {text}", flush=True)
            response.raise_for_status()
        return await response.json()


def _null_record(page_meta, strategy):
    """Return a fully-null record for a failed fetch."""
    base = {
        "date": date.today().isoformat(),
        "page": page_meta["page"],
        "category": page_meta["category"],
        "priority": page_meta["priority"],
        "strategy": strategy,
        "performance_score": None,
        "accessibility_score": None,
        "lcp_lab_ms": None,
        "fcp_lab_ms": None,
        "tbt_lab_ms": None,
        "cls_lab": None,
        "speed_index_ms": None,
        "ttfb_lab_ms": None,
        "lcp_field_ms": None,
        "lcp_field_category": None,
        "inp_field_ms": None,
        "inp_field_category": None,
        "cls_field": None,
        "cls_field_category": None,
        "fcp_field_ms": None,
        "fcp_field_category": None,
        "field_overall_category": None,
        "field_is_origin": False,
        "cwv_pass": None,
    }
    for key in OPPORTUNITY_AUDITS:
        base[f"opp_{key.replace('-', '_')}_ms"] = None
    return base


def build_page_record(page_meta, strategy, data):
    lcp_field,  lcp_field_cat,  lcp_origin  = get_field_metric(data, "LARGEST_CONTENTFUL_PAINT_MS")
    inp_field,  inp_field_cat,  inp_origin  = get_field_metric(data, "INTERACTION_TO_NEXT_PAINT")
    cls_field,  cls_field_cat,  cls_origin  = get_field_metric(data, "CUMULATIVE_LAYOUT_SHIFT_SCORE")
    fcp_field,  fcp_field_cat,  fcp_origin  = get_field_metric(data, "FIRST_CONTENTFUL_PAINT_MS")

    # CWV pass: all three core metrics must be FAST in field data
    cwv_pass = (
        lcp_field_cat == "FAST"
        and inp_field_cat == "FAST"
        and cls_field_cat == "FAST"
    ) if all(c is not None for c in [lcp_field_cat, inp_field_cat, cls_field_cat]) else None

    record = {
        "date": date.today().isoformat(),
        "page": page_meta["page"],
        "category": page_meta["category"],
        "priority": page_meta["priority"],
        "strategy": strategy,
        # Lighthouse category scores
        "performance_score":   get_category_score(data, "performance"),
        "accessibility_score": get_category_score(data, "accessibility"),
        # Lab metrics
        "lcp_lab_ms":    get_audit_numeric(data, "largest-contentful-paint"),
        "fcp_lab_ms":    get_audit_numeric(data, "first-contentful-paint"),
        "tbt_lab_ms":    get_audit_numeric(data, "total-blocking-time"),
        "cls_lab":       get_audit_numeric(data, "cumulative-layout-shift"),
        "speed_index_ms":get_audit_numeric(data, "speed-index"),
        "ttfb_lab_ms":   get_audit_numeric(data, "server-response-time"),
        # Field (CrUX) metrics
        "lcp_field_ms":          lcp_field,
        "lcp_field_category":    lcp_field_cat,
        "inp_field_ms":          inp_field,
        "inp_field_category":    inp_field_cat,
        "cls_field":             cls_field,
        "cls_field_category":    cls_field_cat,
        "fcp_field_ms":          fcp_field,
        "fcp_field_category":    fcp_field_cat,
        "field_overall_category":get_overall_field_category(data),
        "field_is_origin":       lcp_origin,  # True = origin-level data, less precise
        # Derived
        "cwv_pass": cwv_pass,
    }

    # Opportunity audit savings
    for audit_key in OPPORTUNITY_AUDITS:
        col = f"opp_{audit_key.replace('-', '_')}_ms"
        record[col] = get_opportunity_savings(data, audit_key)

    return record


async def process_page_strategy(session, page_meta, strategy):
    try:
        data = await fetch_pagespeed_async(session, page_meta["page"], strategy=strategy)
        print(f"✓ {strategy:7} {page_meta['page']}", flush=True)
        return build_page_record(page_meta, strategy, data)
    except Exception as e:
        print(f"✗ {strategy:7} {page_meta['page']}: {e}", flush=True)
        return _null_record(page_meta, strategy)


async def collect_snapshot_async(tracked_df):
    conn = aiohttp.TCPConnector(limit=10)  # respect API rate limits
    async with aiohttp.ClientSession(connector=conn) as session:
        tasks = [
            process_page_strategy(session, row.to_dict(), strategy)
            for _, row in tracked_df.iterrows()
            for strategy in ["mobile", "desktop"]
        ]
        results = await asyncio.gather(*tasks)
    return pd.DataFrame(results)


def collect_snapshot(tracked_df):
    return asyncio.run(collect_snapshot_async(tracked_df))


def load_previous_snapshot():
    if os.path.exists(SNAPSHOT_FILE):
        return pd.read_csv(SNAPSHOT_FILE)
    return pd.DataFrame()


def prepare_comparison(current_df, previous_df):
    PREV_COLS = ["performance_score", "lcp_lab_ms", "fcp_lab_ms",
                 "tbt_lab_ms", "ttfb_lab_ms", "inp_field_ms", "cls_field"]

    if previous_df.empty:
        work = current_df.copy()
        for col in PREV_COLS:
            work[f"{col}_previous"] = None
    else:
        prev_small = previous_df[["page", "strategy"] + PREV_COLS].rename(
            columns={c: f"{c}_previous" for c in PREV_COLS}
        )
        work = pd.merge(current_df, prev_small, on=["page", "strategy"], how="left")

    for col in PREV_COLS:
        work[f"{col}_change"] = pd.to_numeric(work[col], errors="coerce") - \
                                 pd.to_numeric(work[f"{col}_previous"], errors="coerce")
    return work


# ══════════════════════════════════════════════════════════════════════════════
# DATA PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

def priority_rank(priority):
    return {"high": 0, "medium": 1, "low": 2}.get(str(priority).lower(), 9)


def cwv_status_html(row):
    """Return a coloured badge for CWV pass/fail/unknown."""
    val = row.get("cwv_pass")
    if val is True:
        return '<span style="background:#000;color:#fff;font-family:\'JetBrains Mono\',monospace;font-size:8px;font-weight:700;padding:2px 7px;border:1px solid #000;text-transform:uppercase;letter-spacing:.05em;">PASS</span>'
    if val is False:
        return '<span style="background:#fff;color:#000;font-family:\'JetBrains Mono\',monospace;font-size:8px;font-weight:700;padding:2px 7px;border:1px solid #000;text-transform:uppercase;letter-spacing:.05em;">FAIL</span>'
    return '<span style="background:#fff;color:#525252;font-family:\'JetBrains Mono\',monospace;font-size:8px;font-weight:700;padding:2px 7px;border:1px solid #E5E5E5;text-transform:uppercase;letter-spacing:.05em;">N/A</span>'


def field_cat_html(cat):
    """Return a coloured badge for FAST/AVERAGE/SLOW/NONE."""
    mapping = {
        "FAST":    ("#000", "#fff", "FAST"),
        "AVERAGE": ("#fff", "#000", "AVG"),
        "SLOW":    ("#fff", "#000", "SLOW"),
    }
    bg, fg, label = mapping.get(str(cat).upper(), ("#fff", "#525252", "—"))
    border = "#000" if cat in ("FAST", "SLOW") else "#E5E5E5"
    return (
        f'<span style="background:{bg};color:{fg};font-family:\'JetBrains Mono\',monospace;'
        f'font-size:8px;font-weight:700;padding:2px 6px;border:1px solid {border};'
        f'text-transform:uppercase;letter-spacing:.05em;">{label}</span>'
    )


def ttfb_status_html(ms):
    """Return a coloured badge for TTFB value."""
    try:
        v = float(ms)
    except (TypeError, ValueError):
        return "-"
    if v <= TTFB_WARN_MS:
        bg, fg, border, label = "#000", "#fff", "#000", f"{v:.0f} ms"
    elif v <= TTFB_POOR_MS:
        bg, fg, border, label = "#fff", "#000", "#000", f"{v:.0f} ms ⚠"
    else:
        bg, fg, border, label = "#fff", "#000", "#000", f"{v:.0f} ms ✗"
    return (
        f'<span style="background:{bg};color:{fg};font-family:\'JetBrains Mono\',monospace;'
        f'font-size:9px;font-weight:600;padding:2px 7px;border:1px solid {border};">{label}</span>'
    )


def build_opportunities_df(comparison_df):
    """Flatten opportunity audit savings into a long-form DataFrame for the top-issues table."""
    mobile = comparison_df[comparison_df["strategy"] == "mobile"].copy()
    rows = []
    for _, r in mobile.iterrows():
        for audit_key, label in OPPORTUNITY_AUDITS.items():
            col = f"opp_{audit_key.replace('-', '_')}_ms"
            val = r.get(col)
            if val and float(val) > 100:  # only surface meaningful savings
                rows.append({
                    "page":     r["page"],
                    "category": r["category"],
                    "priority": r["priority"],
                    "issue":    label,
                    "savings_ms": float(val),
                })
    if not rows:
        return pd.DataFrame(columns=["page", "category", "priority", "issue", "savings_ms"])
    df = pd.DataFrame(rows).sort_values("savings_ms", ascending=False)
    return df


# ══════════════════════════════════════════════════════════════════════════════
# AI ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def build_deterministic_bullets(comparison_df):
    """Compute hard metric facts — always present even if AI fails."""
    mobile = comparison_df[comparison_df["strategy"] == "mobile"].copy()
    if mobile.empty:
        return ["No mobile site speed data was available for this run."]

    bullets = []
    scored  = mobile[pd.notnull(mobile["performance_score"])]
    avg_score = scored["performance_score"].mean() if not scored.empty else 0
    bullets.append(
        f"Average mobile performance score across {mobile['page'].nunique()} tracked pages was {avg_score:.1f}."
    )

    # CWV pass rate
    cwv_known = mobile[mobile["cwv_pass"].notna()]
    if not cwv_known.empty:
        passing = int(cwv_known["cwv_pass"].sum())
        total   = len(cwv_known)
        bullets.append(
            f"{passing} of {total} pages with field data passed all three Core Web Vitals (LCP, INP, CLS)."
        )

    # Field metric failures
    poor_lcp = int((mobile["lcp_field_category"] == "SLOW").sum())
    poor_inp = int((mobile["inp_field_category"] == "SLOW").sum())
    poor_cls = int((mobile["cls_field_category"] == "SLOW").sum())
    bullets.append(
        f"{poor_lcp} page{'s' if poor_lcp != 1 else ''} showed poor field LCP; "
        f"{poor_inp} showed poor field INP; "
        f"{poor_cls} showed poor field CLS."
    )

    # TTFB
    ttfb_data = mobile[pd.notnull(mobile["ttfb_lab_ms"])]
    if not ttfb_data.empty:
        slow_ttfb = int((ttfb_data["ttfb_lab_ms"] > TTFB_WARN_MS).sum())
        if slow_ttfb:
            bullets.append(
                f"{slow_ttfb} page{'s' if slow_ttfb != 1 else ''} exceeded the {TTFB_WARN_MS} ms TTFB threshold."
            )

    # Score movement vs previous run
    valid     = mobile[pd.notnull(mobile["performance_score_change"])]
    improved  = int((valid["performance_score_change"] > 0).sum())
    declined  = int((valid["performance_score_change"] < 0).sum())
    if valid.empty:
        bullets.append("No prior-run baseline was available for score movement comparison.")
    elif improved > declined:
        bullets.append(
            f"{improved} pages improved in mobile performance score versus the previous run; {declined} declined."
        )
    elif declined > improved:
        bullets.append(
            f"{declined} pages declined in mobile performance score versus the previous run; {improved} improved."
        )
    else:
        bullets.append("Mobile performance score movement was mixed versus the previous run.")

    # High-priority pages
    hp = mobile[mobile["priority"].str.lower() == "high"]
    hp_scored = hp[pd.notnull(hp["performance_score"])]
    if not hp_scored.empty:
        bullets.append(
            f"High-priority pages averaged a mobile performance score of {hp_scored['performance_score'].mean():.1f}."
        )

    return bullets


def build_ai_bullets(comparison_df):
    """Call Groq for interpreted bullets. Returns empty list if unavailable."""
    if not GROQ_API_KEY:
        return []

    mobile = comparison_df[comparison_df["strategy"] == "mobile"].copy()
    top_table = mobile[[
        "page", "category", "priority", "performance_score", "accessibility_score",
        "performance_score_change", "lcp_lab_ms", "fcp_lab_ms", "ttfb_lab_ms",
        "inp_field_ms", "cls_field", "cwv_pass",
        "lcp_field_category", "inp_field_category", "cls_field_category",
    ]].head(15)

    prompt = (
        "You are writing bullet points for a corporate site speed monitoring report for SEO stakeholders.\n\n"
        "Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.\n"
        "Each bullet is one sentence. Maximum 6 bullets total.\n"
        "Focus on Core Web Vitals pass/fail status, TTFB risks, accessibility concerns, "
        "performance patterns, and recommended actions.\n"
        "Professional corporate tone. Do not invent data. Do not mention AI or automation.\n\n"
        f"Tracked page speed data:\n{top_table.to_csv(index=False)}"
    )

    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write polished weekly executive SEO briefs as bullet points only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        raw = response.choices[0].message.content.strip()
        bullets = []
        for line in raw.splitlines():
            clean = line.strip().lstrip("-*+•·▪▸").replace("**", "").replace("__", "").replace("*", "").strip()
            if clean:
                bullets.append(clean)
        return bullets
    except Exception as e:
        print(f"AI bullet generation failed: {e}", flush=True)
        return []


def build_unified_executive_bullets(comparison_df):
    """Merge deterministic + AI bullets into a single list."""
    return build_deterministic_bullets(comparison_df) + build_ai_bullets(comparison_df)



# ══════════════════════════════════════════════════════════════════════════════
# CHART GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _style_ax(ax, title="", xlabel="", ylabel=""):
    """Apply standard CIM chart styling to an axes object."""
    ax.set_title(title, fontsize=10, fontweight="600", color="#1A1A1A", pad=8, loc="left")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=8, color="#64748B", labelpad=4)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=8, color="#64748B", labelpad=4)
    ax.tick_params(labelsize=8, colors="#64748B", length=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(C_BORDER)
    ax.spines["bottom"].set_color(C_BORDER)
    ax.set_facecolor("#FAFAFA")



def _save(fig, filename):
    """Save a chart at standard dpi and return its Path."""
    CHARTS_DIR.mkdir(exist_ok=True)
    path = CHARTS_DIR / filename
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _placeholder(filename):
    """Return a styled placeholder chart when data is empty."""
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    ax.text(0.5, 0.5, "No data available for this period.",
            ha="center", va="center", fontsize=12, color="#94A3B8",
            transform=ax.transAxes)
    ax.set_axis_off()
    return _save(fig, filename)


def _chart_cwv_status(mobile):
    """Stacked horizontal bar: CWV pass/fail/no-data per page."""
    if mobile.empty:
        return _placeholder("cwv_status.png")

    data = mobile[["page", "cwv_pass", "lcp_field_category",
                   "inp_field_category", "cls_field_category"]].copy()
    data["label"] = [short_url(u, 45) for u in data["page"]]

    # Build per-metric FAST/AVERAGE/SLOW counts for a stacked bar
    metrics = ["lcp_field_category", "inp_field_category", "cls_field_category"]
    metric_labels = ["LCP", "INP", "CLS"]
    cat_colours = {"FAST": C_TEAL, "AVERAGE": C_AMBER, "SLOW": C_CORAL, None: C_BORDER}

    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8))
    fig.patch.set_facecolor("white")

    for ax, col, mlabel in zip(axes, metrics, metric_labels):
        counts = data[col].value_counts().reindex(["FAST", "AVERAGE", "SLOW"]).fillna(0)
        colours = [cat_colours[c] for c in counts.index]
        bars = ax.bar(counts.index, counts.values, color=colours, width=0.5)
        for bar, val in zip(bars, counts.values):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                        str(int(val)), ha="center", va="bottom", fontsize=9,
                        color="#374151", fontweight="600")
        ax.set_ylim(0, max(counts.values.max(), 1) * 1.35)
        ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
        _style_ax(ax, title=f"Field {mlabel} Distribution")

    fig.tight_layout(pad=2.0)
    return _save(fig, "cwv_status.png")


def _chart_overview(mobile, desktop):
    """Paired bar: mobile vs desktop snapshot KPIs."""
    if mobile.empty and desktop.empty:
        return _placeholder("overview.png")

    categories = ["Avg Score", "Poor LCP", "Poor INP", "Poor CLS"]
    mobile_vals = [
        mobile["performance_score"].mean() if not mobile.empty else 0,
        int((mobile["lcp_field_category"] == "SLOW").sum()),
        int((mobile["inp_field_category"] == "SLOW").sum()),
        int((mobile["cls_field_category"] == "SLOW").sum()),
    ]
    desktop_vals = [
        desktop["performance_score"].mean() if not desktop.empty else 0,
        int((desktop["lcp_field_category"] == "SLOW").sum()),
        int((desktop["inp_field_category"] == "SLOW").sum()),
        int((desktop["cls_field_category"] == "SLOW").sum()),
    ]

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    x = range(len(categories))
    width = 0.34
    bars_m = ax.bar([i - width / 2 for i in x], mobile_vals, width=width, label="Mobile", color=C_NAVY)
    bars_d = ax.bar([i + width / 2 for i in x], desktop_vals, width=width, label="Desktop", color=C_TEAL)
    ax.set_xticks(list(x))
    ax.set_xticklabels(categories)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.legend(frameon=False, fontsize=8)
    _style_ax(ax, title="Mobile vs Desktop Site Speed Snapshot")
    max_v = max(max(mobile_vals), max(desktop_vals), 1)
    for bar, val in zip(list(bars_m) + list(bars_d), mobile_vals + desktop_vals):
        label = f"{val:.1f}" if isinstance(val, float) else str(val)
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.03,
                label, ha="center", va="bottom", fontsize=9, color="#374151", fontweight="600")
    ax.set_ylim(0, max_v * 1.25)
    fig.tight_layout(pad=2.0)
    return _save(fig, "overview.png")


def _chart_score_vs_accessibility(mobile):
    """Scatter: performance score vs accessibility score, sized by priority."""
    scored = mobile[pd.notnull(mobile["performance_score"]) & pd.notnull(mobile["accessibility_score"])].copy()
    if scored.empty:
        return _placeholder("score_vs_accessibility.png")

    size_map = {"high": 180, "medium": 100, "low": 60}
    sizes = [size_map.get(str(p).lower(), 80) for p in scored["priority"]]
    colours = [C_CORAL if str(p).lower() == "high" else
               C_AMBER if str(p).lower() == "medium" else C_SLATE
               for p in scored["priority"]]

    fig, ax = plt.subplots(figsize=(13, 6.5))
    fig.patch.set_facecolor("white")
    ax.scatter(scored["performance_score"], scored["accessibility_score"],
               s=sizes, c=colours, alpha=0.8, zorder=3)

    # Reference lines at 90 (good threshold)
    ax.axvline(90, color=C_BORDER, linewidth=1, linestyle="--", zorder=1)
    ax.axhline(90, color=C_BORDER, linewidth=1, linestyle="--", zorder=1)
    ax.axvspan(90, 101, alpha=0.04, color=C_TEAL, zorder=0)
    ax.axhspan(90, 101, alpha=0.04, color=C_TEAL, zorder=0)

    # Annotate top 6 by priority then performance
    scored["_pr"] = scored["priority"].map({"high": 0, "medium": 1, "low": 2})
    top = scored.sort_values(["_pr", "performance_score"]).head(6)
    for _, r in top.iterrows():
        ax.annotate(short_url(r["page"], 30),
                    (r["performance_score"], r["accessibility_score"]),
                    textcoords="offset points", xytext=(6, 4),
                    fontsize=7, color="#374151")

    legend_patches = [
        mpatches.Patch(color=C_CORAL, label="High priority"),
        mpatches.Patch(color=C_AMBER, label="Medium priority"),
        mpatches.Patch(color=C_SLATE, label="Low priority"),
    ]
    ax.legend(handles=legend_patches, frameon=False, fontsize=8, loc="lower right")
    ax.set_xlim(0, 105)
    ax.set_ylim(0, 105)
    ax.grid(linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Performance vs Accessibility Score",
              xlabel="Performance Score", ylabel="Accessibility Score")
    fig.tight_layout(pad=2.0)
    return _save(fig, "score_vs_accessibility.png")


def _chart_ttfb(mobile):
    """Horizontal bar: TTFB for all pages, colour-coded by threshold."""
    scored = mobile[pd.notnull(mobile["ttfb_lab_ms"])].copy()
    if scored.empty:
        return _placeholder("ttfb.png")

    data = scored.sort_values("ttfb_lab_ms", ascending=False).head(15)
    labels = [short_url(u, 45) for u in data["page"]]
    values = data["ttfb_lab_ms"].tolist()
    colours = [C_RED if v > TTFB_POOR_MS else C_AMBER if v > TTFB_WARN_MS else C_TEAL
               for v in values]
    max_v = max(values) if values else 1

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars = ax.barh(labels, values, color=colours)
    ax.axvline(TTFB_WARN_MS, color=C_AMBER, linewidth=1.2, linestyle="--", zorder=3,
               label=f"Needs improvement ({TTFB_WARN_MS} ms)")
    ax.axvline(TTFB_POOR_MS, color=C_RED, linewidth=1.2, linestyle="--", zorder=3,
               label=f"Poor ({TTFB_POOR_MS} ms)")
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.set_xlim(0, max_v * 1.18)
    for bar, val in zip(bars, values):
        ax.text(val + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,.0f}", va="center", fontsize=9, color="#374151")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    _style_ax(ax, title="Time to First Byte (TTFB) — Lab Data", xlabel="TTFB (ms)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "ttfb.png")


def _chart_category_performance(mobile):
    """Grouped bar: avg performance score and accessibility score by page category."""
    scored = mobile[pd.notnull(mobile["performance_score"])].copy()
    if scored.empty or "category" not in scored.columns:
        return _placeholder("category_performance.png")

    grp = scored.groupby("category").agg(
        perf=("performance_score", "mean"),
        a11y=("accessibility_score", "mean"),
        count=("page", "nunique"),
    ).reset_index().sort_values("perf", ascending=False)

    if grp.empty:
        return _placeholder("category_performance.png")

    x = range(len(grp))
    width = 0.38
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars_p = ax.bar([i - width / 2 for i in x], grp["perf"], width=width,
                    label="Performance", color=C_NAVY)
    bars_a = ax.bar([i + width / 2 for i in x], grp["a11y"].fillna(0), width=width,
                    label="Accessibility", color=C_TEAL)
    ax.set_xticks(list(x))
    ax.set_xticklabels([c + "\n(n=" + str(n) + ")" for c, n in zip(grp["category"], grp["count"])],
                       fontsize=8)
    ax.set_ylim(0, 115)
    ax.axhline(90, color=C_BORDER, linewidth=1, linestyle="--", zorder=1)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.legend(frameon=False, fontsize=8)
    for bar, val in zip(list(bars_p) + list(bars_a),
                        grp["perf"].tolist() + grp["a11y"].fillna(0).tolist()):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    f"{val:.0f}", ha="center", va="bottom", fontsize=8,
                    color="#374151", fontweight="600")
    _style_ax(ax, title="Average Score by Page Category")
    fig.tight_layout(pad=2.0)
    return _save(fig, "category_performance.png")


def _chart_top_mobile_scores(mobile):
    """Horizontal bar: top 10 mobile performance scores."""
    if mobile.empty:
        return _placeholder("top_mobile_scores.png")

    top = mobile.sort_values("performance_score", ascending=False).head(10).copy()
    labels = [short_url(u, 45) for u in top["page"]]
    values = top["performance_score"].tolist()
    max_v = max(values) if values else 1

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars = ax.barh(labels, values, color=C_NAVY)
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.set_xlim(0, max_v * 1.18)
    for bar, val in zip(bars, values):
        ax.text(val + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}", va="center", fontsize=9, color="#374151")
    _style_ax(ax, title="Top Mobile Performance Scores")
    fig.tight_layout(pad=2.0)
    return _save(fig, "top_mobile_scores.png")


def _chart_worst_lcp(mobile):
    """Horizontal bar: pages with highest mobile LCP, with threshold bands."""
    scored = mobile[pd.notnull(mobile["lcp_lab_ms"])].copy()
    if scored.empty:
        return _placeholder("highest_mobile_lcp.png")

    worst = scored.sort_values("lcp_lab_ms", ascending=False).head(10).copy()
    labels = [short_url(u, 45) for u in worst["page"]]
    values = worst["lcp_lab_ms"].tolist()
    colours = [C_RED if v > LCP_POOR_MS else C_AMBER if v > LCP_GOOD_MS else C_TEAL
               for v in values]
    max_v = max(values) if values else 1

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars = ax.barh(labels, values, color=colours)
    ax.axvline(LCP_GOOD_MS, color=C_AMBER, linewidth=1.2, linestyle="--", zorder=3,
               label=f"Needs improvement ({LCP_GOOD_MS:,} ms)")
    ax.axvline(LCP_POOR_MS, color=C_RED, linewidth=1.2, linestyle="--", zorder=3,
               label=f"Poor ({LCP_POOR_MS:,} ms)")
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.set_xlim(0, max_v * 1.18)
    for bar, val in zip(bars, values):
        ax.text(val + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,.0f}", va="center", fontsize=9, color="#374151")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    _style_ax(ax, title="Highest Mobile LCP Pages", xlabel="LCP (ms)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "highest_mobile_lcp.png")


def _chart_fcp_vs_lcp(mobile):
    """Paired horizontal bars: FCP vs LCP lab data side by side."""
    scored = mobile[pd.notnull(mobile["lcp_lab_ms"]) & pd.notnull(mobile["fcp_lab_ms"])].copy()
    if scored.empty:
        return _placeholder("fcp_vs_lcp.png")

    data = scored.sort_values("lcp_lab_ms", ascending=False).head(10)
    labels = [short_url(u, 38) for u in data["page"]]
    lcp_vals = data["lcp_lab_ms"].tolist()
    fcp_vals = data["fcp_lab_ms"].tolist()
    y = range(len(labels))
    max_v = max(max(lcp_vals), max(fcp_vals), 1)

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    height = 0.35
    bars_l = ax.barh([i + height / 2 for i in y], lcp_vals, height=height,
                     label="LCP", color=C_CORAL)
    bars_f = ax.barh([i - height / 2 for i in y], fcp_vals, height=height,
                     label="FCP", color=C_NAVY)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.legend(frameon=False, fontsize=8)
    for bar, val in zip(list(bars_l) + list(bars_f), lcp_vals + fcp_vals):
        ax.text(val + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,.0f}", va="center", fontsize=8, color="#374151")
    _style_ax(ax, title="FCP vs LCP Lab Data (ms) — Worst LCP Pages", xlabel="Time (ms)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "fcp_vs_lcp.png")


def _chart_score_change(mobile):
    """Horizontal bar: mobile score winners and losers vs previous run."""
    valid = mobile[pd.notnull(mobile["performance_score_change"])].copy()
    if valid.empty or valid["performance_score_change"].abs().sum() == 0:
        return None

    top = valid.sort_values("performance_score_change", ascending=False).head(12)
    labels = [short_url(u, 45) for u in top["page"]]
    values = top["performance_score_change"].tolist()
    colours = [C_TEAL if v >= 0 else C_CORAL for v in values]
    max_abs = max(abs(v) for v in values) if values else 1

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    ax.barh(labels, values, color=colours)
    ax.invert_yaxis()
    ax.axvline(0, color=C_SLATE, linewidth=1)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.set_xlim(-max_abs * 1.25, max_abs * 1.25)
    _style_ax(ax, title="Mobile Score Winners and Losers")
    fig.tight_layout(pad=2.0)
    return _save(fig, "score_change.png")


def _chart_opportunities(opp_df):
    """Horizontal bar: top optimization opportunities by estimated savings."""
    if opp_df.empty:
        return None

    top = opp_df.head(15).copy()
    labels = [f"{short_url(r['page'], 30)} — {r['issue']}" for _, r in top.iterrows()]
    values = top["savings_ms"].tolist()
    max_v = max(values) if values else 1

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    bars = ax.barh(labels, values, color=C_AMBER)
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    ax.set_xlim(0, max_v * 1.18)
    for bar, val in zip(bars, values):
        ax.text(val + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,.0f} ms", va="center", fontsize=8, color="#374151")
    _style_ax(ax, title="Top Optimization Opportunities — Estimated Savings (ms)",
              xlabel="Estimated Savings (ms)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "opportunities.png")


def build_all_charts(comparison_df, opp_df):
    """Build all charts and return a dict of {name: Path | None}."""
    mobile  = comparison_df[
        (comparison_df["strategy"] == "mobile") & pd.notnull(comparison_df["performance_score"])
    ].copy()
    desktop = comparison_df[
        (comparison_df["strategy"] == "desktop") & pd.notnull(comparison_df["performance_score"])
    ].copy()

    return {
        "overview":              _chart_overview(mobile, desktop),
        "cwv_status":            _chart_cwv_status(mobile),
        "score_vs_a11y":         _chart_score_vs_accessibility(mobile),
        "category_performance":  _chart_category_performance(mobile),
        "top_mobile":            _chart_top_mobile_scores(mobile),
        "worst_lcp":             _chart_worst_lcp(mobile),
        "fcp_vs_lcp":            _chart_fcp_vs_lcp(mobile),
        "ttfb":                  _chart_ttfb(mobile),
        "score_change":          _chart_score_change(mobile),
        "opportunities":         _chart_opportunities(opp_df),
    }


# ══════════════════════════════════════════════════════════════════════════════
# HTML TABLE BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def _build_speed_table(df, cols, rename, badge_cols=None):
    if df.empty:
        return "<p>No data available.</p>"
    badge_cols = badge_cols or {}
    header_html = "".join(
        "<th>" + _html.escape(str(rename.get(c, c))) + "</th>" for c in cols
    )
    rows = []
    for _, row in df[cols].iterrows():
        cells = []
        for col in cols:
            val = row[col]
            display_name = rename.get(col, col)
            if col == "page":
                display = _html.escape(short_url(str(val), 45))
                cells.append(
                    '<td class="url-cell" title="' + _html.escape(str(val)) + '">' + display + '</td>'
                )
            elif col in badge_cols:
                cells.append('<td style="white-space:nowrap;">' + badge_cols[col](row) + '</td>')
            elif "change" in col or "\u0394" in display_name:
                try:
                    fval = float(val)
                    lower_better = any(k in col for k in ["lcp", "fcp", "tbt", "ttfb", "inp"])
                    if lower_better:
                        cls = "pos" if fval < 0 else ("neg" if fval > 0 else "neu")
                    else:
                        cls = "pos" if fval > 0 else ("neg" if fval < 0 else "neu")
                    sign = "+" if fval > 0 else ""
                    disp = (sign + "{:.1f}".format(fval)) if fval != 0 else "-"
                except (TypeError, ValueError):
                    cls, disp = "neu", "-"
                cells.append(
                    '<td style="white-space:nowrap;"><span class="chg ' + cls + '">' + _html.escape(disp) + '</span></td>'
                )
            else:
                try:
                    fval = float(val)
                    if pd.isna(fval) or fval == 0:
                        disp = "-"
                    elif fval < 10:
                        disp = "{:.3f}".format(fval)
                    else:
                        disp = "{:,.0f}".format(fval)
                except (TypeError, ValueError):
                    disp = _html.escape(str(val)) if str(val) not in ("nan", "None", "") else "-"
                cells.append('<td style="white-space:nowrap;">' + disp + '</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<table style="table-layout:fixed;width:100%;">' +
        "<thead><tr>" + header_html + "</tr></thead>" +
        "<tbody>" + "".join(rows) + "</tbody>" +
        "</table>"
    )


def _build_opportunities_table(opp_df):
    if opp_df.empty:
        return "<p>No significant optimization opportunities detected.</p>"
    top = opp_df.head(20).copy()
    rows = []
    for _, r in top.iterrows():
        page_disp = _html.escape(short_url(r["page"], 45))
        issue     = _html.escape(r["issue"])
        savings   = "{:,.0f} ms".format(r["savings_ms"])
        priority  = _html.escape(str(r["priority"]).capitalize())
        cat       = _html.escape(str(r["category"]).capitalize())
        rows.append(
            "<tr>" +
            '<td class="url-cell" title="' + _html.escape(r["page"]) + '">' + page_disp + '</td>' +
            '<td style="white-space:nowrap;">' + cat + '</td>' +
            '<td style="white-space:nowrap;">' + priority + '</td>' +
            '<td style="white-space:nowrap;font-weight:600;">' + issue + '</td>' +
            '<td style="white-space:nowrap;">' + savings + '</td>' +
            "</tr>"
        )
    header = "<tr><th>Page</th><th>Category</th><th>Priority</th><th>Opportunity</th><th>Est. Savings</th></tr>"
    return (
        '<table style="table-layout:fixed;width:100%;">' +
        "<thead>" + header + "</thead>" +
        "<tbody>" + "".join(rows) + "</tbody>" +
        "</table>"
    )



# ══════════════════════════════════════════════════════════════════════════════
# HTML REPORT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _img(path, alt):
    """Return mm_chart_wrap or an empty-state message if path is None."""
    if not path:
        return (
            '<p style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">'
            "No baseline data available for this chart.</p>"
        )
    return mm_chart_wrap(path, alt)


def write_html_summary(comparison_df, opp_df):
    clean   = comparison_df[pd.notnull(comparison_df["performance_score"])].copy()
    mobile  = clean[clean["strategy"] == "mobile"].copy()
    desktop = clean[clean["strategy"] == "desktop"].copy()

    mobile["_pr"]  = mobile["priority"].map(priority_rank)
    desktop["_pr"] = desktop["priority"].map(priority_rank)
    mobile  = mobile.sort_values(["_pr", "performance_score"], ascending=[True, False]).drop(columns=["_pr"])
    desktop = desktop.sort_values(["_pr", "performance_score"], ascending=[True, False]).drop(columns=["_pr"])

    # Executive bullets
    exec_bullets = build_unified_executive_bullets(comparison_df)

    # Charts
    chart_paths = build_all_charts(comparison_df, opp_df)

    # ── Mobile table columns ──────────────────────────────────────────────────
    mob_cols   = ["page", "cwv_pass", "field_overall_category", "performance_score",
                  "performance_score_change", "accessibility_score",
                  "lcp_field_ms", "lcp_field_category",
                  "inp_field_ms", "inp_field_category",
                  "cls_field",   "cls_field_category",
                  "ttfb_lab_ms"]
    mob_rename = {
        "page": "Page", "cwv_pass": "CWV", "field_overall_category": "Field",
        "performance_score": "Perf", "performance_score_change": "Perf \u0394",
        "accessibility_score": "A11y",
        "lcp_field_ms": "LCP (ms)", "lcp_field_category": "LCP Cat",
        "inp_field_ms": "INP (ms)", "inp_field_category": "INP Cat",
        "cls_field": "CLS", "cls_field_category": "CLS Cat",
        "ttfb_lab_ms": "TTFB (ms)",
    }
    mob_badges = {
        "cwv_pass":             cwv_status_html,
        "field_overall_category": lambda r: field_cat_html(r.get("field_overall_category")),
        "lcp_field_category":   lambda r: field_cat_html(r.get("lcp_field_category")),
        "inp_field_category":   lambda r: field_cat_html(r.get("inp_field_category")),
        "cls_field_category":   lambda r: field_cat_html(r.get("cls_field_category")),
        "ttfb_lab_ms":          lambda r: ttfb_status_html(r.get("ttfb_lab_ms")),
    }

    # ── Desktop table columns ─────────────────────────────────────────────────
    desk_cols   = ["page", "performance_score", "performance_score_change",
                   "accessibility_score", "lcp_lab_ms", "fcp_lab_ms",
                   "tbt_lab_ms", "cls_lab", "ttfb_lab_ms"]
    desk_rename = {
        "page": "Page", "performance_score": "Perf", "performance_score_change": "Perf \u0394",
        "accessibility_score": "A11y",
        "lcp_lab_ms": "LCP (ms)", "fcp_lab_ms": "FCP (ms)",
        "tbt_lab_ms": "TBT (ms)", "cls_lab": "CLS",
        "ttfb_lab_ms": "TTFB (ms)",
    }
    desk_badges = {
        "ttfb_lab_ms": lambda r: ttfb_status_html(r.get("ttfb_lab_ms")),
    }

    mobile_main      = mobile.head(10).copy()
    desktop_main     = desktop.head(10).copy()
    appendix_mobile  = mobile.iloc[10:].copy()
    appendix_desktop = desktop.iloc[10:].copy()

    # ── KPI grid ──────────────────────────────────────────────────────────────
    cwv_known   = mobile[mobile["cwv_pass"].notna()]
    cwv_passing = int(cwv_known["cwv_pass"].sum()) if not cwv_known.empty else 0
    cwv_total   = len(cwv_known)
    slow_ttfb   = int((mobile["ttfb_lab_ms"] > TTFB_WARN_MS).sum()) if "ttfb_lab_ms" in mobile.columns else 0

    kpi_grid = mm_kpi_grid(
        mm_kpi_card("Tracked URLs",      comparison_df["page"].nunique(), None),
        mm_kpi_card("Mobile Avg Score",  mobile["performance_score"].mean() if not mobile.empty else 0,
                    None, decimals=1),
        mm_kpi_card("CWV Passing",       cwv_passing, None),
        mm_kpi_card("Slow TTFB Pages",   slow_ttfb, None),
    )

    # ── Body ──────────────────────────────────────────────────────────────────
    body = (
        mm_section(
            "Executive Summary",
            mm_report_section(mm_exec_bullets(exec_bullets)),
        ) +
        '<div class="section" style="padding-top:0;">' + kpi_grid + '</div>'
        '<hr class="rule-thick">' +

        # Section 1: CWV field status — the headline metric
        mm_section(
            "Core Web Vitals — Field Status",
            mm_report_section(
                _img(chart_paths["cwv_status"], "CWV field metric distribution")
            ),
        ) +

        # Section 2: Overview paired bar
        mm_section(
            "Mobile vs Desktop Snapshot",
            mm_report_section(
                _img(chart_paths["overview"], "Mobile vs desktop overview")
            ),
        ) +

        # Section 3: Performance vs Accessibility scatter (full-page)
        mm_section(
            "Performance vs Accessibility",
            mm_report_section(
                _img(chart_paths["score_vs_a11y"], "Performance vs accessibility scatter")
            ),
        ) +

        # Section 4: Category breakdown
        mm_section(
            "Score by Page Category",
            mm_report_section(
                _img(chart_paths["category_performance"], "Average score by page category")
            ),
        ) +

        # Section 5: TTFB
        mm_section(
            "Time to First Byte (TTFB)",
            mm_report_section(
                _img(chart_paths["ttfb"], "TTFB by page")
            ),
        ) +

        # Section 6: LCP + FCP side by side
        mm_section(
            "LCP vs FCP — Worst Pages",
            mm_report_section(
                _img(chart_paths["fcp_vs_lcp"], "FCP vs LCP comparison")
            ),
        ) +

        # Section 7: Worst LCP with thresholds
        mm_section(
            "Highest Mobile LCP Pages",
            mm_report_section(
                _img(chart_paths["worst_lcp"], "Highest mobile LCP")
            ),
        ) +

        # Section 8: Top scores
        mm_section(
            "Top Mobile Performance Scores",
            mm_report_section(
                _img(chart_paths["top_mobile"], "Top mobile scores")
            ),
        ) +

        # Section 9: Score movement (optional)
        (
            mm_section(
                "Mobile Score Movement",
                mm_report_section(
                    _img(chart_paths["score_change"], "Mobile score winners and losers")
                ),
            )
            if chart_paths.get("score_change") else ""
        ) +

        # Section 10: Opportunities chart + table
        (
            mm_section(
                "Optimization Opportunities",
                mm_report_section(
                    _img(chart_paths["opportunities"], "Top optimization opportunities") +
                    "<br>" +
                    _build_opportunities_table(opp_df)
                ),
            )
            if chart_paths.get("opportunities") else ""
        ) +

        # Section 11: Mobile detail table
        mm_section(
            "Mobile Results — Detail",
            mm_report_section(
                _build_speed_table(mobile_main, mob_cols, mob_rename, mob_badges)
            ),
        ) +

        # Section 12: Desktop detail table
        mm_section(
            "Desktop Results — Detail",
            mm_report_section(
                _build_speed_table(desktop_main, desk_cols, desk_rename, desk_badges)
            ),
        ) +

        # Appendix
        (
            mm_section(
                "Appendix \u2014 Additional Mobile Rows",
                mm_report_section(
                    _build_speed_table(appendix_mobile, mob_cols, mob_rename, mob_badges)
                ),
            )
            if not appendix_mobile.empty else ""
        ) +
        (
            mm_section(
                "Appendix \u2014 Additional Desktop Rows",
                mm_report_section(
                    _build_speed_table(appendix_desktop, desk_cols, desk_rename, desk_badges)
                ),
            )
            if not appendix_desktop.empty else ""
        )
    )

    doc = mm_html_shell(
        title="Site Speed Monitoring",
        eyebrow="CIM SEO \u2014 Core Web Vitals",
        headline="Site Speed\nMonitoring",
        meta_line="Generated " + date.today().isoformat(),
        body_content=body,
    )
    with open("site_speed_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("Saved site_speed_summary.html")



# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

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
    tracked_df    = load_tracked_pages()
    current_df    = collect_snapshot(tracked_df)
    previous_df   = load_previous_snapshot()
    comparison_df = prepare_comparison(current_df, previous_df)

    # 1. Save CSVs before any report generation
    current_df.to_csv("site_speed_current_snapshot.csv", index=False)
    comparison_df.to_csv("site_speed_comparison.csv", index=False)

    # 2. Persist to Google Sheets
    append_to_sheet(current_df, "Site_Speed_Snapshot")
    append_to_sheet(comparison_df, "Site_Speed_Comparison")

    # 3. Build opportunity data
    opp_df = build_opportunities_df(comparison_df)
    opp_df.to_csv("site_speed_opportunities.csv", index=False)

    # 4. Build HTML report
    write_html_summary(comparison_df, opp_df)
    generate_self_contained()

    # 5. Persist snapshots for next run's WoW comparison
    persist_snapshots(current_df)

    # 6. Upload to Monday.com — non-fatal
    try:
        upload_to_monday()
    except Exception as e:
        print(f"Monday upload failed: {e}")

    print("Site speed outputs saved.")


if __name__ == "__main__":
    main()
