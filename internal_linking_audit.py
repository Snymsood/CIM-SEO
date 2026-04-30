from collections import Counter, deque
from datetime import date
from openai import OpenAI
from urllib.parse import urljoin, urlparse, urldefrag
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
import pandas as pd
import requests
import os
import html
import json
import time
import asyncio
import aiohttp

from pdf_report_formatter import html_table_from_df
from html_report_utils import (
    mm_html_shell, mm_kpi_card, mm_kpi_grid, mm_section, mm_report_section,
    mm_col_header, mm_chart_wrap, mm_exec_bullets, mm_ai_block,
    generate_self_contained_html, upload_html_to_monday,
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_ITEM_ID = os.getenv("MONDAY_ITEM_ID")

CONFIG_FILE = "internal_linking_config.csv"
MONDAY_API_URL = "https://api.monday.com/v2"
MONDAY_FILE_API_URL = "https://api.monday.com/v2/file"

REQUEST_TIMEOUT = 30
CRAWL_DELAY_SECONDS = 0.35

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "CIM-SEO-InternalLinkAudit/1.0"
})


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
        return int(float(values[0]))
    except Exception:
        return default_value


def normalize_url(url):
    if not url:
        return None
    url, _ = urldefrag(str(url).strip())
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    return parsed._replace(fragment="").geturl()


def get_allowed_hosts(seed_urls):
    hosts = set()
    for url in seed_urls:
        normalized = normalize_url(url)
        if normalized:
            hosts.add(urlparse(normalized).netloc.lower())
    return hosts


def should_crawl_url(url, allowed_hosts):
    normalized = normalize_url(url)
    if not normalized:
        return False

    parsed = urlparse(normalized)
    if parsed.netloc.lower() not in allowed_hosts:
        return False

    blocked_ext = (
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".zip", ".xml", ".json", ".doc", ".docx", ".xls", ".xlsx",
        ".ppt", ".pptx", ".mp4", ".mp3"
    )
    if parsed.path.lower().endswith(blocked_ext):
        return False

    return True


async def fetch_page_async(session, url):
    async with session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True) as response:
        response.raise_for_status()
        text = await response.text()
        return response.status, text, response.headers


def is_html_response_headers(headers):
    content_type = headers.get("Content-Type", "").lower()
    return "text/html" in content_type


def extract_links_from_html(source_url, html_text, allowed_hosts):
    soup = BeautifulSoup(html_text, "html.parser")
    discovered = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        anchor_text = a.get_text(" ", strip=True)
        target_url = normalize_url(urljoin(source_url, href))

        if not target_url:
            continue

        parsed = urlparse(target_url)
        if parsed.netloc.lower() not in allowed_hosts:
            continue

        discovered.append({
            "source_url": source_url,
            "target_url": target_url,
            "anchor_text": anchor_text[:200],
        })

    return discovered


async def _crawl_internal_links_async(config_df):
    seed_urls = get_config_values(config_df, "seed_url")
    allowed_hosts = get_allowed_hosts(seed_urls)
    max_pages_per_domain = get_config_number(config_df, "max_pages_per_domain", 120)

    queue = deque()
    visited = set()
    host_counts = {host: 0 for host in allowed_hosts}
    links = []

    for seed_url in seed_urls:
        normalized = normalize_url(seed_url)
        if normalized:
            queue.append(normalized)

    semaphore = asyncio.Semaphore(10)
    connector = aiohttp.TCPConnector(limit=15)
    headers = {"User-Agent": "CIM-SEO-InternalLinkAudit/1.0"}

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        while queue:
            # Determine how many pages we can fetch in this batch
            current_batch = []
            while queue and len(current_batch) < 10:
                url = queue.popleft()
                if url in visited:
                    continue
                
                host = urlparse(url).netloc.lower()
                if host_counts.get(host, 0) >= max_pages_per_domain:
                    continue
                
                visited.add(url)
                host_counts[host] = host_counts.get(host, 0) + 1
                current_batch.append(url)

            if not current_batch:
                break

            async def process_url(url):
                async with semaphore:
                    try:
                        status, text, headers = await fetch_page_async(session, url)
                        print(f"Crawled {url} -> {status}", flush=True)
                        if "text/html" in headers.get("Content-Type", "").lower():
                            return url, text
                    except Exception as e:
                        print(f"Failed crawl {url}: {e}", flush=True)
                    return url, None

            tasks = [process_url(url) for url in current_batch]
            results = await asyncio.gather(*tasks)

            for url, text in results:
                if text:
                    extracted = extract_links_from_html(url, text, allowed_hosts)
                    links.extend(extracted)
                    for row in extracted:
                        target = row["target_url"]
                        if should_crawl_url(target, allowed_hosts) and target not in visited:
                            queue.append(target)
            
            # Subtle delay to be respectful
            await asyncio.sleep(0.1)

    links_df = pd.DataFrame(links).drop_duplicates() if links else pd.DataFrame(columns=["source_url", "target_url", "anchor_text"])
    crawled_pages_df = pd.DataFrame({"page": sorted(list(visited))})
    return crawled_pages_df, links_df


