# ══════════════════════════════════════════════════════════════════════════════
# broken_link_check.py
# CIM SEO — Broken Link & Technical Audit
# Redesigned per report_design_principles.md
# ══════════════════════════════════════════════════════════════════════════════

from collections import deque
from datetime import date
from openai import OpenAI
from urllib.parse import urljoin, urlparse, urldefrag
from bs4 import BeautifulSoup
from pathlib import Path
import asyncio
import aiohttp
import pandas as pd
import requests
import os
import html
import math
import base64
import re
import time
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from pdf_report_formatter import format_pct_change, format_num
from google_sheets_db import append_to_sheet
from seo_utils import short_url

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN  = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID    = os.getenv("MONDAY_ITEM_ID")
MONDAY_API_URL    = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"

SEED_FILE             = "broken_link_seed_domains.csv"
MAX_PAGES_PER_DOMAIN  = 200
REQUEST_TIMEOUT       = 30
CRAWL_DELAY_SECONDS   = 0.4
CHARTS_DIR            = Path("charts")

# ── Brand palette (report_design_principles.md §1) ────────────────────────────
C_NAVY   = "#212878"
C_TEAL   = "#2A9D8F"
C_CORAL  = "#E76F51"
C_SLATE  = "#6C757D"
C_GREEN  = "#059669"
C_RED    = "#DC2626"
C_AMBER  = "#D97706"
C_LIGHT  = "#F1F5F9"
C_BORDER = "#E2E8F0"

# Issue type → display colour mapping
ISSUE_COLORS = {
    "broken":       C_RED,
    "client_error": C_AMBER,
    "server_error": C_CORAL,
    "redirect":     C_TEAL,
    "error":        C_SLATE,
    "ok":           C_GREEN,
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "CIM-SEO-LinkChecker/1.0"})


# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING — Crawl
# ══════════════════════════════════════════════════════════════════════════════

def load_seed_domains():
    df = pd.read_csv(SEED_FILE)
    df["seed_url"]   = df["seed_url"].astype(str).str.strip()
    df["scope_type"] = df["scope_type"].astype(str).str.strip()
    df["priority"]   = df["priority"].astype(str).str.strip()
    return df


def get_allowed_hosts(seed_df):
    hosts = set()
    for url in seed_df["seed_url"].tolist():
        host = urlparse(url).netloc.lower()
        if host:
            hosts.add(host)
    return hosts


def normalize_url(url):
    url, _ = urldefrag(url.strip())
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    return parsed._replace(fragment="").geturl()


def is_html_response(response):
    return "text/html" in response.headers.get("Content-Type", "").lower()


def should_crawl_url(url, allowed_hosts):
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc.lower() not in allowed_hosts:
        return False
    blocked_ext = (
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".zip", ".xml", ".json", ".doc", ".docx", ".xls", ".xlsx",
        ".ppt", ".pptx", ".mp4", ".mp3", ".css", ".js",
    )
    if parsed.path.lower().endswith(blocked_ext):
        return False
    return True


def fetch_page(url):
    return SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)


