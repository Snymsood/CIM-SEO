from collections import Counter, deque
from datetime import date
from openai import OpenAI
from weasyprint import HTML
from urllib.parse import urljoin, urlparse, urldefrag
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
import pandas as pd
import requests
import os
import html
import json
import time

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


def fetch_page(url):
    response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    return response


def is_html_response(response):
    content_type = response.headers.get("Content-Type", "").lower()
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


def crawl_internal_links(config_df):
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

    while queue:
        current_url = queue.popleft()
        if current_url in visited:
            continue

        host = urlparse(current_url).netloc.lower()
        if host_counts.get(host, 0) >= max_pages_per_domain:
            continue

        try:
            response = fetch_page(current_url)
            print(f"Crawled {current_url} -> {response.status_code}", flush=True)
        except Exception as e:
            print(f"Failed crawl {current_url}: {e}", flush=True)
            visited.add(current_url)
            host_counts[host] = host_counts.get(host, 0) + 1
            continue

        visited.add(current_url)
        host_counts[host] = host_counts.get(host, 0) + 1

        if not is_html_response(response):
            time.sleep(CRAWL_DELAY_SECONDS)
            continue

        extracted = extract_links_from_html(current_url, response.text, allowed_hosts)
        links.extend(extracted)

        for row in extracted:
            target = row["target_url"]
            if should_crawl_url(target, allowed_hosts) and target not in visited:
                queue.append(target)

        time.sleep(CRAWL_DELAY_SECONDS)

    links_df = pd.DataFrame(links).drop_duplicates()
    crawled_pages_df = pd.DataFrame({"page": sorted(list(visited))})
    return crawled_pages_df, links_df


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

    work = df[columns].copy()
    if rename_map:
        work = work.rename(columns=rename_map)

    for col in work.columns:
        lower = col.lower()
        if any(token in lower for token in ["outlink", "inlink", "count"]):
            work[col] = pd.to_numeric(work[col], errors="coerce").map(
                lambda x: f"{x:.0f}" if pd.notnull(x) else ""
            )
        else:
            work[col] = work[col].fillna("").astype(str)

    header_html = "".join(f"<th>{html.escape(str(col))}</th>" for col in work.columns)
    body_rows = []
    for row in work.values.tolist():
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in row)
        body_rows.append(f"<tr>{cells}</tr>")

    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


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
    commentary_lines = [line.strip() for line in commentary_text.splitlines() if line.strip()]

    total_pages = len(page_summary_df)
    low_outlinks = int(page_summary_df["flag_low_outlinks"].sum()) if not page_summary_df.empty else 0
    orphan_like = int(page_summary_df["flag_zero_inlinks"].sum()) if not page_summary_df.empty else 0
    weak_targets = int(priority_target_df["flag_low_inlinks"].sum()) if not priority_target_df.empty else 0

    def card(title, value, sub):
        return f"""
        <div class="card">
            <div class="label">{html.escape(title)}</div>
            <div class="value">{html.escape(str(value))}</div>
            <div class="sub">{html.escape(sub)}</div>
        </div>
        """

    flagged_table = build_table_html(
        flagged_pages_df.head(20),
        ["url", "outlinks", "inlinks", "generic_anchor_links"],
        {
            "url": "Page",
            "outlinks": "Outlinks",
            "inlinks": "Inlinks",
            "generic_anchor_links": "Generic Anchor Links",
        }
    )

    priority_table = build_table_html(
        priority_target_df,
        ["priority_target", "inlinks", "flag_low_inlinks"],
        {
            "priority_target": "Priority Target",
            "inlinks": "Inlinks",
            "flag_low_inlinks": "Low Support Flag",
        }
    )

    generic_anchor_table = build_table_html(
        generic_anchor_examples_df.head(20),
        ["source_url", "target_url", "anchor_text"],
        {
            "source_url": "Source URL",
            "target_url": "Target URL",
            "anchor_text": "Anchor Text",
        }
    )

    opportunity_table = build_table_html(
        opportunities_df.head(20),
        ["source_page", "suggested_target", "reason"],
        {
            "source_page": "Source Page",
            "suggested_target": "Suggested Target",
            "reason": "Reason",
        }
    )

    html_output = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Internal Linking Audit</title>