def crawl_internal_links(config_df):
    return asyncio.run(_crawl_internal_links_async(config_df))


def analyze_internal_links(crawled_pages_df, links_df, config_df):
    min_internal_outlinks = get_config_number(config_df, "min_internal_outlinks", 3)
    min_inlinks_to_priority_target = get_config_number(config_df, "min_inlinks_to_priority_target", 2)
    generic_anchors = {x.lower().strip() for x in get_config_values(config_df, "generic_anchor")}
    priority_targets = [normalize_url(x) for x in get_config_values(config_df, "priority_target")]
    priority_targets = [x for x in priority_targets if x]

    if links_df.empty:
        page_summary_df = crawled_pages_df.copy()
        page_summary_df["outlinks"] = 0
        page_summary_df["inlinks"] = 0
        page_summary_df["generic_anchor_links"] = 0
    else:
        outlinks_df = links_df.groupby("source_url").size().reset_index(name="outlinks")
        inlinks_df = links_df.groupby("target_url").size().reset_index(name="inlinks")

        generic_anchor_df = links_df.copy()
        generic_anchor_df["is_generic_anchor"] = generic_anchor_df["anchor_text"].str.lower().str.strip().isin(generic_anchors)
        generic_anchor_counts = generic_anchor_df.groupby("source_url")["is_generic_anchor"].sum().reset_index(name="generic_anchor_links")

        page_summary_df = crawled_pages_df.rename(columns={"page": "url"})
        page_summary_df = page_summary_df.merge(outlinks_df, left_on="url", right_on="source_url", how="left")
        page_summary_df = page_summary_df.merge(inlinks_df, left_on="url", right_on="target_url", how="left")
        page_summary_df = page_summary_df.merge(generic_anchor_counts, left_on="url", right_on="source_url", how="left")

        page_summary_df["outlinks"] = page_summary_df["outlinks"].fillna(0).astype(int)
        page_summary_df["inlinks"] = page_summary_df["inlinks"].fillna(0).astype(int)
        page_summary_df["generic_anchor_links"] = page_summary_df["generic_anchor_links"].fillna(0).astype(int)

        page_summary_df = page_summary_df[["url", "outlinks", "inlinks", "generic_anchor_links"]]

    page_summary_df["flag_low_outlinks"] = page_summary_df["outlinks"] < min_internal_outlinks
    page_summary_df["flag_zero_inlinks"] = page_summary_df["inlinks"] == 0
    page_summary_df["flag_generic_anchor_overuse"] = page_summary_df["generic_anchor_links"] > 0

    priority_rows = []
    link_counter = Counter(links_df["target_url"].tolist()) if not links_df.empty else Counter()

    for target in priority_targets:
        priority_rows.append({
            "priority_target": target,
            "inlinks": int(link_counter.get(target, 0)),
            "flag_low_inlinks": int(link_counter.get(target, 0)) < min_inlinks_to_priority_target,
        })

    priority_target_df = pd.DataFrame(priority_rows)

    generic_anchor_examples_df = pd.DataFrame(columns=["source_url", "target_url", "anchor_text"])
    if not links_df.empty:
        generic_anchor_examples_df = links_df[
            links_df["anchor_text"].str.lower().str.strip().isin(generic_anchors)
        ].copy()

    flagged_pages_df = page_summary_df[
        page_summary_df["flag_low_outlinks"] |
        page_summary_df["flag_zero_inlinks"] |
        page_summary_df["flag_generic_anchor_overuse"]
    ].copy()

    return page_summary_df, flagged_pages_df, priority_target_df, generic_anchor_examples_df