def extract_links_from_html(base_url, html_text, allowed_hosts):
    soup = BeautifulSoup(html_text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href:
            continue
        absolute  = urljoin(base_url, href)
        normalized = normalize_url(absolute)
        if not normalized:
            continue
        if urlparse(normalized).netloc.lower() not in allowed_hosts:
            continue
        links.append({
            "source_url":  base_url,
            "target_url":  normalized,
            "anchor_text": a.get_text(" ", strip=True)[:200],
        })
    return links


def classify_status(status_code, error, redirect_count):
    if error:
        return "error"
    if status_code is None:
        return "error"
    if status_code >= 500:
        return "server_error"
    if status_code in (404, 410):
        return "broken"
    if 400 <= status_code < 500:
        return "client_error"
    if redirect_count and redirect_count > 0:
        return "redirect"
    if 200 <= status_code < 300:
        return "ok"
    return "other"


def crawl_site(seed_df):
    """Breadth-first crawl across all seed domains. Returns DataFrame of discovered links."""
    allowed_hosts    = get_allowed_hosts(seed_df)
    visited_pages    = set()
    discovered_links = []
    queue            = deque()
    host_page_counts = {host: 0 for host in allowed_hosts}

    for seed_url in seed_df["seed_url"].tolist():
        normalized = normalize_url(seed_url)
        if normalized:
            queue.append(normalized)

    while queue:
        current_url = queue.popleft()
        if current_url in visited_pages:
            continue
        host = urlparse(current_url).netloc.lower()
        if host_page_counts.get(host, 0) >= MAX_PAGES_PER_DOMAIN:
            continue

        try:
            response = fetch_page(current_url)
            print(f"  Crawled {current_url} → {response.status_code}", flush=True)
        except Exception as e:
            print(f"  ✗ Failed {current_url}: {e}", flush=True)
            visited_pages.add(current_url)
            host_page_counts[host] = host_page_counts.get(host, 0) + 1
            continue

        visited_pages.add(current_url)
        host_page_counts[host] = host_page_counts.get(host, 0) + 1

        if response.status_code >= 400 or not is_html_response(response):
            time.sleep(CRAWL_DELAY_SECONDS)
            continue

        extracted = extract_links_from_html(current_url, response.text, allowed_hosts)
        discovered_links.extend(extracted)

        for link in extracted:
            target = link["target_url"]
            if should_crawl_url(target, allowed_hosts) and target not in visited_pages:
                queue.append(target)

        time.sleep(CRAWL_DELAY_SECONDS)

    df = pd.DataFrame(discovered_links)
    return df.drop_duplicates() if not df.empty else df


# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING — Async Link Validation
# ══════════════════════════════════════════════════════════════════════════════

async def _check_one_link(session, semaphore, url):
    """Check a single URL: HEAD first, fall back to GET on 405/5xx."""
    async with semaphore:
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with session.head(url, timeout=timeout, allow_redirects=True) as resp:
                status_code   = resp.status
                final_url     = str(resp.url)
                redirect_count = len(resp.history)
            if status_code == 405 or status_code >= 500:
                async with session.get(url, timeout=timeout, allow_redirects=True) as resp2:
                    status_code    = resp2.status
                    final_url      = str(resp2.url)
                    redirect_count = len(resp2.history)
            return {
                "target_url":    url,
                "status_code":   status_code,
                "final_url":     final_url,
                "redirect_count": redirect_count,
                "error":         None,
            }
        except Exception as exc:
            return {
                "target_url":    url,
                "status_code":   None,
                "final_url":     None,
                "redirect_count": None,
                "error":         str(exc),
            }


async def _evaluate_links_async(links_df):
    if links_df.empty:
        return pd.DataFrame(columns=[
            "source_url", "target_url", "anchor_text", "status_code",
            "final_url", "redirect_count", "error", "issue_type",
        ])

    unique_targets = links_df["target_url"].dropna().unique().tolist()
    semaphore  = asyncio.Semaphore(15)
    connector  = aiohttp.TCPConnector(limit=20)
    headers    = {"User-Agent": "CIM-SEO-LinkChecker/1.0"}

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        tasks       = [_check_one_link(session, semaphore, url) for url in unique_targets]
        raw_results = await asyncio.gather(*tasks)

    status_rows = []
    for result in raw_results:
        result["issue_type"] = classify_status(
            result["status_code"], result["error"], result["redirect_count"]
        )
        status_rows.append(result)
        print(f"  Checked {result['target_url']} → {result['issue_type']}", flush=True)

    status_df = pd.DataFrame(status_rows)
    return pd.merge(links_df, status_df, on="target_url", how="left")


def evaluate_links(links_df):
    return asyncio.run(_evaluate_links_async(links_df))


# ══════════════════════════════════════════════════════════════════════════════
# DATA PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

def compute_kpis(results_df):
    """Return a dict of aggregate counts for KPI cards."""
    if results_df.empty:
        return {k: 0 for k in ("source_pages", "total_links", "broken", "client_error",
                                "server_error", "redirect", "error", "ok")}
    return {
        "source_pages":  int(results_df["source_url"].nunique()),
        "total_links":   int(len(results_df)),
        "broken":        int((results_df["issue_type"] == "broken").sum()),
        "client_error":  int((results_df["issue_type"] == "client_error").sum()),
        "server_error":  int((results_df["issue_type"] == "server_error").sum()),
        "redirect":      int((results_df["issue_type"] == "redirect").sum()),
        "error":         int((results_df["issue_type"] == "error").sum()),
        "ok":            int((results_df["issue_type"] == "ok").sum()),
    }


def _fmt(val, decimals=0, pct=False):
    """Lightweight number formatter for table cells."""
    try:
        v = float(val)
        if math.isnan(v):
            return "-"
        if v == 0:
            return "-"
        if pct:
            return f"{v:.2%}"
        if decimals == 0:
            return f"{v:,.0f}"
        return f"{v:,.{decimals}f}"
    except (TypeError, ValueError):
        s = str(val)
        return s[:57] + "..." if len(s) > 60 else s


def _delta_html(val, decimals=0, lower_is_better=False):
    """Return a coloured delta span (monochrome border style)."""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "-"
    if math.isclose(v, 0, abs_tol=1e-5):
        return '<span class="chg neu">—</span>'
    positive_good = (v > 0 and not lower_is_better) or (v < 0 and lower_is_better)
    cls  = "pos" if positive_good else "neg"
    sign = "+" if v > 0 else ""
    return f'<span class="chg {cls}">{sign}{v:.{decimals}f}</span>'


def _issue_badge(issue_type):
    """Return a styled badge for an issue type."""
    labels = {
        "broken":       ("404/410", "background:#000;color:#fff;"),
        "client_error": ("4xx",     "background:#fff;color:#000;border-color:#D97706;"),
        "server_error": ("5xx",     "background:#fff;color:#000;border-color:#E76F51;"),
        "redirect":     ("Redirect","background:#fff;color:#000;border-color:#2A9D8F;"),
        "error":        ("Timeout", "background:#fff;color:#6C757D;border-color:#E2E8F0;"),
        "ok":           ("OK",      "background:#fff;color:#059669;border-color:#059669;"),
    }
    label, style = labels.get(issue_type, (issue_type, ""))
    return (
        f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:8px;font-weight:700;'
        f'padding:2px 6px;border:1px solid #000;text-transform:uppercase;'
        f'letter-spacing:0.05em;{style}">{html.escape(label)}</span>'
    )


def _bar_cell(value, max_value, color=C_NAVY):
    """Table cell with inline proportional bar."""
    if max_value <= 0:
        return f"<td>{_fmt(value)}</td>"
    pct = min(value / max_value * 100, 100)
    return (
        f'<td><div style="display:flex;align-items:center;gap:6px;">'
        f'<div style="width:{pct:.1f}%;max-width:80px;height:8px;'
        f'background:{color};border-radius:0;flex-shrink:0;"></div>'
        f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:9px;color:#374151;">'
        f'{_fmt(value)}</span></div></td>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# CHART GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _style_ax(ax, title="", xlabel="", ylabel=""):
    """Shared axes styling — report_design_principles.md §6."""
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
    CHARTS_DIR.mkdir(exist_ok=True)
    path = CHARTS_DIR / filename
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def plot_issue_breakdown(kpis):
    """Horizontal stacked bar showing issue type distribution — half page."""
    categories = ["broken", "client_error", "server_error", "redirect", "error"]
    labels     = ["Broken (404/410)", "4xx Other", "5xx Server", "Redirect", "Timeout/Error"]
    colors     = [C_RED, C_AMBER, C_CORAL, C_TEAL, C_SLATE]
    values     = [kpis[c] for c in categories]
    total      = sum(values)

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")

    if total == 0:
        ax.text(0.5, 0.5, "No issues found — all links returned 200 OK.",
                ha="center", va="center", fontsize=12, color="#94A3B8",
                transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "issue_breakdown.png")

    left = 0
    for val, label, color in zip(values, labels, colors):
        if val == 0:
            continue
        pct = val / total * 100
        ax.barh(0, pct, left=left, color=color, height=0.55)
        if pct > 5:
            ax.text(left + pct / 2, 0, f"{label}\n{val:,} ({pct:.1f}%)",
                    ha="center", va="center", fontsize=9, color="white", fontweight="600")
        left += pct

    ax.set_xlim(0, 100)
    ax.set_yticks([])
    _style_ax(ax, title=f"Issue Distribution — {total:,} total links with issues")
    ax.spines["left"].set_visible(False)
    ax.tick_params(labelsize=9, colors="#64748B", length=0)
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    fig.tight_layout(pad=2.0)
    return _save(fig, "issue_breakdown.png")


def plot_domain_health(results_df):
    """Grouped bar chart: issue counts per domain — half page."""
    if results_df.empty:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No data available.", ha="center", va="center",
                fontsize=12, color="#94A3B8", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "domain_health.png")

    results_df = results_df.copy()
    results_df["domain"] = results_df["source_url"].apply(
        lambda u: urlparse(u).netloc.replace("www.", "")
    )

    pivot = (
        results_df[results_df["issue_type"] != "ok"]
        .groupby(["domain", "issue_type"])
        .size()
        .unstack(fill_value=0)
    )
    # Ensure all columns exist
    for col in ["broken", "client_error", "server_error", "redirect", "error"]:
        if col not in pivot.columns:
            pivot[col] = 0

    pivot = pivot[["broken", "client_error", "server_error", "redirect", "error"]]
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("total", ascending=True).drop(columns="total")

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")

    bar_colors  = [C_RED, C_AMBER, C_CORAL, C_TEAL, C_SLATE]
    bar_labels  = ["Broken", "4xx", "5xx", "Redirect", "Error"]
    x           = np.arange(len(pivot))
    width       = 0.15
    offsets     = [-2, -1, 0, 1, 2]

    for i, (col, color, label) in enumerate(zip(pivot.columns, bar_colors, bar_labels)):
        bars = ax.bar(x + offsets[i] * width, pivot[col], width=width,
                      color=color, label=label, zorder=2)
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, h + 0.3,
                        str(int(h)), ha="center", va="bottom", fontsize=7,
                        color="#374151", fontweight="600")

    ax.set_xticks(x)
    ax.set_xticklabels(pivot.index, fontsize=9, rotation=15, ha="right")
    ax.legend(fontsize=8, frameon=False, loc="upper left", ncol=5)
    _style_ax(ax, title="Issue Count by Domain", ylabel="Issues")
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    fig.tight_layout(pad=2.0)
    return _save(fig, "domain_health.png")


