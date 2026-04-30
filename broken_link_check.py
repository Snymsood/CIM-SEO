from collections import deque
from datetime import date
from openai import OpenAI
from urllib.parse import urljoin, urlparse, urldefrag
from bs4 import BeautifulSoup
import asyncio
import aiohttp
import pandas as pd
import requests
import os
import html
import json
import time

from pdf_report_formatter import html_table_from_df
from html_report_utils import (
    mm_html_shell, mm_kpi_card, mm_kpi_grid, mm_section, mm_report_section,
    mm_col_header, mm_exec_bullets, mm_ai_block,
    generate_self_contained_html, upload_html_to_monday,
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")

SEED_FILE = "broken_link_seed_domains.csv"
MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"

MAX_PAGES_PER_DOMAIN = 150
REQUEST_TIMEOUT = 30
CRAWL_DELAY_SECONDS = 0.5

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CIM-SEO-LinkChecker/1.0"
})


def load_seed_domains():
    df = pd.read_csv(SEED_FILE)
    df["seed_url"] = df["seed_url"].astype(str).str.strip()
    df["scope_type"] = df["scope_type"].astype(str).str.strip()
    df["priority"] = df["priority"].astype(str).str.strip()
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

    normalized = parsed._replace(fragment="")
    return normalized.geturl()


def is_html_response(response):
    content_type = response.headers.get("Content-Type", "").lower()
    return "text/html" in content_type


def should_crawl_url(url, allowed_hosts):
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    host = parsed.netloc.lower()
    if host not in allowed_hosts:
        return False

    blocked_ext = (
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".zip", ".xml", ".json", ".doc", ".docx", ".xls", ".xlsx",
        ".ppt", ".pptx", ".mp4", ".mp3"
    )
    lower_path = parsed.path.lower()
    if lower_path.endswith(blocked_ext):
        return False

    return True


def fetch_page(url):
    response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    return response