def build_link_opportunities(page_summary_df, priority_target_df, config_df):
    priority_targets = priority_target_df["priority_target"].tolist() if not priority_target_df.empty else []
    if not priority_targets:
        return pd.DataFrame(columns=["source_page", "suggested_target", "reason"])

    candidate_sources = page_summary_df.sort_values(by=["outlinks", "inlinks"], ascending=[True, True]).head(15)
    opportunities = []

    for _, row in candidate_sources.iterrows():
        for target in priority_targets[:3]:
            if row["url"] != target:
                opportunities.append({
                    "source_page": row["url"],
                    "suggested_target": target,
                    "reason": "Low-link page could strengthen navigation and authority flow to a priority destination.",
                })

    return pd.DataFrame(opportunities).drop_duplicates().head(20)


def build_executive_commentary(page_summary_df, flagged_pages_df, priority_target_df, generic_anchor_examples_df):
    total_pages = len(page_summary_df)
    low_outlink_count = int(page_summary_df["flag_low_outlinks"].sum()) if not page_summary_df.empty else 0
    zero_inlink_count = int(page_summary_df["flag_zero_inlinks"].sum()) if not page_summary_df.empty else 0
    generic_anchor_count = len(generic_anchor_examples_df)
    weak_priority_count = int(priority_target_df["flag_low_inlinks"].sum()) if not priority_target_df.empty else 0

    lines = [
        f"The audit reviewed internal linking patterns across {total_pages} crawled pages.",
        f"{low_outlink_count} pages were flagged for low internal outlink counts.",
        f"{zero_inlink_count} pages appeared orphan-like within the crawl set, with zero inlinks detected.",
        f"{generic_anchor_count} generic-anchor link instances were identified.",
        f"{weak_priority_count} priority destinations were flagged for weak internal link support.",
    ]
    return lines


def build_executive_analysis(flagged_pages_df, priority_target_df, opportunities_df):
    if not GROQ_API_KEY:
        return (
            "This review highlights internal linking gaps based on low outlink counts, weak support for priority targets, "
            "generic anchor text usage, and orphan-like pages identified within the crawl set."
        )

    flagged_sample = flagged_pages_df.head(10)[["url", "outlinks", "inlinks", "generic_anchor_links"]]
    priority_sample = priority_target_df.head(10)
    opportunity_sample = opportunities_df.head(10)

    prompt = f"""
You are preparing a concise executive internal linking audit summary.

Write:
1. Executive Summary
2. Structural Issues
3. Priority Link Opportunities
4. Recommended Actions

Requirements:
- professional corporate tone
- under 250 words
- no mention of AI or automation
- do not invent data

Flagged pages:
{flagged_sample.to_csv(index=False)}

Priority targets:
{priority_sample.to_csv(index=False)}

Link opportunities:
{opportunity_sample.to_csv(index=False)}
"""

    try:
        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write precise executive SEO internal linking summaries."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content.strip()
        return content if content else "This report summarizes the current internal linking structure and the clearest corrective opportunities."
    except Exception:
        return "This report summarizes the current internal linking structure and the clearest corrective opportunities."


def shorten_url(url):
    cleaned = str(url).replace("https://", "").replace("http://", "")
    return cleaned if len(cleaned) <= 68 else cleaned[:65] + "..."