def plot_status_code_distribution(results_df):
    """Horizontal bar chart of top status codes — half page."""
    if results_df.empty or "status_code" not in results_df.columns:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No status code data available.", ha="center", va="center",
                fontsize=12, color="#94A3B8", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "status_codes.png")

    counts = (
        results_df["status_code"]
        .dropna()
        .astype(int)
        .value_counts()
        .sort_values(ascending=True)
        .tail(12)
    )

    def _code_color(code):
        if code in (404, 410):
            return C_RED
        if 400 <= code < 500:
            return C_AMBER
        if code >= 500:
            return C_CORAL
        if code in (301, 302, 307, 308):
            return C_TEAL
        return C_GREEN

    colors = [_code_color(c) for c in counts.index]

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")

    bars = ax.barh(counts.index.astype(str), counts.values, color=colors, height=0.55, zorder=2)
    max_v = counts.max()
    for bar, v in zip(bars, counts.values):
        ax.text(v + max_v * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{v:,}", va="center", fontsize=9, color="#374151")
    ax.set_xlim(0, max_v * 1.18)
    _style_ax(ax, title="Links by HTTP Status Code", xlabel="Count")
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    fig.tight_layout(pad=2.0)
    return _save(fig, "status_codes.png")


def plot_top_broken_sources(results_df, n=15):
    """Lollipop chart: pages with the most broken outbound links — half page."""
    broken_df = results_df[results_df["issue_type"] == "broken"].copy()

    if broken_df.empty:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No broken links found — great link hygiene!",
                ha="center", va="center", fontsize=12, color="#94A3B8",
                transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "top_broken_sources.png")

    source_counts = (
        broken_df.groupby("source_url")
        .size()
        .sort_values(ascending=True)
        .tail(n)
    )

    labels = [short_url(u, 55) for u in source_counts.index]
    values = source_counts.values.tolist()

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")

    y_pos = range(len(labels))
    for y, v in zip(y_pos, values):
        ax.plot([0, v], [y, y], color=C_RED, linewidth=2.0, zorder=2, solid_capstyle="round")
        ax.scatter([v], [y], color=C_RED, s=70, zorder=3, edgecolors="white", linewidths=0.8)
        ax.text(v + max(values) * 0.02, y, str(v), va="center", ha="left",
                fontsize=9, color=C_RED, fontweight="600")

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=8)
    ax.axvline(0, color="#374151", linewidth=1.0, zorder=1)
    _style_ax(ax, title=f"Pages with Most Broken Outbound Links (top {n})",
              xlabel="Broken Link Count")
    ax.grid(axis="x", linestyle="--", alpha=0.3, color=C_BORDER, zorder=0)
    ax.set_xlim(0, max(values) * 1.25)
    fig.tight_layout(pad=2.0)
    return _save(fig, "top_broken_sources.png")


def plot_redirect_chain_depth(results_df):
    """Bar chart of redirect hop depth distribution — half page."""
    redirect_df = results_df[results_df["issue_type"] == "redirect"].copy()

    if redirect_df.empty:
        fig, ax = plt.subplots(figsize=(13, 4.8))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No redirect chains found.",
                ha="center", va="center", fontsize=12, color="#94A3B8",
                transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "redirect_depth.png")

    redirect_df["redirect_count"] = pd.to_numeric(
        redirect_df["redirect_count"], errors="coerce"
    ).fillna(1).astype(int)

    counts = redirect_df["redirect_count"].value_counts().sort_index()
    colors = [C_TEAL if h == 1 else C_AMBER if h == 2 else C_CORAL for h in counts.index]

    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")

    bars = ax.bar(counts.index.astype(str), counts.values, color=colors, width=0.55, zorder=2)
    for bar, v in zip(bars, counts.values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                str(v), ha="center", va="bottom", fontsize=9,
                color="#374151", fontweight="600")

    _style_ax(ax, title="Redirect Chain Depth Distribution",
              xlabel="Number of Hops", ylabel="Link Count")
    ax.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    fig.tight_layout(pad=2.0)
    return _save(fig, "redirect_depth.png")