def extract_links_from_html(base_url, html_text, allowed_hosts):
    soup = BeautifulSoup(html_text, "html.parser")
    links = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        anchor_text = a.get_text(" ", strip=True)

        if not href:
            continue

        absolute = urljoin(base_url, href)
        normalized = normalize_url(absolute)

        if not normalized:
            continue

        parsed = urlparse(normalized)
        if parsed.netloc.lower() not in allowed_hosts:
            continue

        links.append({
            "source_url": base_url,
            "target_url": normalized,
            "anchor_text": anchor_text[:200],
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
    allowed_hosts = get_allowed_hosts(seed_df)

    visited_pages = set()
    discovered_links = []
    queue = deque()

    host_page_counts = {host: 0 for host in allowed_hosts}

    for seed_url in seed_df["seed_url"].tolist():
        normalized = normalize_url(seed_url)
        if normalized:
            queue.append(normalized)

    while queue:
        current_url = queue.popleft()
        if current_url in visited_pages:
            continue

        parsed = urlparse(current_url)
        host = parsed.netloc.lower()

        if host_page_counts.get(host, 0) >= MAX_PAGES_PER_DOMAIN:
            continue

        try:
            response = fetch_page(current_url)
            print(f"Crawled {current_url} -> {response.status_code}", flush=True)
        except Exception as e:
            print(f"Failed crawl {current_url}: {e}", flush=True)
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

    return pd.DataFrame(discovered_links).drop_duplicates()


async def _check_one_link(session, semaphore, url):
    """Check a single URL asynchronously, falling back from HEAD to GET on 405/5xx."""
    async with semaphore:
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with session.head(url, timeout=timeout, allow_redirects=True) as resp:
                status_code = resp.status
                final_url = str(resp.url)
                redirect_count = len(resp.history)

            # Some servers reject HEAD — retry with GET
            if status_code == 405 or status_code >= 500:
                async with session.get(url, timeout=timeout, allow_redirects=True) as resp2:
                    status_code = resp2.status
                    final_url = str(resp2.url)
                    redirect_count = len(resp2.history)

            return {
                "target_url": url,
                "status_code": status_code,
                "final_url": final_url,
                "redirect_count": redirect_count,
                "error": None,
            }
        except Exception as exc:
            return {
                "target_url": url,
                "status_code": None,
                "final_url": None,
                "redirect_count": None,
                "error": str(exc),
            }


async def _evaluate_links_async(links_df):
    """Evaluate all unique link targets concurrently (max 15 in-flight at once)."""
    if links_df.empty:
        return pd.DataFrame(columns=[
            "source_url", "target_url", "anchor_text", "status_code",
            "final_url", "redirect_count", "error", "issue_type",
        ])

    unique_targets = links_df["target_url"].dropna().unique().tolist()
    semaphore = asyncio.Semaphore(15)
    connector = aiohttp.TCPConnector(limit=20)
    headers = {"User-Agent": "CIM-SEO-LinkChecker/1.0"}

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        tasks = [_check_one_link(session, semaphore, url) for url in unique_targets]
        raw_results = await asyncio.gather(*tasks)

    status_rows = []
    for result in raw_results:
        issue_type = classify_status(
            result["status_code"], result["error"], result["redirect_count"]
        )
        result["issue_type"] = issue_type
        status_rows.append(result)
        print(f"Checked {result['target_url']} -> {issue_type}", flush=True)

    status_df = pd.DataFrame(status_rows)
    return pd.merge(links_df, status_df, on="target_url", how="left")


def evaluate_links(links_df):
    """Synchronous entry point — runs async evaluation via asyncio.run()."""
    return asyncio.run(_evaluate_links_async(links_df))


def build_executive_read(results_df):
    if results_df.empty:
        return ["No internal links were collected during this crawl."]

    broken_count = (results_df["issue_type"] == "broken").sum()
    client_error_count = (results_df["issue_type"] == "client_error").sum()
    server_error_count = (results_df["issue_type"] == "server_error").sum()
    redirect_count = (results_df["issue_type"] == "redirect").sum()
    error_count = (results_df["issue_type"] == "error").sum()
    unique_sources = results_df["source_url"].nunique()

    lines = [
        f"The crawler checked internal links across {unique_sources} source pages.",
        f"{broken_count} broken links returned 404 or 410.",
        f"{client_error_count} additional client-error links returned other 4xx responses.",
        f"{server_error_count} links returned 5xx server errors.",
        f"{redirect_count} internal links resolved through redirects.",
    ]

    if error_count > 0:
        lines.append(f"{error_count} links failed due to timeout or request errors.")

    return lines


def build_ai_analysis(results_df):
    if not GROQ_API_KEY:
        return "AI executive analysis was skipped because GROQ_API_KEY is not configured."

    issue_df = results_df[results_df["issue_type"] != "ok"].copy()
    if issue_df.empty:
        return "No broken, redirected, or errored internal links were found in this run."

    top_issues = issue_df[[
        "source_url", "target_url", "status_code", "issue_type", "redirect_count"
    ]].head(20)

    prompt = f"""
You are writing a concise broken-link monitoring summary for SEO stakeholders.

Write:
1. Executive Summary
2. Key Technical Risks
3. Priority Fix Areas
4. Recommended Actions

Requirements:
- professional corporate tone
- under 300 words
- do not invent data
- focus on internal link integrity and crawl hygiene

Issue sample:
{top_issues.to_csv(index=False)}
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




def write_html_summary(results_df, ai_analysis):
    issues_df  = results_df[results_df["issue_type"] != "ok"].copy()
    broken_df  = results_df[results_df["issue_type"] == "broken"].copy().head(50)
    client_df  = results_df[results_df["issue_type"] == "client_error"].copy().head(50)
    server_df  = results_df[results_df["issue_type"] == "server_error"].copy().head(50)
    redirect_df= results_df[results_df["issue_type"] == "redirect"].copy().head(50)
    error_df   = results_df[results_df["issue_type"] == "error"].copy().head(50)

    executive_read  = build_executive_read(results_df)
    broken_count    = int((results_df["issue_type"] == "broken").sum())
    client_error_count = int((results_df["issue_type"] == "client_error").sum())
    server_error_count = int((results_df["issue_type"] == "server_error").sum())
    redirect_count  = int((results_df["issue_type"] == "redirect").sum())
    source_count    = int(results_df["source_url"].nunique())

    def tbl(df, cols, rename):
        return html_table_from_df(df, cols, rename) if not df.empty else "<p>No issues found.</p>"

    kpi_grid = mm_kpi_grid(
        mm_kpi_card("Source Pages",    source_count,       None),
        mm_kpi_card("Broken (404/410)",broken_count,       None),
        mm_kpi_card("4xx Other",       client_error_count, None),
        mm_kpi_card("5xx Errors",      server_error_count, None),
    )

    body = (
        mm_section("Executive Summary",
            mm_report_section(mm_exec_bullets(executive_read) + mm_ai_block(ai_analysis))
        ) +
        f'<div class="section" style="padding-top:0;">{kpi_grid}</div>'
        '<hr class="rule-thick">' +
        mm_section("Broken Links (404 / 410)",
            mm_report_section(tbl(broken_df,
                ["source_url","target_url","anchor_text","status_code","issue_type"],
                {"source_url":"Source URL","target_url":"Broken Target","anchor_text":"Anchor Text","status_code":"Status","issue_type":"Issue Type"}
            ))
        ) +
        mm_section("Other 4xx Links",
            mm_report_section(tbl(client_df,
                ["source_url","target_url","anchor_text","status_code","issue_type"],
                {"source_url":"Source URL","target_url":"Target URL","anchor_text":"Anchor Text","status_code":"Status","issue_type":"Issue Type"}
            ))
        ) +
        mm_section("5xx Server Errors",
            mm_report_section(tbl(server_df,
                ["source_url","target_url","anchor_text","status_code","issue_type"],
                {"source_url":"Source URL","target_url":"Target URL","anchor_text":"Anchor Text","status_code":"Status","issue_type":"Issue Type"}
            ))
        ) +
        mm_section("Redirected Internal Links",
            mm_report_section(tbl(redirect_df,
                ["source_url","target_url","final_url","redirect_count","status_code"],
                {"source_url":"Source URL","target_url":"Original Target","final_url":"Final URL","redirect_count":"Redirects","status_code":"Final Status"}
            ))
        ) +
        mm_section("Request Errors",
            mm_report_section(tbl(error_df,
                ["source_url","target_url","error","issue_type"],
                {"source_url":"Source URL","target_url":"Target URL","error":"Error","issue_type":"Issue Type"}
            ))
        )
    )

    doc = mm_html_shell(
        title="Broken Link & Technical Audit",
        eyebrow="CIM SEO — Technical Audit",
        headline="Broken Link\nCheck",
        meta_line=f"Generated {date.today().strftime('%B %d, %Y')} · {source_count} source URLs audited",
        body_content=body,
    )
    with open("broken_link_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("Saved broken_link_summary.html", flush=True)


def generate_self_contained():
    generate_self_contained_html("broken_link_summary.html", "broken_link_summary_final.html")


def upload_to_monday():
    upload_html_to_monday(
        "broken_link_summary_final.html",
        "broken-link-check.html",
        body_text="Broken Link Audit attached as self-contained HTML.",
    )


def main():
    seed_df = load_seed_domains()
    links_df = crawl_site(seed_df)
    results_df = evaluate_links(links_df)

    links_df.to_csv("discovered_internal_links.csv", index=False)
    results_df.to_csv("broken_link_results.csv", index=False)

    issue_df = results_df[results_df["issue_type"] != "ok"].copy()
    issue_df.to_csv("broken_link_issues_only.csv", index=False)

    ai_analysis = build_ai_analysis(results_df)
    write_html_summary(results_df, ai_analysis)
    generate_self_contained()

    try:
        upload_to_monday()
    except Exception as e:
        print(f"monday upload step failed: {e}", flush=True)

    print("Saved broken link outputs.", flush=True)


if __name__ == "__main__":
    main()
