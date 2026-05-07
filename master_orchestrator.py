import asyncio
import os
import html as _html
import pandas as pd
import numpy as np
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from openai import OpenAI
from datetime import date
from pathlib import Path
from seo_utils import short_url
from pdf_report_formatter import format_num, format_delta, format_pct_change

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

MONDAY_API_TOKEN    = os.getenv("MONDAY_API_TOKEN")
MONDAY_MASTER_ITEM_ID = os.getenv("MONDAY_MASTER_ITEM_ID")
GROQ_API_KEY        = os.getenv("GROQ_API_KEY")

CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

# Brand palette — matches REPORT_DESIGN_PRINCIPLES.md §1
C_NAVY   = "#212878"
C_TEAL   = "#2A9D8F"
C_CORAL  = "#E76F51"
C_SLATE  = "#6C757D"
C_GREEN  = "#059669"
C_RED    = "#DC2626"
C_AMBER  = "#D97706"
C_BORDER = "#E2E8F0"
C_LIGHT  = "#F1F5F9"

# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

async def run_script(script_name, env_vars=None):
    print(f"Starting {script_name}...")
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)

    process = await asyncio.create_subprocess_exec(
        "python", "-u", script_name,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    while True:
        line = await process.stdout.readline()
        if not line:
            break
        print(f"[{script_name}] {line.decode('utf-8').strip()}", flush=True)

    await process.wait()
    print(f"Finished {script_name} with code {process.returncode}")
    if process.returncode != 0:
        raise RuntimeError(f"{script_name} failed with exit code {process.returncode}")

async def run_all_scripts():
    # ── Group 1: API-based pipelines — run fully concurrently ─────────────────
    ga4_env = {
        "GA4_PROPERTY_ID": "341629008",
        "MONDAY_ITEM_ID":  "11818936551",
    }
    gsc_weekly_env = {
        "GSC_PROPERTY": "https://www.cim.org/",
        "MONDAY_ITEM_ID": os.getenv("MONDAY_GSC_ITEM_ID", ""),
    }
    gsc_keyword_env = {
        "GSC_PROPERTY": "https://www.cim.org/",
        "MONDAY_ITEM_ID": os.getenv("MONDAY_GSC_KEYWORD_ITEM_ID", ""),
    }
    gsc_landing_env = {
        "GSC_PROPERTY": "https://www.cim.org/",
        "MONDAY_ITEM_ID": os.getenv("MONDAY_GSC_LANDING_ITEM_ID", ""),
    }
    speed_env = {
        "MONDAY_ITEM_ID": "11404492774",
    }

    async def run_snippet_pipeline():
        snippet_env = {
            "MONDAY_API_KEY":              MONDAY_API_TOKEN or "",
            "MONDAY_AI_SNIPPET_ITEM_ID":   os.getenv("MONDAY_AI_SNIPPET_ITEM_ID", ""),
            "GROQ_MODEL":                  "llama-3.1-8b-instant",
        }
        await run_script("ai_snippet_verification.py", snippet_env)
        await run_script("ai_snippet_pdf_report.py",   snippet_env)

    print("--- Starting API-based pipelines (concurrent) ---")
    await asyncio.gather(
        run_script("ga4_weekly_report.py",          ga4_env),
        run_script("gsc_weekly_report.py",          gsc_weekly_env),
        run_script("gsc_keyword_ranking_report.py", gsc_keyword_env),
        run_script("gsc_landing_pages_report.py",   gsc_landing_env),
        run_script("site_speed_monitoring.py",      speed_env),
        run_snippet_pipeline(),
    )

    # ── Group 2: Crawl-based pipelines — sequential to avoid overloading cim.org
    broken_link_env  = {"MONDAY_ITEM_ID": os.getenv("MONDAY_BROKEN_LINK_ITEM_ID", "")}
    internal_link_env = {"MONDAY_ITEM_ID": os.getenv("MONDAY_INTERNAL_LINK_ITEM_ID", "")}
    content_audit_env = {
        "GSC_PROPERTY": "https://www.cim.org/",
        "MONDAY_ITEM_ID": os.getenv("MONDAY_CONTENT_AUDIT_ITEM_ID", ""),
    }
    content_perf_env = {
        "GSC_PROPERTY":   "https://www.cim.org/",
        "GA4_PROPERTY_ID": "341629008",
    }

    print("--- Starting crawl-based pipelines (sequential) ---")
    await run_script("broken_link_check.py",           broken_link_env)
    await run_script("internal_linking_audit.py",      internal_link_env)
    await run_script("content_audit_schedule_report.py", content_audit_env)
    await run_script("content_category_performance.py",  content_perf_env)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

def _load(filename):
    """Safely load a CSV, returning an empty DataFrame on any failure."""
    try:
        return pd.read_csv(filename)
    except Exception:
        return pd.DataFrame()


def load_all_data():
    """Load every downstream CSV produced by the sub-scripts."""
    ga4_summary  = _load("ga4_summary_comparison.csv")
    ga4_pages    = _load("ga4_top_landing_pages.csv").head(10)
    gsc_comp     = _load("weekly_comparison.csv")
    gsc_queries  = _load("top_queries.csv").head(10)
    speed        = _load("site_speed_comparison.csv")
    content_cat  = _load("content_category_performance.csv")
    kw_comp      = _load("tracked_keywords_comparison.csv")

    if not content_cat.empty and "sessions" in content_cat.columns:
        content_cat = content_cat.sort_values("sessions", ascending=False)

    return {
        "ga4_summary":  ga4_summary,
        "ga4_pages":    ga4_pages,
        "gsc_comp":     gsc_comp,
        "gsc_queries":  gsc_queries,
        "speed":        speed,
        "content_cat":  content_cat,
        "kw_comp":      kw_comp,
    }


def aggregate_kpis(data):
    """Derive the 8 headline KPIs from loaded DataFrames."""
    kpis = {
        "sessions":    {"curr": 0, "prev": 0},
        "users":       {"curr": 0, "prev": 0},
        "clicks":      {"curr": 0, "prev": 0},
        "impressions": {"curr": 0, "prev": 0},
        "avg_position":{"curr": 0, "prev": 0},
        "mobile_score":{"curr": 0, "prev": 0},
    }

    ga4 = data["ga4_summary"]
    if not ga4.empty and "metric" in ga4.columns:
        for _, row in ga4.iterrows():
            m = str(row.get("metric", ""))
            if m == "sessions":
                kpis["sessions"] = {"curr": float(row.get("current", 0)), "prev": float(row.get("previous", 0))}
            elif m == "activeUsers":
                kpis["users"] = {"curr": float(row.get("current", 0)), "prev": float(row.get("previous", 0))}

    gsc = data["gsc_comp"]
    if not gsc.empty:
        for col in ["clicks_current", "clicks_previous", "impressions_current", "impressions_previous"]:
            gsc[col] = pd.to_numeric(gsc.get(col, 0), errors="coerce").fillna(0)
        kpis["clicks"]      = {"curr": gsc["clicks_current"].sum(),      "prev": gsc["clicks_previous"].sum()}
        kpis["impressions"] = {"curr": gsc["impressions_current"].sum(),  "prev": gsc["impressions_previous"].sum()}
        pos_curr = gsc.loc[gsc["position_current"] > 0, "position_current"].mean() if "position_current" in gsc.columns else 0
        pos_prev = gsc.loc[gsc["position_previous"] > 0, "position_previous"].mean() if "position_previous" in gsc.columns else 0
        kpis["avg_position"] = {"curr": round(float(pos_curr or 0), 1), "prev": round(float(pos_prev or 0), 1)}

    speed = data["speed"]
    if not speed.empty and "strategy" in speed.columns and "performance_score" in speed.columns:
        mob = speed[speed["strategy"] == "mobile"]
        if not mob.empty:
            kpis["mobile_score"] = {"curr": round(mob["performance_score"].mean(), 1), "prev": 0}

    return kpis


# ══════════════════════════════════════════════════════════════════════════════
# CHART GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _style_ax(ax, title="", xlabel="", ylabel=""):
    """Shared axes styling — REPORT_DESIGN_PRINCIPLES.md §6."""
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


def _save(fig, name):
    path = CHARTS_DIR / name
    fig.patch.set_facecolor("white")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path.absolute())