<style>
    @page {{
        size: A4;
        margin: 0.55in;
    }}
    body {{
        font-family: "Times New Roman", Times, serif;
        margin: 0;
        padding: 0;
        background: #f4f6fb;
        color: #1f2937;
        line-height: 1.45;
    }}
    .container {{
        max-width: 1180px;
        margin: 0 auto;
        padding: 26px 24px 40px 24px;
    }}
    .hero {{
        background: linear-gradient(135deg, #153e75 0%, #1e5aa8 55%, #5b8bd9 100%);
        color: white;
        border-radius: 20px;
        padding: 34px 34px 28px 34px;
        margin-bottom: 28px;
        box-shadow: 0 10px 28px rgba(21, 62, 117, 0.22);
    }}
    .hero-title {{
        font-size: 30px;
        margin: 0 0 10px 0;
        font-weight: 700;
    }}
    .hero-subtitle {{
        font-size: 15px;
        margin: 0;
        opacity: 0.95;
    }}
    .section {{
        background: white;
        border-radius: 18px;
        padding: 24px 24px 22px 24px;
        margin-bottom: 24px;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.07);
    }}
    h2 {{
        margin: 0 0 14px 0;
        font-size: 22px;
        color: #153e75;
        border-bottom: 2px solid #dbe7fb;
        padding-bottom: 10px;
    }}
    .commentary-box {{
        background: linear-gradient(180deg, #f8fbff 0%, #edf4ff 100%);
        border-left: 6px solid #1e5aa8;
        border-radius: 16px;
        padding: 20px 22px;
        margin-top: 8px;
    }}
    .commentary-box p {{
        margin: 0 0 12px 0;
        font-size: 16px;
    }}
    .grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 18px;
        margin-top: 6px;
    }}
    .card {{
        background: linear-gradient(180deg, #ffffff 0%, #f6f9ff 100%);
        border: 1px solid #d7e3f8;
        border-radius: 16px;
        padding: 20px 18px;
        min-height: 118px;
    }}
    .label {{
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #58749e;
        margin-bottom: 12px;
        font-weight: 700;
    }}
    .value {{
        font-size: 30px;
        color: #153e75;
        font-weight: 700;
        margin-bottom: 10px;
    }}
    .sub {{
        font-size: 14px;
        color: #5b6474;
    }}
    .chart-block {{
        background: #ffffff;
        border: 1px solid #deebff;
        border-radius: 16px;
        padding: 18px;
        margin-top: 18px;
    }}
    .chart-block img {{
        width: 100%;
        height: auto;
        display: block;
        border-radius: 12px;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        background: white;
        margin-top: 10px;
        border-radius: 14px;
        overflow: hidden;
    }}
    th, td {{
        text-align: left;
        padding: 14px 16px;
        border-bottom: 1px solid #e6edf8;
        vertical-align: top;
        word-break: break-word;
    }}
    th {{
        background: #214f8f;
        color: white;
        font-size: 13px;
        letter-spacing: 0.02em;
    }}
    tr:nth-child(even) td {{
        background: #f8fbff;
    }}
    .empty-state {{
        color: #6b7280;
        font-style: italic;
        padding: 8px 0 2px 0;
    }}
</style>
</head>
<body>
<div class="container">
    <div class="hero">
        <div class="hero-title">Internal Linking Audit</div>
        <div class="hero-subtitle">Weekly review of internal navigation structure, link support, and link opportunity coverage.</div>
    </div>

    <div class="section">
        <h2>Executive Commentary</h2>
        <div class="commentary-box">
            {''.join(f'<p>{html.escape(line)}</p>' for line in commentary_lines)}
        </div>
    </div>

    <div class="section">
        <h2>Linking Snapshot</h2>
        <div class="grid">
            {card("Crawled Pages", total_pages, "HTML pages reviewed")}
            {card("Low Outlinks", low_outlinks, "pages below outlink threshold")}
            {card("Orphan-Like Pages", orphan_like, "pages with zero detected inlinks")}
            {card("Weak Priority Targets", weak_targets, "priority destinations with low support")}
        </div>
    </div>

    <div class="section">
        <h2>Low Outlink Coverage</h2>
        <div class="chart-block">
            <img src="internal_linking_low_outlinks.png" alt="Low outlink pages">
        </div>
    </div>

    <div class="section">
        <h2>Low Inlink Coverage</h2>
        <div class="chart-block">
            <img src="internal_linking_low_inlinks.png" alt="Low inlink pages">
        </div>
    </div>

    <div class="section">
        <h2>Priority Target Support</h2>
        <div class="chart-block">
            <img src="internal_linking_priority_targets.png" alt="Priority target support">
        </div>
    </div>

    <div class="section">
        <h2>Flagged Pages</h2>
        {flagged_table}
    </div>

    <div class="section">
        <h2>Priority Target Review</h2>
        {priority_table}
    </div>

    <div class="section">
        <h2>Generic Anchor Text Examples</h2>
        {generic_anchor_table}
    </div>

    <div class="section">
        <h2>Suggested Link Opportunities</h2>
        {opportunity_table}
    </div>
</div>
</body>
</html>
"""
    with open("internal_linking_audit_summary.html", "w", encoding="utf-8") as f:
        f.write(html_output)


def generate_pdf():
    HTML("internal_linking_audit_summary.html").write_pdf("internal_linking_audit_summary.pdf")
    print("Saved internal_linking_audit_summary.pdf", flush=True)


def upload_pdf_to_monday(pdf_path):
    if not MONDAY_API_TOKEN or not MONDAY_ITEM_ID:
        print("Skipping monday file upload: MONDAY_API_TOKEN or MONDAY_ITEM_ID not configured.", flush=True)
        return

    update_query = """
    mutation ($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) {
        id
      }
    }
    """
    update_variables = {
        "item_id": str(MONDAY_ITEM_ID),
        "body": "Internal linking PDF report attached.",
    }

    update_response = requests.post(
        MONDAY_API_URL,
        headers={"Authorization": MONDAY_API_TOKEN, "Content-Type": "application/json"},
        json={"query": update_query, "variables": update_variables},
        timeout=60,
    )
    update_response.raise_for_status()
    update_id = update_response.json()["data"]["create_update"]["id"]

    file_query = """
    mutation ($update_id: ID!, $file: File!) {
      add_file_to_update(update_id: $update_id, file: $file) {
        id
      }
    }
    """

    with open(pdf_path, "rb") as f:
        response = requests.post(
            MONDAY_FILE_API_URL,
            headers={"Authorization": MONDAY_API_TOKEN},
            data={
                "query": file_query,
                "variables": json.dumps({"update_id": str(update_id), "file": None}),
                "map": json.dumps({"pdf": ["variables.file"]}),
            },
            files={"pdf": ("internal-linking-audit.pdf", f, "application/pdf")},
            timeout=120,
        )

    print("monday file upload status:", response.status_code, flush=True)
    print("monday file upload response:", response.text, flush=True)
    response.raise_for_status()
    print("Uploaded PDF to monday update.", flush=True)


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
    generate_pdf()

    try:
        upload_pdf_to_monday("internal_linking_audit_summary.pdf")
    except Exception as e:
        print(f"monday upload step failed: {e}", flush=True)

    print("Saved internal linking outputs.", flush=True)


if __name__ == "__main__":
    main()