def plot_issue_heatmap(results_df):
    """Heatmap: domains (rows) × issue types (cols) — full page."""
    if results_df.empty:
        fig, ax = plt.subplots(figsize=(13, 6.5))
        fig.patch.set_facecolor("white")
        ax.text(0.5, 0.5, "No data available.", ha="center", va="center",
                fontsize=12, color="#94A3B8", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, "issue_heatmap.png")

    results_df = results_df.copy()
    results_df["domain"] = results_df["source_url"].apply(
        lambda u: urlparse(u).netloc.replace("www.", "")
    )

    pivot = (
        results_df[results_df["issue_type"] != "ok"]
        .groupby(["domain", "issue_type"])
        .size()
        .unstack(fill_value=0)
    )
    for col in ["broken", "client_error", "server_error", "redirect", "error"]:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot = pivot[["broken", "client_error", "server_error", "redirect", "error"]]
    col_labels = ["Broken\n(404/410)", "4xx\nOther", "5xx\nServer", "Redirect", "Timeout\nError"]

    fig, ax = plt.subplots(figsize=(13, 6.5))
    fig.patch.set_facecolor("white")

    data = pivot.values.astype(float)
    # Normalize per row for colour intensity
    row_max = data.max(axis=1, keepdims=True)
    row_max[row_max == 0] = 1
    norm_data = data / row_max

    im = ax.imshow(norm_data, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=1)

    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, fontsize=9)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=9)

    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = int(data[i, j])
            text_color = "white" if norm_data[i, j] > 0.6 else "#374151"
            ax.text(j, i, str(val) if val > 0 else "—",
                    ha="center", va="center", fontsize=10,
                    color=text_color, fontweight="600")

    cbar = fig.colorbar(im, ax=ax, pad=0.02, shrink=0.8)
    cbar.set_label("Relative severity (row-normalised)", fontsize=8, color="#64748B")
    cbar.ax.tick_params(labelsize=7)

    ax.set_title("Domain × Issue Type Heatmap  ·  cell = count  ·  colour = relative severity",
                 fontsize=10, fontweight="600", color="#1A1A1A", pad=10, loc="left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(C_BORDER)
    ax.spines["bottom"].set_color(C_BORDER)
    fig.tight_layout(pad=2.0)
    return _save(fig, "issue_heatmap.png")


def build_all_charts(results_df, kpis):
    """Generate all charts and return {name: Path}."""
    print("  Generating charts…", flush=True)
    return {
        "issue_breakdown":    plot_issue_breakdown(kpis),
        "domain_health":      plot_domain_health(results_df),
        "status_codes":       plot_status_code_distribution(results_df),
        "top_broken_sources": plot_top_broken_sources(results_df),
        "redirect_depth":     plot_redirect_chain_depth(results_df),
        "issue_heatmap":      plot_issue_heatmap(results_df),
    }


# ══════════════════════════════════════════════════════════════════════════════
# AI ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def build_deterministic_bullets(results_df, kpis):
    """Hard-metric bullets — always present even if AI fails."""
    bullets = []
    total   = kpis["total_links"]
    sources = kpis["source_pages"]

    bullets.append(
        f"Crawler audited {sources:,} source pages and checked {total:,} internal links across {len(pd.read_csv(SEED_FILE))} CIM domains."
    )

    broken = kpis["broken"]
    if broken == 0:
        bullets.append("No broken links (404/410) were found — internal link integrity is clean.")
    else:
        pct = broken / total * 100 if total else 0
        bullets.append(
            f"{broken:,} broken links returned 404 or 410 ({pct:.1f}% of all links checked)."
        )

    server = kpis["server_error"]
    if server > 0:
        bullets.append(f"{server:,} links returned 5xx server errors, indicating intermittent server instability.")

    client = kpis["client_error"]
    if client > 0:
        bullets.append(f"{client:,} links returned other 4xx client errors (e.g. 403 Forbidden, 401 Unauthorized).")

    redirects = kpis["redirect"]
    if redirects > 0:
        pct_r = redirects / total * 100 if total else 0
        bullets.append(
            f"{redirects:,} internal links resolve through redirects ({pct_r:.1f}%) — each adds latency and dilutes link equity."
        )

    errors = kpis["error"]
    if errors > 0:
        bullets.append(f"{errors:,} links failed due to timeout or connection errors and could not be verified.")

    return bullets


def build_ai_bullets(results_df, kpis):
    """Call Groq/Llama for interpretive bullets. Returns [] on failure."""
    if not GROQ_API_KEY:
        return []

    issue_df = results_df[results_df["issue_type"] != "ok"].copy()
    if issue_df.empty:
        return []

    top_issues = issue_df[[
        "source_url", "target_url", "status_code", "issue_type", "redirect_count"
    ]].head(25)

    # Domain-level summary for richer context
    issue_df["domain"] = issue_df["source_url"].apply(
        lambda u: urlparse(u).netloc.replace("www.", "")
    )
    domain_summary = (
        issue_df.groupby(["domain", "issue_type"])
        .size()
        .unstack(fill_value=0)
        .to_csv()
    )

    prompt = f"""You are writing a concise broken-link audit brief for SEO stakeholders.

Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.
Each bullet is one sentence. Maximum 8 bullets total.
Cover: key risks, worst-affected domains, redirect chain concerns, recommended fix priorities.
Do not repeat raw numbers already in the data — interpret and prioritise.
Professional corporate tone. Under 200 words total.
Do not invent data.

Overall counts:
- Source pages crawled: {kpis['source_pages']:,}
- Total links checked: {kpis['total_links']:,}
- Broken (404/410): {kpis['broken']:,}
- 4xx other: {kpis['client_error']:,}
- 5xx server errors: {kpis['server_error']:,}
- Redirects: {kpis['redirect']:,}
- Timeouts/errors: {kpis['error']:,}

Domain-level breakdown:
{domain_summary}

Sample issues (top 25):
{top_issues.to_csv(index=False)}
"""

    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write precise weekly technical SEO audit briefs as bullet points only."},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.2,
        )
        raw = resp.choices[0].message.content.strip()
        bullets = []
        for line in raw.splitlines():
            clean = line.strip().lstrip("-•*·▪▸").strip()
            clean = clean.replace("**", "").replace("__", "").replace("*", "").strip()
            if clean:
                bullets.append(clean)
        return bullets
    except Exception as e:
        print(f"  AI analysis failed: {e}", flush=True)
        return []


def build_unified_bullets(results_df, kpis):
    det = build_deterministic_bullets(results_df, kpis)
    ai  = build_ai_bullets(results_df, kpis)
    return det + ai


# ══════════════════════════════════════════════════════════════════════════════
# HTML TABLE BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def build_issues_table(df, n=50):
    """Broken / error links table with inline bar, badge, and status."""
    if df.empty:
        return "<p style=\"font-family:'JetBrains Mono',monospace;font-size:10px;color:#94A3B8;\">No issues found.</p>"

    work = df.head(n).copy()
    max_redirects = work["redirect_count"].fillna(0).astype(float).max() if "redirect_count" in work.columns else 0

    headers = ["#", "Source Page", "Target URL", "Anchor Text", "Status", "Type", "Hops"]
    th = "".join(f"<th>{h}</th>" for h in headers)

    rows_html = []
    for i, (_, row) in enumerate(work.iterrows(), 1):
        issue = str(row.get("issue_type", ""))
        border_color = ISSUE_COLORS.get(issue, C_SLATE)
        source  = html.escape(short_url(str(row.get("source_url", "")), 45))
        target  = html.escape(short_url(str(row.get("target_url", "")), 45))
        anchor  = html.escape(str(row.get("anchor_text", ""))[:40])
        status  = _fmt(row.get("status_code", ""))
        badge   = _issue_badge(issue)
        hops    = _fmt(row.get("redirect_count", 0))

        rows_html.append(
            f'<tr style="border-left:3px solid {border_color};">'
            f"<td style='color:#94A3B8;font-size:9px;width:18px;'>{i}</td>"
            f"<td class='url-cell'>{source}</td>"
            f"<td class='url-cell'>{target}</td>"
            f"<td style='font-size:9px;color:#525252;'>{anchor}</td>"
            f"<td style='white-space:nowrap;font-family:\"JetBrains Mono\",monospace;font-size:10px;'>{status}</td>"
            f"<td style='white-space:nowrap;'>{badge}</td>"
            f"<td style='white-space:nowrap;font-family:\"JetBrains Mono\",monospace;font-size:10px;'>{hops}</td>"
            f"</tr>"
        )

    return (
        f"<table><thead><tr>{th}</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table>"
    )


