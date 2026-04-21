from collections import deque
from datetime import date
from openai import OpenAI
from weasyprint import HTML
from urllib.parse import urljoin, urlparse, urldefrag
from bs4 import BeautifulSoup
import pandas as pd
import requests
import os
import html
import json
import time

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


def check_link_status(url):
    try:
        response = SESSION.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        status_code = response.status_code

        if status_code == 405 or status_code >= 500:
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
            status_code = response.status_code

        final_url = response.url
        redirect_count = len(response.history)
        return {
            "status_code": status_code,
            "final_url": final_url,
            "redirect_count": redirect_count,
            "error": None,
        }
    except Exception as e:
        return {
            "status_code": None,
            "final_url": None,
            "redirect_count": None,
            "error": str(e),
        }


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


def evaluate_links(links_df):
    if links_df.empty:
        return pd.DataFrame(columns=[
            "source_url", "target_url", "anchor_text", "status_code",
            "final_url", "redirect_count", "error", "issue_type"
        ])

    status_rows = []
    unique_targets = links_df["target_url"].dropna().unique().tolist()

    for target in unique_targets:
        result = check_link_status(target)
        issue_type = classify_status(
            result["status_code"],
            result["error"],
            result["redirect_count"]
        )
        status_rows.append({
            "target_url": target,
            "status_code": result["status_code"],
            "final_url": result["final_url"],
            "redirect_count": result["redirect_count"],
            "error": result["error"],
            "issue_type": issue_type,
        })
        print(f"Checked {target} -> {issue_type}", flush=True)
        time.sleep(0.1)

    status_df = pd.DataFrame(status_rows)
    merged = pd.merge(links_df, status_df, on="target_url", how="left")
    return merged


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


def html_table_from_df(df, columns, rename_map=None):
    work = df[columns].copy()
    if rename_map:
        work = work.rename(columns=rename_map)

    for col in work.columns:
        work[col] = work[col].fillna("").astype(str)

    header_html = "".join(f"<th>{html.escape(str(col))}</th>" for col in work.columns)
    body_rows = []
    for row in work.values.tolist():
        cells = "".join(f"<td>{html.escape(str(v))}</td>" for v in row)
        body_rows.append(f"<tr>{cells}</tr>")

    return f"<table><thead><tr>{header_html}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def write_html_summary(results_df, ai_analysis):
    issues_df = results_df[results_df["issue_type"] != "ok"].copy()
    broken_df = results_df[results_df["issue_type"] == "broken"].copy().head(50)
    client_df = results_df[results_df["issue_type"] == "client_error"].copy().head(50)
    server_df = results_df[results_df["issue_type"] == "server_error"].copy().head(50)
    redirect_df = results_df[results_df["issue_type"] == "redirect"].copy().head(50)
    error_df = results_df[results_df["issue_type"] == "error"].copy().head(50)

    executive_read = build_executive_read(results_df)

    def card(title, value, sub):
        return f"""
        <div class="card">
            <div class="label">{html.escape(title)}</div>
            <div class="value">{html.escape(str(value))}</div>
            <div class="sub">{html.escape(sub)}</div>
        </div>
        """

    html_output = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Broken Link Check</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 0; padding: 32px; background: #f5f7fb; color: #1f2937; }}