def create_bar_chart(labels, values, title, xlabel, output_path):
    plt.figure(figsize=(11, 4.6))
    positions = list(range(len(labels)))
    plt.barh(positions, values)
    plt.yticks(positions, labels, fontsize=9)
    plt.xlabel(xlabel)
    plt.title(title, fontsize=14, pad=14)
    plt.gca().invert_yaxis()
    plt.tight_layout()
    plt.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close()


def generate_charts(page_summary_df, priority_target_df):
    if page_summary_df.empty:
        return

    low_outlinks = page_summary_df.sort_values(by="outlinks", ascending=True).head(10)
    create_bar_chart(
        [shorten_url(x) for x in low_outlinks["url"].tolist()],
        low_outlinks["outlinks"].tolist(),
        "Pages With Lowest Internal Outlink Counts",
        "Internal Outlinks",
        "internal_linking_low_outlinks.png",
    )

    lowest_inlinks = page_summary_df.sort_values(by="inlinks", ascending=True).head(10)
    create_bar_chart(
        [shorten_url(x) for x in lowest_inlinks["url"].tolist()],
        lowest_inlinks["inlinks"].tolist(),
        "Pages With Lowest Internal Inlink Counts",
        "Internal Inlinks",
        "internal_linking_low_inlinks.png",
    )

    if not priority_target_df.empty:
        create_bar_chart(
            [shorten_url(x) for x in priority_target_df["priority_target"].tolist()],
            priority_target_df["inlinks"].tolist(),
            "Priority Target Internal Link Support",
            "Inlinks",
            "internal_linking_priority_targets.png",
        )


def build_table_html(df, columns, rename_map=None):
    if df.empty:
        return '<div class="empty-state">No rows to display.</div>'
    return html_table_from_df(df, columns, rename_map)