def _placeholder(name):
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    ax.text(0.5, 0.5, "No data available for this period.",
            ha="center", va="center", fontsize=12, color="#94A3B8",
            transform=ax.transAxes)
    ax.set_axis_off()
    return _save(fig, name)


def chart_kpi_overview(kpis):
    """Paired bar: current vs previous for sessions, users, clicks, impressions."""
    labels = ["Sessions", "Users", "Clicks", "Impressions"]
    keys   = ["sessions", "users", "clicks", "impressions"]
    curr_vals = [kpis[k]["curr"] for k in keys]
    prev_vals = [kpis[k]["prev"] for k in keys]

    x = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars_p = ax.bar(x - 0.2, prev_vals, width=0.38, color=C_SLATE, label="Previous", zorder=2)
    bars_c = ax.bar(x + 0.2, curr_vals, width=0.38, color=C_NAVY,  label="Current",  zorder=2)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    max_v = max(curr_vals + prev_vals, default=1)
    for bar in list(bars_p) + list(bars_c):
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, h * 1.03,
                    f"{h:,.0f}", ha="center", va="bottom", fontsize=7,
                    color="#374151", fontweight="600")
    ax.set_ylim(0, max_v * 1.22)
    _style_ax(ax, title="Weekly KPI Overview — Current vs Previous")
    fig.tight_layout(pad=2.0)
    return _save(fig, "master_kpi_overview.png")