.container {{ max-width: 1200px; margin: 0 auto; }}
h2 {{ margin-top: 32px; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
.grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:16px; margin:20px 0 28px 0; }}
.card, .panel {{ background:white; border-radius:12px; padding:18px; box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
.panel {{ margin-bottom:20px; }}
.label {{ font-size:12px; text-transform:uppercase; color:#6b7280; margin-bottom:10px; }}
.value {{ font-size:28px; font-weight:700; margin-bottom:6px; }}
.sub {{ font-size:13px; color:#6b7280; }}
table {{ width:100%; border-collapse:collapse; background:white; border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08); margin-bottom:24px; }}
th, td {{ text-align:left; padding:12px 14px; border-bottom:1px solid #e5e7eb; vertical-align:top; word-break:break-word; }}
th {{ background:#111827; color:white; font-size:13px; }}
tr:nth-child(even) td {{ background:#f9fafb; }}
.ai-block {{ white-space:pre-wrap; line-height:1.5; }}
</style>
</head>
<body>
<div class="container">
<h1>Broken Link Check</h1>

<div class="panel">
<h2>Executive Read</h2>
<ul>{''.join(f"<li>{html.escape(line)}</li>" for line in executive_read)}</ul>
</div>

<div class="panel">
<h2>AI Executive Analysis</h2>
<div class="ai-block">{html.escape(ai_analysis)}</div>
</div>

<div class="grid">
{card("Source Pages", results_df["source_url"].nunique(), "pages crawled with internal links")}
{card("Broken", (results_df["issue_type"] == "broken").sum(), "404/410 links")}
{card("4xx Other", (results_df["issue_type"] == "client_error").sum(), "other client errors")}
{card("5xx", (results_df["issue_type"] == "server_error").sum(), "server errors")}
{card("Redirects", (results_df["issue_type"] == "redirect").sum(), "internal redirects")}
</div>

<h2>Broken Links</h2>
{html_table_from_df(
    broken_df,
    ["source_url", "target_url", "anchor_text", "status_code", "issue_type"],
    {
        "source_url": "Source URL",
        "target_url": "Broken Target",
        "anchor_text": "Anchor Text",
        "status_code": "Status",
        "issue_type": "Issue Type",
    }
)}

<h2>Other 4xx Links</h2>
{html_table_from_df(
    client_df,
    ["source_url", "target_url", "anchor_text", "status_code", "issue_type"],
    {
        "source_url": "Source URL",
        "target_url": "Target URL",
        "anchor_text": "Anchor Text",
        "status_code": "Status",
        "issue_type": "Issue Type",
    }
)}

<h2>5xx Links</h2>
{html_table_from_df(
    server_df,
    ["source_url", "target_url", "anchor_text", "status_code", "issue_type"],
    {
        "source_url": "Source URL",
        "target_url": "Target URL",
        "anchor_text": "Anchor Text",
        "status_code": "Status",
        "issue_type": "Issue Type",
    }
)}

<h2>Redirected Internal Links</h2>
{html_table_from_df(
    redirect_df,
    ["source_url", "target_url", "final_url", "redirect_count", "status_code"],
    {
        "source_url": "Source URL",
        "target_url": "Original Target",
        "final_url": "Final URL",
        "redirect_count": "Redirects",
        "status_code": "Final Status",
    }
)}

<h2>Request Errors</h2>
{html_table_from_df(
    error_df,
    ["source_url", "target_url", "error", "issue_type"],
    {
        "source_url": "Source URL",
        "target_url": "Target URL",
        "error": "Error",
        "issue_type": "Issue Type",
    }
)}
</div>
</body>
</html>
"""
    with open("broken_link_summary.html", "w", encoding="utf-8") as f:
        f.write(html_output)


def generate_pdf():
    HTML("broken_link_summary.html").write_pdf("broken_link_summary.pdf")
    print("Saved broken_link_summary.pdf", flush=True)


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
        "body": "Broken link PDF report attached.",
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
            files={"pdf": ("broken-link-check.pdf", f, "application/pdf")},
            timeout=120,
        )

    print("monday file upload status:", response.status_code, flush=True)
    print("monday file upload response:", response.text, flush=True)
    response.raise_for_status()
    print("Uploaded PDF to monday update.", flush=True)


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
    generate_pdf()

    try:
        upload_pdf_to_monday("broken_link_summary.pdf")
    except Exception as e:
        print(f"monday upload step failed: {e}", flush=True)

    print("Saved broken link outputs.", flush=True)


if __name__ == "__main__":
    main()