def build_redirect_table(df, n=50):
    """Redirect chains table showing original → final URL and hop count."""
    if df.empty:
        return "<p style=\"font-family:'JetBrains Mono',monospace;font-size:10px;color:#94A3B8;\">No redirects found.</p>"

    work = df.head(n).copy()
    headers = ["#", "Source Page", "Original Target", "Final URL", "Hops", "Final Status"]
    th = "".join(f"<th>{h}</th>" for h in headers)

    rows_html = []
    for i, (_, row) in enumerate(work.iterrows(), 1):
        hops = int(row.get("redirect_count", 1))
        hop_color = C_TEAL if hops == 1 else C_AMBER if hops == 2 else C_CORAL
        source  = html.escape(short_url(str(row.get("source_url", "")), 40))
        target  = html.escape(short_url(str(row.get("target_url", "")), 40))
        final   = html.escape(short_url(str(row.get("final_url", "")), 40))
        status  = _fmt(row.get("status_code", ""))

        rows_html.append(
            f'<tr style="border-left:3px solid {hop_color};">'
            f"<td style='color:#94A3B8;font-size:9px;width:18px;'>{i}</td>"
            f"<td class='url-cell'>{source}</td>"
            f"<td class='url-cell'>{target}</td>"
            f"<td class='url-cell'>{final}</td>"
            f"<td style='white-space:nowrap;font-family:\"JetBrains Mono\",monospace;font-size:10px;"
            f"color:{hop_color};font-weight:700;'>{hops}</td>"
            f"<td style='white-space:nowrap;font-family:\"JetBrains Mono\",monospace;font-size:10px;'>{status}</td>"
            f"</tr>"
        )

    return (
        f"<table><thead><tr>{th}</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table>"
    )


def build_domain_summary_table(results_df):
    """Per-domain issue summary table."""
    if results_df.empty:
        return "<p style=\"font-family:'JetBrains Mono',monospace;font-size:10px;color:#94A3B8;\">No data.</p>"

    df = results_df.copy()
    df["domain"] = df["source_url"].apply(lambda u: urlparse(u).netloc.replace("www.", ""))

    summary = df.groupby("domain").agg(
        pages_crawled=("source_url", "nunique"),
        total_links=("target_url", "count"),
        broken=("issue_type", lambda x: (x == "broken").sum()),
        redirects=("issue_type", lambda x: (x == "redirect").sum()),
        server_errors=("issue_type", lambda x: (x == "server_error").sum()),
        ok=("issue_type", lambda x: (x == "ok").sum()),
    ).reset_index()

    summary["health_pct"] = (summary["ok"] / summary["total_links"] * 100).round(1)
    summary = summary.sort_values("broken", ascending=False)

    headers = ["Domain", "Pages", "Links", "Broken", "Redirects", "5xx", "Health %"]
    th = "".join(f"<th>{h}</th>" for h in headers)

    rows_html = []
    max_broken = summary["broken"].max()
    for _, row in summary.iterrows():
        health = row["health_pct"]
        health_color = C_GREEN if health >= 95 else C_AMBER if health >= 85 else C_RED
        broken_bar = _bar_cell(row["broken"], max_broken, C_RED) if max_broken > 0 else f"<td>{_fmt(row['broken'])}</td>"

        rows_html.append(
            f"<tr>"
            f"<td class='url-cell'>{html.escape(str(row['domain']))}</td>"
            f"<td style='white-space:nowrap;'>{_fmt(row['pages_crawled'])}</td>"
            f"<td style='white-space:nowrap;'>{_fmt(row['total_links'])}</td>"
            f"{broken_bar}"
            f"<td style='white-space:nowrap;'>{_fmt(row['redirects'])}</td>"
            f"<td style='white-space:nowrap;'>{_fmt(row['server_errors'])}</td>"
            f"<td style='white-space:nowrap;font-weight:700;color:{health_color};'>{health:.1f}%</td>"
            f"</tr>"
        )

    return (
        f"<table><thead><tr>{th}</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table>"
    )


# ══════════════════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════════════════

def get_extra_css():
    return """
    /* ── Noise texture overlay ──────────────────────────────────── */
    body::before {
        content: '';
        position: fixed;
        inset: 0;
        background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
        opacity: 0.018;
        pointer-events: none;
        z-index: 9999;
    }

    /* ── Executive summary panel ────────────────────────────────── */
    .exec-panel { border: none; padding: 0; margin: 0; background: transparent; }
    .panel-label {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #525252;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .panel-label::after { content: ''; flex: 1; height: 1px; background: #E5E5E5; }
    .exec-bullets { margin: 0; padding: 0; list-style: none; }
    .exec-bullets li {
        font-family: 'Source Serif 4', Georgia, serif;
        font-size: 14px;
        color: #000;
        line-height: 1.7;
        padding: 10px 0 10px 20px;
        border-bottom: 1px solid #E5E5E5;
        position: relative;
    }
    .exec-bullets li::before {
        content: '—';
        position: absolute;
        left: 0;
        color: #525252;
        font-family: 'JetBrains Mono', monospace;
    }
    .exec-bullets li:last-child { border-bottom: none; }

    /* ── Section label ──────────────────────────────────────────── */
    .section-label {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #525252;
        margin-bottom: 8px;
    }

    /* ── Delta spans ────────────────────────────────────────────── */
    .chg {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        font-weight: 600;
        padding: 2px 7px;
        border-radius: 0;
        display: inline-block;
        border: 1px solid #000;
    }
    .chg.pos { background: #000; color: #fff; border-color: #000; }
    .chg.neg { background: #fff; color: #000; border-color: #000; }
    .chg.neu { background: #fff; color: #525252; border-color: #E5E5E5; }

    /* ── Chart wrapper ──────────────────────────────────────────── */
    .chart-wrap { width: 100%; margin-bottom: 24px; }
    .chart-wrap img { width: 100%; display: block; border: 2px solid #000; border-radius: 0; }

    /* ── Two-chart row ──────────────────────────────────────────── */
    .chart-row-2 {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
        margin-bottom: 24px;
    }
    .chart-row-2 img { width: 100%; display: block; border: 2px solid #000; border-radius: 0; }

    /* ── Section header ─────────────────────────────────────────── */
    .col-header {
        font-family: 'Playfair Display', Georgia, serif;
        font-size: 13px;
        font-weight: 700;
        color: #000;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-top: 28px;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 2px solid #000;
    }
    .col-header:first-child { margin-top: 0; }

    /* ── Table ──────────────────────────────────────────────────── */
    table {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 0;
    }
    th {
        font-family: 'JetBrains Mono', monospace;
        font-size: 8px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        padding: 10px 12px;
        text-align: left;
        background: #000;
        color: #fff;
        border: none;
    }
    td {
        padding: 9px 12px;
        border-bottom: 1px solid #E5E5E5;
        overflow-wrap: break-word;
        word-break: normal;
        color: #000;
    }
    td.url-cell {
        max-width: 220px;
        overflow-wrap: break-word;
        word-break: break-word;
        font-family: 'Source Serif 4', Georgia, serif;
        font-size: 11px;
        color: #000;
    }
    tr:hover td { background: #F5F5F5; }
    tr:nth-child(even) td { background: transparent; }
    """