def chart_traffic_vs_search(kpis):
    """Horizontal bar comparing GA4 sessions and GSC clicks side by side."""
    metrics = ["Sessions", "GSC Clicks", "Impressions / 10"]
    values  = [
        kpis["sessions"]["curr"],
        kpis["clicks"]["curr"],
        kpis["impressions"]["curr"] / 10,
    ]
    prev_values = [
        kpis["sessions"]["prev"],
        kpis["clicks"]["prev"],
        kpis["impressions"]["prev"] / 10,
    ]
    if all(v == 0 for v in values):
        return _placeholder("master_traffic_search.png")

    y = np.arange(len(metrics))
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars_p = ax.barh(y - 0.2, prev_values, height=0.35, color=C_SLATE, label="Previous", zorder=2)
    bars_c = ax.barh(y + 0.2, values,      height=0.35, color=C_TEAL,  label="Current",  zorder=2)
    ax.set_yticks(y)
    ax.set_yticklabels(metrics)
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    max_v = max(values + prev_values, default=1)
    for bar in list(bars_c):
        v = bar.get_width()
        if v > 0:
            ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                    f"{v:,.0f}", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.2)
    _style_ax(ax, title="Traffic vs Search Demand (Impressions ÷ 10 for scale)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "master_traffic_search.png")


def chart_top_landing_pages(ga4_pages):
    """Horizontal bar — top landing pages by sessions."""
    if ga4_pages.empty or "sessions" not in ga4_pages.columns:
        return _placeholder("master_top_pages.png")
    df = ga4_pages.copy()
    df = pd.to_numeric(df["sessions"], errors="coerce").fillna(0).to_frame("sessions").join(df.drop(columns=["sessions"]))
    df = df.sort_values("sessions", ascending=True).head(10)
    page_col = "landingPage" if "landingPage" in df.columns else df.columns[0]
    df["label"] = df[page_col].apply(lambda p: short_url(str(p), 45))
    max_v = df["sessions"].max() or 1
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["label"], df["sessions"], color=C_NAVY, zorder=2)
    for bar in bars:
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Landing Pages — Sessions (GA4)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "master_top_pages.png")


def chart_top_queries(gsc_queries):
    """Horizontal bar — top GSC queries by clicks."""
    if gsc_queries.empty:
        return _placeholder("master_top_queries.png")
    df = gsc_queries.copy()
    click_col = "clicks_current" if "clicks_current" in df.columns else "clicks"
    df[click_col] = pd.to_numeric(df[click_col], errors="coerce").fillna(0)
    df = df.sort_values(click_col, ascending=True).head(10)
    query_col = "query" if "query" in df.columns else df.columns[0]
    df["label"] = df[query_col].apply(lambda q: short_url(str(q), 40))
    max_v = df[click_col].max() or 1
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["label"], df[click_col], color=C_TEAL, zorder=2)
    for bar in bars:
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Top Search Queries — Clicks (GSC)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "master_top_queries.png")