def write_markdown_summary(commentary_text, page_summary_df, flagged_pages_df, priority_target_df, opportunities_df):
    lines = []
    lines.append("# Internal Linking Audit")
    lines.append("")
    lines.append("## Executive Commentary")
    lines.append("")
    lines.append(commentary_text)
    lines.append("")
    lines.append("## Flagged Pages")
    lines.append("")
    if flagged_pages_df.empty:
        lines.append("No flagged pages.")
    else:
        lines.append(
            flagged_pages_df.head(10)[["url", "outlinks", "inlinks", "generic_anchor_links"]].to_markdown(index=False)
        )
    lines.append("")
    lines.append("## Priority Targets")
    lines.append("")
    if priority_target_df.empty:
        lines.append("No priority targets configured.")
    else:
        lines.append(priority_target_df.to_markdown(index=False))
    lines.append("")
    lines.append("## Link Opportunities")
    lines.append("")
    if opportunities_df.empty:
        lines.append("No link opportunities identified.")
    else:
        lines.append(opportunities_df.head(10).to_markdown(index=False))

    with open("internal_linking_audit_summary.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_html_summary(commentary_text, page_summary_df, flagged_pages_df, priority_target_df, generic_anchor_examples_df, opportunities_df):
    total_pages   = len(page_summary_df)
    low_outlinks  = int(page_summary_df["flag_low_outlinks"].sum()) if not page_summary_df.empty else 0
    orphan_like   = int(page_summary_df["flag_zero_inlinks"].sum()) if not page_summary_df.empty else 0
    weak_targets  = int(priority_target_df["flag_low_inlinks"].sum()) if not priority_target_df.empty else 0

    def tbl(df, cols, rename):
        return html_table_from_df(df, cols, rename) if not df.empty else "<p>No rows to display.</p>"

    kpi_grid = mm_kpi_grid(
        mm_kpi_card("Crawled Pages",         total_pages,  None),
        mm_kpi_card("Low Outlinks",          low_outlinks, None),
        mm_kpi_card("Orphan-Like Pages",     orphan_like,  None),
        mm_kpi_card("Weak Priority Targets", weak_targets, None),
    )

    charts_html = (
        mm_chart_wrap("internal_linking_low_outlinks.png",    "Low outlink pages") +
        mm_chart_wrap("internal_linking_low_inlinks.png",     "Low inlink pages") +
        mm_chart_wrap("internal_linking_priority_targets.png","Priority target support")
    )

    body = (
        mm_section("Executive Commentary",
            mm_report_section(mm_ai_block(commentary_text))
        ) +
        f'<div class="section" style="padding-top:0;">{kpi_grid}</div>'
        '<hr class="rule-thick">' +
        mm_section("Link Coverage Charts",
            mm_report_section(charts_html)
        ) +
        mm_section("Flagged Pages",
            mm_report_section(tbl(flagged_pages_df.head(20),
                ["url","outlinks","inlinks","generic_anchor_links"],
                {"url":"Page","outlinks":"Outlinks","inlinks":"Inlinks","generic_anchor_links":"Generic Anchor Links"}
            ))
        ) +
        mm_section("Priority Target Review",
            mm_report_section(tbl(priority_target_df,
                ["priority_target","inlinks","flag_low_inlinks"],
                {"priority_target":"Priority Target","inlinks":"Inlinks","flag_low_inlinks":"Low Support Flag"}
            ))
        ) +
        mm_section("Generic Anchor Text Examples",
            mm_report_section(tbl(generic_anchor_examples_df.head(20),
                ["source_url","target_url","anchor_text"],
                {"source_url":"Source URL","target_url":"Target URL","anchor_text":"Anchor Text"}
            ))
        ) +
        mm_section("Suggested Link Opportunities",
            mm_report_section(tbl(opportunities_df.head(20),
                ["source_page","suggested_target","reason"],
                {"source_page":"Source Page","suggested_target":"Suggested Target","reason":"Reason"}
            ))
        )
    )

    doc = mm_html_shell(
        title="Internal Linking & Architecture Audit",
        eyebrow="CIM SEO — Technical Audit",
        headline="Internal Linking\nAudit",
        meta_line=f"Generated {date.today().strftime('%B %d, %Y')} · {total_pages} crawled pages",
        body_content=body,
    )
    with open("internal_linking_audit_summary.html", "w", encoding="utf-8") as f:
        f.write(doc)
    print("Saved internal_linking_audit_summary.html", flush=True)


def generate_self_contained():
    generate_self_contained_html("internal_linking_audit_summary.html", "internal_linking_audit_summary_final.html")


def upload_to_monday():
    upload_html_to_monday(
        "internal_linking_audit_summary_final.html",
        "internal-linking-audit.html",
        body_text="Internal Linking Audit attached as self-contained HTML.",
    )


def main():
    config_df = load_config()

    crawled_pages_df, links_df = crawl_internal_links(config_df)
    page_summary_df, flagged_pages_df, priority_target_df, generic_anchor_examples_df = analyze_internal_links(
        crawled_pages_df,
        links_df,
        config_df,
    )
    opportunities_df = build_link_opportunities(page_summary_df, priority_target_df, config_df)
    commentary_text = build_executive_analysis(flagged_pages_df, priority_target_df, opportunities_df)

    crawled_pages_df.to_csv("internal_linking_crawled_pages.csv", index=False)
    links_df.to_csv("internal_linking_discovered_links.csv", index=False)
    page_summary_df.to_csv("internal_linking_page_summary.csv", index=False)
    flagged_pages_df.to_csv("internal_linking_flagged_pages.csv", index=False)
    priority_target_df.to_csv("internal_linking_priority_targets.csv", index=False)
    generic_anchor_examples_df.to_csv("internal_linking_generic_anchor_examples.csv", index=False)
    opportunities_df.to_csv("internal_linking_opportunities.csv", index=False)

    generate_charts(page_summary_df, priority_target_df)
    write_markdown_summary(commentary_text, page_summary_df, flagged_pages_df, priority_target_df, opportunities_df)
    write_html_summary(commentary_text, page_summary_df, flagged_pages_df, priority_target_df, generic_anchor_examples_df, opportunities_df)
    generate_self_contained()

    try:
        upload_to_monday()
    except Exception as e:
        print(f"monday upload step failed: {e}", flush=True)

    print("Saved internal linking outputs.", flush=True)


if __name__ == "__main__":
    main()