# ══════════════════════════════════════════════════════════════════════════════
# HTML REPORT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _img_tag(path, alt="chart"):
    if not path:
        return ""
    return (
        f'<img src="{html.escape(str(path))}" alt="{html.escape(alt)}" '
        f'style="width:100%;display:block;border:2px solid #000;">'
    )


def _chart_wrap(path, alt="chart"):
    if not path:
        return ""
    return f'<div class="chart-wrap">{_img_tag(path, alt)}</div>'


def _chart_row_2(path_a, alt_a, path_b, alt_b):
    a = _img_tag(path_a, alt_a) if path_a else ""
    b = _img_tag(path_b, alt_b) if path_b else ""
    if not a and not b:
        return ""
    return f'<div class="chart-row-2"><div>{a}</div><div>{b}</div></div>'


def embed_images_as_base64(html_content):
    """Replace local img src= paths with inline base64 data URIs."""
    def replace_src(match):
        src = match.group(1)
        img_path = Path(src)
        if img_path.exists():
            ext  = img_path.suffix.lstrip(".").lower()
            mime = "image/png" if ext == "png" else f"image/{ext}"
            b64  = base64.b64encode(img_path.read_bytes()).decode()
            return f'src="data:{mime};base64,{b64}"'
        return match.group(0)
    return re.sub(r'src="([^"]+\.(png|jpg|jpeg|svg|gif))"', replace_src, html_content)


def _kpi_card(label, curr_val, prev_val=None, lower_better=False):
    """Inverted KPI card (black bg, white text) matching GSC weekly design."""
    curr_str = f"{curr_val:,}" if isinstance(curr_val, int) else str(curr_val)
    if prev_val is not None:
        delta_str = format_pct_change(curr_val, prev_val)
        prev_str  = f"{prev_val:,}" if isinstance(prev_val, int) else str(prev_val)
    else:
        delta_str = "-"
        prev_str  = "—"

    if delta_str == "-":
        delta_html_str = '<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#525252;">—</span>'
    else:
        is_pos = delta_str.startswith("+")
        good   = (is_pos and not lower_better) or (not is_pos and lower_better)
        d_bg, d_color = ("#000", "#fff") if good else ("#fff", "#000")
        delta_html_str = (
            f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:10px;font-weight:700;'
            f'padding:2px 8px;background:{d_bg};color:{d_color};border:1px solid #000;">'
            f'{delta_str}</span>'
        )

    return f"""
<div style="background:#000;color:#fff;padding:24px 20px;border:2px solid #000;position:relative;overflow:hidden;">
  <div style="position:absolute;inset:0;background-image:repeating-linear-gradient(90deg,transparent,transparent 1px,#fff 1px,#fff 2px);background-size:4px 100%;opacity:0.03;pointer-events:none;"></div>
  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.15em;color:#999;margin-bottom:12px;">{html.escape(label)}</div>
  <div style="font-family:'Playfair Display',Georgia,serif;font-size:36px;font-weight:700;color:#fff;line-height:1;margin-bottom:10px;">{html.escape(curr_str)}</div>
  <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#999;margin-bottom:8px;">prev {html.escape(prev_str)}</div>
  {delta_html_str}
</div>"""


def write_html_summary(results_df, kpis, exec_bullets, chart_paths):
    """Build the full HTML report matching the GSC weekly design system."""

    broken_df   = results_df[results_df["issue_type"] == "broken"].copy()
    client_df   = results_df[results_df["issue_type"] == "client_error"].copy()
    server_df   = results_df[results_df["issue_type"] == "server_error"].copy()
    redirect_df = results_df[results_df["issue_type"] == "redirect"].copy()
    error_df    = results_df[results_df["issue_type"] == "error"].copy()

    bullet_items = "".join(f"<li>{html.escape(b)}</li>" for b in exec_bullets)

    kpi_grid = "".join([
        _kpi_card("Source Pages",     kpis["source_pages"]),
        _kpi_card("Broken (404/410)", kpis["broken"],       lower_better=True),
        _kpi_card("4xx Other",        kpis["client_error"], lower_better=True),
        _kpi_card("5xx Errors",       kpis["server_error"], lower_better=True),
        _kpi_card("Redirects",        kpis["redirect"],     lower_better=True),
        _kpi_card("Total Links",      kpis["total_links"]),
    ])

    domain_tbl   = build_domain_summary_table(results_df)
    broken_tbl   = build_issues_table(broken_df)
    client_tbl   = build_issues_table(client_df)
    server_tbl   = build_issues_table(server_df)
    redirect_tbl = build_redirect_table(redirect_df)
    error_tbl    = build_issues_table(error_df)

    today = date.today().strftime("%B %d, %Y")

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Broken Link &amp; Technical Audit — CIM SEO</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,700;0,900;1,400;1,700&family=Source+Serif+4:ital,wght@0,300;0,400;0,600;1,400&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