def chart_content_category(content_cat):
    """Horizontal bar — content categories by sessions."""
    if content_cat.empty or "category" not in content_cat.columns:
        return _placeholder("master_content_cat.png")
    df = content_cat.copy()
    sess_col = "sessions" if "sessions" in df.columns else df.select_dtypes("number").columns[0]
    df[sess_col] = pd.to_numeric(df[sess_col], errors="coerce").fillna(0)
    df = df.sort_values(sess_col, ascending=True).head(12)
    max_v = df[sess_col].max() or 1
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(df["category"], df[sess_col], color=C_NAVY, zorder=2)
    for bar in bars:
        v = bar.get_width()
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{int(v):,}", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Content Category Performance — Sessions")
    fig.tight_layout(pad=2.0)
    return _save(fig, "master_content_cat.png")


def chart_mobile_speed(speed):
    """Horizontal bar — mobile performance scores per page."""
    if speed.empty or "strategy" not in speed.columns:
        return _placeholder("master_mobile_speed.png")
    mob = speed[speed["strategy"] == "mobile"].copy()
    if mob.empty:
        return _placeholder("master_mobile_speed.png")
    score_col = "performance_score" if "performance_score" in mob.columns else mob.select_dtypes("number").columns[0]
    mob[score_col] = pd.to_numeric(mob[score_col], errors="coerce").fillna(0)
    page_col = "page" if "page" in mob.columns else mob.columns[0]
    mob = mob.sort_values(score_col, ascending=True).head(10)
    mob["label"] = mob[page_col].apply(lambda p: short_url(str(p), 45))
    colors = [C_GREEN if s >= 90 else C_AMBER if s >= 50 else C_CORAL for s in mob[score_col]]
    fig, ax = plt.subplots(figsize=(13, 4.8))
    bars = ax.barh(mob["label"], mob[score_col], color=colors, zorder=2)
    ax.axvline(90, color=C_GREEN, linewidth=1, linestyle="--", alpha=0.6, label="Good (90+)")
    ax.axvline(50, color=C_AMBER, linewidth=1, linestyle="--", alpha=0.6, label="Needs Improvement (50+)")
    for bar in bars:
        v = bar.get_width()
        ax.text(v + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{v:.0f}", va="center", fontsize=8, color="#374151")
    ax.set_xlim(0, 115)
    ax.legend(frameon=False, fontsize=7, loc="lower right")
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    _style_ax(ax, title="Mobile Performance Scores (PageSpeed Insights)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "master_mobile_speed.png")


def chart_keyword_movement(kw_comp):
    """Lollipop — top keyword ranking movers (gainers teal, losers coral)."""
    if kw_comp.empty or "position_change" not in kw_comp.columns:
        return _placeholder("master_kw_movement.png")
    df = kw_comp.copy()
    df["position_change"] = pd.to_numeric(df["position_change"], errors="coerce").fillna(0)
    gainers = df[df["position_change"] < 0].nsmallest(5, "position_change").copy()
    losers  = df[df["position_change"] > 0].nlargest(5, "position_change").copy()
    gainers["delta"] = gainers["position_change"].abs()
    losers["delta"]  = -losers["position_change"].abs()
    gainers["label"] = gainers["keyword"].apply(lambda k: short_url(str(k), 35))
    losers["label"]  = losers["keyword"].apply(lambda k: short_url(str(k), 35))
    plot_df = pd.concat([gainers[["label", "delta"]], losers[["label", "delta"]]]).sort_values("delta")
    if plot_df.empty:
        return _placeholder("master_kw_movement.png")
    fig, ax = plt.subplots(figsize=(13, 4.8))
    ax.axvline(0, color="#888", linewidth=0.8, zorder=1)
    for i, (_, row) in enumerate(plot_df.iterrows()):
        color = C_TEAL if row["delta"] > 0 else C_CORAL
        ax.plot([0, row["delta"]], [i, i], color=color, linewidth=1.5, zorder=2)
        ax.scatter([row["delta"]], [i], color=color, s=55, zorder=3)
    ax.set_yticks(range(len(plot_df)))
    ax.set_yticklabels(plot_df["label"], fontsize=8)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    gain_p = mpatches.Patch(color=C_TEAL,  label="Improved")
    loss_p = mpatches.Patch(color=C_CORAL, label="Declined")
    ax.legend(handles=[gain_p, loss_p], frameon=False, fontsize=8, loc="lower right")
    _style_ax(ax, title="Keyword Ranking Movement (Top Movers)")
    fig.tight_layout(pad=2.0)
    return _save(fig, "master_kw_movement.png")


def build_all_charts(data, kpis):
    return {
        "kpi_overview":    chart_kpi_overview(kpis),
        "traffic_search":  chart_traffic_vs_search(kpis),
        "top_pages":       chart_top_landing_pages(data["ga4_pages"]),
        "top_queries":     chart_top_queries(data["gsc_queries"]),
        "content_cat":     chart_content_category(data["content_cat"]),
        "mobile_speed":    chart_mobile_speed(data["speed"]),
        "kw_movement":     chart_keyword_movement(data["kw_comp"]),
    }


# ══════════════════════════════════════════════════════════════════════════════
# AI ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def build_deterministic_bullets(data, kpis):
    """Hard metric facts — always present even if AI fails."""
    bullets = []

    # Sessions
    s_curr, s_prev = kpis["sessions"]["curr"], kpis["sessions"]["prev"]
    if s_curr > 0:
        chg = s_curr - s_prev
        sign = "+" if chg >= 0 else ""
        pct  = f" ({chg / s_prev:.1%})" if s_prev > 0 else ""
        bullets.append(f"GA4 sessions: {s_curr:,.0f} this week ({sign}{chg:,.0f} WoW{pct}).")

    # Clicks
    c_curr, c_prev = kpis["clicks"]["curr"], kpis["clicks"]["prev"]
    if c_curr > 0:
        chg  = c_curr - c_prev
        sign = "+" if chg >= 0 else ""
        pct  = f" ({chg / c_prev:.1%})" if c_prev > 0 else ""
        bullets.append(f"GSC clicks: {c_curr:,.0f} ({sign}{chg:,.0f} WoW{pct}).")

    # Impressions
    i_curr, i_prev = kpis["impressions"]["curr"], kpis["impressions"]["prev"]
    if i_curr > 0:
        chg  = i_curr - i_prev
        sign = "+" if chg >= 0 else ""
        bullets.append(f"GSC impressions: {i_curr:,.0f} ({sign}{chg:,.0f} WoW).")

    # Avg position
    p_curr, p_prev = kpis["avg_position"]["curr"], kpis["avg_position"]["prev"]
    if p_curr > 0:
        direction = "improved" if p_curr < p_prev else "declined" if p_curr > p_prev else "unchanged"
        bullets.append(f"Average search position: {p_curr:.1f} ({direction} from {p_prev:.1f} previous week).")

    # Mobile speed
    ms = kpis["mobile_score"]["curr"]
    if ms > 0:
        rating = "good" if ms >= 90 else "needs improvement" if ms >= 50 else "poor"
        bullets.append(f"Average mobile PageSpeed score: {ms:.0f} ({rating}).")

    # Keyword movement
    kw = data["kw_comp"]
    if not kw.empty and "ranking_improved" in kw.columns:
        improved = int(kw["ranking_improved"].sum()) if "ranking_improved" in kw.columns else 0
        declined = int(kw["ranking_declined"].sum()) if "ranking_declined" in kw.columns else 0
        if improved or declined:
            bullets.append(f"Tracked keywords: {improved} improved in position, {declined} declined.")

    # Content category leader
    cat = data["content_cat"]
    if not cat.empty and "category" in cat.columns and "sessions" in cat.columns:
        top = cat.sort_values("sessions", ascending=False).iloc[0]
        bullets.append(
            f"Top content category by sessions: {top['category']} ({int(top['sessions']):,} sessions)."
        )

    return bullets


def build_ai_bullets(data, kpis):
    """AI cross-channel interpretation bullets. Returns [] on failure."""
    if not GROQ_API_KEY:
        return []

    def _csv(df, cols=None, n=8):
        if df.empty:
            return "unavailable"
        work = df[cols].head(n) if cols else df.head(n)
        return work.to_csv(index=False)

    ga4_ctx   = _csv(data["ga4_summary"])
    gsc_ctx   = _csv(data["gsc_queries"])
    speed_ctx = _csv(data["speed"][data["speed"]["strategy"] == "mobile"] if not data["speed"].empty and "strategy" in data["speed"].columns else data["speed"])
    cat_ctx   = _csv(data["content_cat"])

    prompt = f"""
You are writing concise executive bullet points for a weekly cross-channel SEO master report.

Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.
Each bullet is one sentence. Maximum 8 bullets total.
Do not invent data. Do not mention AI, models, or automation.
Draw cross-channel correlations: e.g. high impressions but low sessions, speed issues on high-traffic pages, content pillars with engagement gaps.
Focus on actionable insights and risks.
Write as if this is part of a manually produced executive report.

GA4 summary:
{ga4_ctx}

GSC top queries:
{gsc_ctx}

Mobile PageSpeed (top pages):
{speed_ctx}

Content category performance:
{cat_ctx}
"""

    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write polished weekly executive SEO master briefs as bullet points only."},
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
        print(f"AI bullets failed: {e}")
        return []


def build_unified_bullets(data, kpis):
    det = build_deterministic_bullets(data, kpis)
    ai  = build_ai_bullets(data, kpis)
    return det + ai


# ══════════════════════════════════════════════════════════════════════════════
# HTML TABLE BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# HTML DASHBOARD BUILDER
# ══════════════════════════════════════════════════════════════════════════════

FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400'
    '&family=Source+Serif+4:ital,wght@0,300;0,400;0,600;1,400'
    '&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">'
)


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
    """Return an img tag for a chart path, or empty string if path is falsy."""
    if not path:
        return ""
    return (
        f'<div style="width:100%;margin-bottom:24px;">'
        f'<img src="{_html.escape(str(path))}" alt="{_html.escape(alt)}" '
        f'style="width:100%;display:block;border:2px solid #000;">'
        f'</div>'
    )


def _chart_row_2(path_a, alt_a, path_b, alt_b):
    """Two charts side by side."""
    a = (f'<div style="width:calc(50% - 10px);display:inline-block;vertical-align:top;">'
         f'<img src="{_html.escape(str(path_a))}" alt="{_html.escape(alt_a)}" style="width:100%;display:block;border:2px solid #000;"></div>') if path_a else ""
    b = (f'<div style="width:calc(50% - 10px);display:inline-block;vertical-align:top;margin-left:20px;">'
         f'<img src="{_html.escape(str(path_b))}" alt="{_html.escape(alt_b)}" style="width:100%;display:block;border:2px solid #000;"></div>') if path_b else ""
    if not a and not b:
        return ""
    return f'<div style="margin-bottom:24px;">{a}{b}</div>'


def _section(title, content):
    """Wrap content in a titled section with thick rule."""
    return f"""
<div style="padding:40px 0;">
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
    return (
        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;text-transform:uppercase;'
        f'letter-spacing:0.15em;color:#525252;margin-bottom:16px;display:flex;align-items:center;gap:12px;">'
        f'{_html.escape(text)}'
        f'<span style="flex:1;height:1px;background:#E5E5E5;display:inline-block;"></span></div>'
    )


def generate_html_dashboard(bullets, chart_paths, data, kpis):
    """Build the full index.html dashboard in the MM design system."""
    today = date.today().strftime("%B %d, %Y")

    # ── KPI grid (8 cards) ────────────────────────────────────────────────────
    kpi_cards = (
        _kpi_card("Weekly Sessions",    kpis["sessions"]["curr"],    kpis["sessions"]["prev"]) +
        _kpi_card("Active Users",       kpis["users"]["curr"],       kpis["users"]["prev"]) +
        _kpi_card("GSC Clicks",         kpis["clicks"]["curr"],      kpis["clicks"]["prev"]) +
        _kpi_card("GSC Impressions",    kpis["impressions"]["curr"], kpis["impressions"]["prev"]) +
        _kpi_card("Avg Position",       kpis["avg_position"]["curr"],kpis["avg_position"]["prev"], lower_better=True, decimals=1) +
        _kpi_card("Mobile Speed Score", kpis["mobile_score"]["curr"],kpis["mobile_score"]["prev"], decimals=0)
    )
    kpi_grid = (
        f'<div style="display:grid;grid-template-columns:repeat(6,1fr);border:2px solid #000;margin-bottom:0;">'
        f'{kpi_cards}</div>'
    )

    # ── Tables ────────────────────────────────────────────────────────────────
    ga4_pages   = data["ga4_pages"]
    gsc_queries = data["gsc_queries"]
    speed       = data["speed"]
    content_cat = data["content_cat"]

    page_col  = "landingPage" if "landingPage" in ga4_pages.columns else (ga4_pages.columns[0] if not ga4_pages.empty else "page")
    ga4_tbl   = _build_html_table(ga4_pages.head(10),  [page_col, "sessions", "activeUsers", "engagementRate"],
                                  ["Landing Page", "Sessions", "Users", "Eng Rate"])

    q_col     = "query" if "query" in gsc_queries.columns else (gsc_queries.columns[0] if not gsc_queries.empty else "query")
    c_col     = "clicks_current" if "clicks_current" in gsc_queries.columns else "clicks"
    i_col     = "impressions_current" if "impressions_current" in gsc_queries.columns else "impressions"
    p_col     = "position_current" if "position_current" in gsc_queries.columns else "position"
    gsc_tbl   = _build_html_table(gsc_queries.head(10), [q_col, c_col, i_col, p_col],
                                  ["Query", "Clicks", "Impressions", "Position"])

    speed_mob = speed[speed["strategy"] == "mobile"].head(10) if not speed.empty and "strategy" in speed.columns else pd.DataFrame()
    spd_page  = "page" if "page" in speed_mob.columns else (speed_mob.columns[0] if not speed_mob.empty else "page")
    speed_tbl = _build_html_table(speed_mob, [spd_page, "performance_score", "lcp_field_ms", "cls_field"],
                                  ["Page", "Mobile Score", "LCP (ms)", "CLS"])

    cat_cols  = [c for c in ["category", "sessions", "clicks", "engagement_rate", "avg_duration"] if c in content_cat.columns]
    cat_hdrs  = [c.replace("_", " ").title() for c in cat_cols]
    cat_tbl   = _build_html_table(content_cat.head(12), cat_cols, cat_hdrs)

    # ── Body ──────────────────────────────────────────────────────────────────
    body = f"""
<header style="background:#000;color:#fff;padding:40px 48px;margin:0 -40px 0;position:relative;overflow:hidden;">
  <div style="font-family:'JetBrains Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:0.2em;color:#999;margin-bottom:12px;">CIM SEO Intelligence</div>
  <h1 style="font-family:'Playfair Display',Georgia,serif;font-size:clamp(28px,4vw,56px);font-weight:900;line-height:1;letter-spacing:-0.02em;color:#fff;margin-bottom:16px;">Weekly SEO<br>Master Report</h1>
  <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:#666;letter-spacing:0.05em;">
    <span style="display:inline-block;width:24px;height:2px;background:#fff;vertical-align:middle;margin-right:16px;"></span>
    Generated {today}
  </div>
</header>
<hr style="border:none;border-top:4px solid #000;margin:0;">

<div style="padding:40px 0;">
  {kpi_grid}
</div>
<hr style="border:none;border-top:4px solid #000;margin:0;">

{_section("Executive Summary",
    _panel_label("Cross-Channel Analysis") + _exec_bullets(bullets)
)}

{_section("Performance Overview",
    '<div class="col-header">Weekly KPI Overview</div>' +
    _img_tag(chart_paths.get("kpi_overview"), "Weekly KPI overview") +
    '<div class="col-header">Traffic vs Search Demand</div>' +
    _img_tag(chart_paths.get("traffic_search"), "Traffic vs search demand")
)}

{_section("Top Landing Pages & Search Queries",
    '<div class="col-header">Top Landing Pages by Sessions</div>' +
    _img_tag(chart_paths.get("top_pages"),   "Top landing pages by sessions") +
    '<div class="col-header">Top Search Queries by Clicks</div>' +
    _img_tag(chart_paths.get("top_queries"),  "Top search queries by clicks")
)}

{_section("Keyword Ranking Movement",
    _img_tag(chart_paths.get("kw_movement"), "Keyword ranking movement")
)}

{_section("Content Category Performance",
    _img_tag(chart_paths.get("content_cat"), "Content category performance") + cat_tbl
)}

{_section("Mobile PageSpeed",
    _img_tag(chart_paths.get("mobile_speed"), "Mobile performance scores") + speed_tbl
)}

{_section("Top Landing Pages — Detail",
    ga4_tbl
)}

{_section("Top Search Queries — Detail",
    gsc_tbl
)}

<hr style="border:none;border-top:4px solid #000;margin:0;">
<footer style="padding:32px 0;display:flex;justify-content:space-between;align-items:center;">
  <span style="font-family:'Playfair Display',Georgia,serif;font-size:13px;font-weight:700;letter-spacing:0.05em;">CIM SEO Intelligence</span>
  <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#525252;text-transform:uppercase;letter-spacing:0.12em;">Generated {today}</span>
</footer>
"""

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CIM SEO Master Report — {today}</title>
{FONT_LINK}
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ background: #fff; }}
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
</style>
</head>
<body>
{body}
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_doc)
    print("Dashboard generated as index.html")


# ══════════════════════════════════════════════════════════════════════════════
# MONDAY.COM
# ══════════════════════════════════════════════════════════════════════════════

def post_to_monday(bullets):
    """Post the unified bullet summary to Monday.com. Non-fatal."""
    if not MONDAY_API_TOKEN or not MONDAY_MASTER_ITEM_ID:
        print("Monday master update skipped: MONDAY_API_TOKEN or MONDAY_MASTER_ITEM_ID not set.")
        return

    bullet_html = "".join(f"<li>{_html.escape(b)}</li>" for b in bullets)
    body = (
        f"<h2>Weekly SEO Master Report — {date.today().strftime('%B %d, %Y')}</h2>"
        f"<ul>{bullet_html}</ul>"
        f'<br>📊 <a href="https://snymsood.github.io/CIM-SEO">View live dashboard</a>'
    )

    mutation = """
    mutation ($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) { id }
    }
    """
    try:
        resp = requests.post(
            "https://api.monday.com/v2",
            headers={"Authorization": MONDAY_API_TOKEN, "Content-Type": "application/json"},
            json={"query": mutation, "variables": {"item_id": str(MONDAY_MASTER_ITEM_ID), "body": body}},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            print(f"Monday update error: {data['errors']}")
        else:
            print("Posted master summary to Monday.com.")
    except Exception as e:
        print(f"Monday master post failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("--- STARTING MASTER ORCHESTRATOR ---")
    asyncio.run(run_all_scripts())

    print("--- LOADING DATA ---")
    data = load_all_data()
    kpis = aggregate_kpis(data)

    print("--- BUILDING CHARTS ---")
    chart_paths = build_all_charts(data, kpis)

    print("--- BUILDING EXECUTIVE BULLETS ---")
    bullets = build_unified_bullets(data, kpis)

    print("--- GENERATING DASHBOARD ---")
    generate_html_dashboard(bullets, chart_paths, data, kpis)

    print("--- POSTING TO MONDAY.COM ---")
    try:
        post_to_monday(bullets)
    except Exception as e:
        print(f"Monday post failed: {e}")

    # ── Weekly Intelligence Layer ──────────────────────────────────────────────
    # Runs after all existing reports. Non-fatal: failure does not block outputs.
    enable_intel = os.getenv("ENABLE_WEEKLY_INTELLIGENCE", "true").lower() == "true"
    if enable_intel:
        print("--- RUNNING WEEKLY SEO INTELLIGENCE LAYER ---")
        try:
            import weekly_seo_intelligence as _intel
            _intel.main(dry_run=False)
        except Exception as e:
            print(f"Weekly intelligence layer failed (non-fatal): {e}")
            import traceback
            traceback.print_exc()
    else:
        print("--- WEEKLY INTELLIGENCE LAYER DISABLED (ENABLE_WEEKLY_INTELLIGENCE=false) ---")

    print("--- MASTER ORCHESTRATOR COMPLETE ---")


if __name__ == "__main__":
    main()