html {{
    background: #fff;
    background-image: repeating-linear-gradient(0deg,transparent,transparent 1px,#000 1px,#000 2px);
    background-size: 100% 4px;
    background-attachment: fixed;
}}
html::before {{
    content: '';
    position: fixed;
    inset: 0;
    background: rgba(255,255,255,0.97);
    pointer-events: none;
    z-index: 0;
}}
body {{
    font-family: 'Source Serif 4', Georgia, serif;
    font-size: 14px;
    color: #000;
    background: transparent;
    line-height: 1.625;
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 40px 80px;
    position: relative;
    z-index: 1;
}}
.site-header {{
    background: #000;
    color: #fff;
    padding: 40px 48px;
    margin: 0 -40px 0;
    position: relative;
    overflow: hidden;
}}
.site-header::before {{
    content: '';
    position: absolute;
    inset: 0;
    background-image: repeating-linear-gradient(90deg,transparent,transparent 1px,#fff 1px,#fff 2px);
    background-size: 4px 100%;
    opacity: 0.03;
    pointer-events: none;
}}
.site-header__eyebrow {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    color: #999;
    margin-bottom: 12px;
}}
.site-header__title {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: clamp(32px, 5vw, 64px);
    font-weight: 900;
    line-height: 1;
    letter-spacing: -0.02em;
    color: #fff;
    margin-bottom: 16px;
}}
.site-header__meta {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: #666;
    letter-spacing: 0.05em;
    display: flex;
    align-items: center;
    gap: 16px;
}}
.site-header__meta::before {{
    content: '';
    display: inline-block;
    width: 24px;
    height: 2px;
    background: #fff;
    flex-shrink: 0;
}}
.section {{ padding: 40px 0; }}
.section-title {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: #000;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 16px;
}}
.section-title::before {{
    content: '';
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #000;
    flex-shrink: 0;
}}
.kpi-grid {{
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 2px;
    border: 2px solid #000;
}}
.kpi-grid > div {{ border-right: 2px solid #000; }}
.kpi-grid > div:last-child {{ border-right: none; }}
.report-section {{
    background: #fff;
    border: 2px solid #000;
    padding: 28px 32px;
}}
.rule-thick {{ border: none; border-top: 4px solid #000; margin: 0; }}
.rule-thin  {{ border: none; border-top: 1px solid #E5E5E5; margin: 24px 0; }}
{get_extra_css()}
@media (max-width: 768px) {{
    body {{ padding: 0 20px 60px; }}
    .site-header {{ padding: 28px 24px; margin: 0 -20px 0; }}
    .kpi-grid {{ grid-template-columns: repeat(3, 1fr); }}
    .chart-row-2 {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>

<!-- ══ HEADER ══════════════════════════════════════════════════════ -->
<header class="site-header">
  <div class="site-header__eyebrow">CIM SEO — Technical Audit</div>
  <h1 class="site-header__title">Broken Link<br>Check</h1>
  <div class="site-header__meta">
    Generated {today} &nbsp;·&nbsp; {kpis['source_pages']:,} source pages audited &nbsp;·&nbsp; {kpis['total_links']:,} links checked
  </div>
</header>

<hr class="rule-thick">

<!-- ══ EXECUTIVE SUMMARY ══════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Executive Summary</div>
  <div class="exec-panel">
    <ul class="exec-bullets">{bullet_items}</ul>
  </div>
</div>

<hr class="rule-thick">

<!-- ══ KPI CARDS ══════════════════════════════════════════════════ -->
<div class="section" style="padding-top:0;">
  <div class="kpi-grid">{kpi_grid}</div>
</div>

<hr class="rule-thick">

<!-- ══ ISSUE OVERVIEW CHARTS ══════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Issue Overview</div>
  <div class="report-section">
    <div class="col-header">Issue Distribution Across All Links</div>
    {_chart_wrap(chart_paths.get("issue_breakdown"), "Issue distribution")}
    <div class="col-header">Issue Count by Domain</div>
    {_chart_wrap(chart_paths.get("domain_health"), "Domain health")}
  </div>
</div>

<hr class="rule-thick">

<!-- ══ DOMAIN × ISSUE HEATMAP ════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Domain Health Heatmap</div>
  <div class="report-section">
    {_chart_wrap(chart_paths.get("issue_heatmap"), "Domain issue heatmap")}
  </div>
</div>

<hr class="rule-thick">

<!-- ══ STATUS CODES + REDIRECT DEPTH ════════════════════════════ -->
<div class="section">
  <div class="section-title">Status Codes &amp; Redirect Depth</div>
  <div class="report-section">
    <div class="col-header">HTTP Status Code Distribution</div>
    {_chart_wrap(chart_paths.get("status_codes"), "HTTP status code distribution")}
    <div class="col-header">Redirect Chain Depth</div>
    {_chart_wrap(chart_paths.get("redirect_depth"), "Redirect chain depth")}
  </div>
</div>

<hr class="rule-thick">

<!-- ══ TOP BROKEN SOURCES ════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Pages with Most Broken Links</div>
  <div class="report-section">
    {_chart_wrap(chart_paths.get("top_broken_sources"), "Top broken link sources")}
  </div>
</div>

<hr class="rule-thick">

<!-- ══ DOMAIN SUMMARY TABLE ══════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Domain Summary</div>
  <div class="report-section">
    <div class="col-header">Health Score by Domain</div>
    {domain_tbl}
  </div>
</div>

<hr class="rule-thick">

<!-- ══ BROKEN LINKS TABLE ════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Broken Links (404 / 410)</div>
  <div class="report-section">
    {broken_tbl}
  </div>
</div>

<hr class="rule-thick">

<!-- ══ REDIRECT CHAINS TABLE ════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Redirect Chains</div>
  <div class="report-section">
    {redirect_tbl}
  </div>
</div>

<hr class="rule-thick">

<!-- ══ OTHER ISSUES ══════════════════════════════════════════════ -->
<div class="section">
  <div class="section-title">Other Issues</div>
  <div class="report-section">
    <div class="col-header">4xx Client Errors</div>
    {client_tbl}
    <div class="col-header">5xx Server Errors</div>
    {server_tbl}
    <div class="col-header">Request Errors / Timeouts</div>
    {error_tbl}
  </div>
</div>

<hr class="rule-thick">

<!-- ══ FOOTER ════════════════════════════════════════════════════ -->
<footer style="padding:32px 0;display:flex;justify-content:space-between;align-items:center;">
  <span style="font-family:'Playfair Display',Georgia,serif;font-size:13px;font-weight:700;letter-spacing:0.05em;">CIM SEO Intelligence</span>
  <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#525252;text-transform:uppercase;letter-spacing:0.12em;">Generated {today}</span>
</footer>

</body>
</html>"""

    with open("broken_link_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("  Saved broken_link_summary.html", flush=True)


def generate_self_contained():
    """Embed all chart images as base64 and write the final self-contained file."""
    raw   = Path("broken_link_summary.html").read_text(encoding="utf-8")
    final = embed_images_as_base64(raw)
    Path("broken_link_summary_final.html").write_text(final, encoding="utf-8")
    size_kb = len(final.encode()) // 1024
    print(f"  Saved broken_link_summary_final.html ({size_kb} KB, self-contained)", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# MONDAY UPLOAD  (HTML file, matching GSC weekly pattern)
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_monday():
    """Post a text update and attach the self-contained HTML to Monday.com."""
    api_token = MONDAY_API_TOKEN
    item_id   = MONDAY_ITEM_ID

    if not api_token or not item_id:
        print("  Monday upload skipped: MONDAY_API_TOKEN or MONDAY_ITEM_ID not configured.", flush=True)
        return

    body_text = (
        "Broken Link & Technical Audit attached as a self-contained HTML file. "
        "Open in any browser — all charts are embedded inline."
    )

    # Step 1 — create text update
    update_query = """
    mutation ($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) { id }
    }
    """
    resp = requests.post(
        MONDAY_API_URL,
        headers={"Authorization": api_token, "Content-Type": "application/json"},
        json={"query": update_query, "variables": {"item_id": str(item_id), "body": body_text}},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday update creation failed: {data['errors']}")
    update_id = data["data"]["create_update"]["id"]

    # Step 2 — attach self-contained HTML
    file_query = """
    mutation ($update_id: ID!, $file: File!) {
      add_file_to_update(update_id: $update_id, file: $file) { id }
    }
    """
    html_path = Path("broken_link_summary_final.html")
    if not html_path.exists():
        print("  Monday file attach skipped: broken_link_summary_final.html not found.", flush=True)
        return

    with open(html_path, "rb") as f:
        file_resp = requests.post(
            MONDAY_FILE_API_URL,
            headers={"Authorization": api_token},
            data={
                "query": file_query,
                "variables": '{"update_id": "' + str(update_id) + '", "file": null}',
                "map": '{"file": ["variables.file"]}',
            },
            files={"file": ("broken-link-audit.html", f, "text/html")},
            timeout=120,
        )
    file_resp.raise_for_status()
    file_data = file_resp.json()
    if "errors" in file_data:
        raise RuntimeError(f"Monday file attach failed: {file_data['errors']}")
    print("  Uploaded broken-link-audit.html to Monday.com successfully.", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS LOGGING
# ══════════════════════════════════════════════════════════════════════════════

def log_to_google_sheets(kpis):
    """Append a one-row summary to the broken_link_history sheet."""
    row = {
        "date":            [date.today().isoformat()],
        "source_pages":    [kpis["source_pages"]],
        "total_links":     [kpis["total_links"]],
        "broken":          [kpis["broken"]],
        "client_error":    [kpis["client_error"]],
        "server_error":    [kpis["server_error"]],
        "redirect":        [kpis["redirect"]],
        "error":           [kpis["error"]],
        "ok":              [kpis["ok"]],
        "health_pct":      [round(kpis["ok"] / kpis["total_links"] * 100, 2) if kpis["total_links"] else 0],
    }
    try:
        append_to_sheet(pd.DataFrame(row), "broken_link_history")
        print("  Appended to Google Sheets (broken_link_history)", flush=True)
    except Exception as e:
        print(f"  Google Sheets logging failed: {e}", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n╔" + "═" * 58 + "╗")
    print("║" + "  BROKEN LINK & TECHNICAL AUDIT".center(58) + "║")
    print("╚" + "═" * 58 + "╝\n")

    # ── Phase 1: Crawl ────────────────────────────────────────────────────
    print("PHASE 1: CRAWLING")
    print("-" * 60)
    seed_df  = load_seed_domains()
    links_df = crawl_site(seed_df)
    print(f"  ✓ Discovered {len(links_df):,} links across {links_df['source_url'].nunique() if not links_df.empty else 0:,} pages\n")

    # ── Phase 2: Validate ─────────────────────────────────────────────────
    print("PHASE 2: LINK VALIDATION")
    print("-" * 60)
    results_df = evaluate_links(links_df)
    print(f"  ✓ Validated {len(results_df):,} links\n")

    # ── Phase 3: Save CSVs ────────────────────────────────────────────────
    print("PHASE 3: SAVING DATA")
    print("-" * 60)
    links_df.to_csv("discovered_internal_links.csv", index=False)
    results_df.to_csv("broken_link_results.csv", index=False)
    issue_df = results_df[results_df["issue_type"] != "ok"].copy()
    issue_df.to_csv("broken_link_issues_only.csv", index=False)
    print("  ✓ Saved discovered_internal_links.csv")
    print("  ✓ Saved broken_link_results.csv")
    print("  ✓ Saved broken_link_issues_only.csv\n")

    # ── Phase 4: KPIs ─────────────────────────────────────────────────────
    kpis = compute_kpis(results_df)
    print(f"  Broken: {kpis['broken']:,}  |  Redirects: {kpis['redirect']:,}  |  5xx: {kpis['server_error']:,}  |  OK: {kpis['ok']:,}\n")

    # ── Phase 5: Charts ───────────────────────────────────────────────────
    print("PHASE 4: CHART GENERATION")
    print("-" * 60)
    chart_paths = build_all_charts(results_df, kpis)
    print(f"  ✓ Generated {len(chart_paths)} charts\n")

    # ── Phase 6: AI + Bullets ─────────────────────────────────────────────
    print("PHASE 5: AI ANALYSIS")
    print("-" * 60)
    exec_bullets = build_unified_bullets(results_df, kpis)
    print(f"  ✓ {len(exec_bullets)} executive bullets\n")

    # ── Phase 7: HTML Report ──────────────────────────────────────────────
    print("PHASE 6: HTML REPORT")
    print("-" * 60)
    write_html_summary(results_df, kpis, exec_bullets, chart_paths)
    generate_self_contained()
    print()

    # ── Phase 8: Google Sheets ────────────────────────────────────────────
    print("PHASE 7: GOOGLE SHEETS")
    print("-" * 60)
    log_to_google_sheets(kpis)
    print()

    # ── Phase 9: Monday Upload ────────────────────────────────────────────
    print("PHASE 8: MONDAY.COM UPLOAD")
    print("-" * 60)
    try:
        upload_to_monday()
    except Exception as e:
        print(f"  Monday upload failed: {e}", flush=True)
    print()

    print("╔" + "═" * 58 + "╗")
    print("║" + "  AUDIT COMPLETE".center(58) + "║")
    print("╚" + "═" * 58 + "╝\n")


if __name__ == "__main__":
    main()
