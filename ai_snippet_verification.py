import os
import re
import json
import time
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


TARGETS_FILE = "ai_snippet_targets.csv"

REPORT_DIR = Path("reports")
SCREENSHOT_DIR = Path("screenshots")
EVIDENCE_DIR = Path("evidence")

REPORT_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR.mkdir(exist_ok=True)
EVIDENCE_DIR.mkdir(exist_ok=True)


def slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")[:80]


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "")
    return text.strip()


def extract_page_signals(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    title = clean_text(soup.title.get_text()) if soup.title else ""

    meta_description = ""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        meta_description = clean_text(meta["content"])

    h1s = [clean_text(h.get_text()) for h in soup.find_all("h1")]
    h2s = [clean_text(h.get_text()) for h in soup.find_all("h2")]

    links = []
    for a in soup.find_all("a"):
        label = clean_text(a.get_text())
        href = a.get("href", "")
        if label and href:
            links.append({"label": label, "href": href})

    buttons = []
    for button in soup.find_all(["button"]):
        label = clean_text(button.get_text())
        if label:
            buttons.append(label)

    visible_text = clean_text(soup.get_text(" "))

    return {
        "title": title,
        "meta_description": meta_description,
        "h1s": h1s[:10],
        "h2s": h2s[:20],
        "links": links[:100],
        "buttons": buttons[:50],
        "visible_text_sample": visible_text[:8000],
        "visible_text_length": len(visible_text),
    }


def score_accessibility(signals: dict) -> tuple[int, str]:
    text_length = signals.get("visible_text_length", 0)
    h1_count = len(signals.get("h1s", []))
    link_count = len(signals.get("links", []))

    if text_length >= 2500 and h1_count >= 1 and link_count >= 5:
        return 5, "Page appears highly readable to automated extraction."
    if text_length >= 1500 and link_count >= 3:
        return 4, "Page appears mostly readable."
    if text_length >= 750:
        return 3, "Page is partially readable; important content may be hidden or dynamic."
    if text_length >= 250:
        return 2, "Page has limited readable content."
    if text_length > 0:
        return 1, "Page has very little readable content."
    return 0, "Could not extract readable page content."


def score_summary_readiness(signals: dict) -> tuple[int, str]:
    title = signals.get("title", "")
    meta = signals.get("meta_description", "")
    h1s = signals.get("h1s", [])
    h2s = signals.get("h2s", [])
    text_length = signals.get("visible_text_length", 0)

    score = 0

    if title:
        score += 1
    if meta:
        score += 1
    if h1s:
        score += 1
    if len(h2s) >= 2:
        score += 1
    if text_length >= 1500:
        score += 1

    if score >= 5:
        note = "Strong summary readiness."
    elif score >= 4:
        note = "Good summary readiness."
    elif score >= 3:
        note = "Moderate summary readiness."
    elif score >= 2:
        note = "Weak summary readiness."
    else:
        note = "Poor summary readiness."

    return score, note


def score_cta_accuracy(signals: dict, expected_ctas: str) -> tuple[int, str, list]:
    expected = [
        clean_text(item).lower()
        for item in str(expected_ctas).split(";")
        if clean_text(item)
    ]

    cta_text_sources = []

    for link in signals.get("links", []):
        cta_text_sources.append(link.get("label", ""))

    for button in signals.get("buttons", []):
        cta_text_sources.append(button)

    combined = " ".join(cta_text_sources).lower()

    matched = []
    for cta in expected:
        if cta and cta in combined:
            matched.append(cta)

    if not expected:
        return 3, "No expected CTAs provided for this row.", matched

    ratio = len(matched) / len(expected)

    if ratio == 1:
        return 5, "All expected CTAs were visible in extracted page actions.", matched
    if ratio >= 0.66:
        return 4, "Most expected CTAs were visible.", matched
    if ratio >= 0.33:
        return 3, "Some expected CTAs were visible.", matched
    if len(cta_text_sources) > 0:
        return 2, "Page has actions, but expected CTAs were mostly missing.", matched
    return 1, "No useful CTA text was extracted.", matched


def hallucination_risk(access_score: int, summary_score: int, cta_score: int) -> tuple[str, str]:
    average = (access_score + summary_score + cta_score) / 3

    if access_score <= 1:
        return "High", "AI tools may hallucinate because readable content is very limited."
    if average >= 4:
        return "Low", "Page has enough structured/readable content to reduce hallucination risk."
    if average >= 3:
        return "Medium", "Page is usable but may cause partial or incomplete AI answers."
    return "High", "Page content or CTAs are not exposed clearly enough for reliable AI answers."


def recommendation(access_score: int, summary_score: int, cta_score: int, risk: str) -> str:
    if access_score <= 2:
        return "Improve static HTML readability. Important content may be too dynamic or hidden."
    if cta_score <= 2:
        return "Make primary CTAs clearer in crawlable link/button text."
    if summary_score <= 2:
        return "Improve title, meta description, H1, and section headings."
    if risk == "High":
        return "Review page structure and add clearer visible copy for AI/search extraction."
    return "No urgent issue. Continue monitoring AI answer quality."


def update_monday(report_text: str) -> None:
    api_key = os.getenv("MONDAY_API_KEY")
    item_id = os.getenv("MONDAY_AI_SNIPPET_ITEM_ID")

    if not api_key or not item_id:
        print("Monday update skipped. Missing MONDAY_API_KEY or MONDAY_AI_SNIPPET_ITEM_ID.")
        return

    mutation = """
    mutation ($item_id: ID!, $body: String!) {
      create_update (item_id: $item_id, body: $body) {
        id
      }
    }
    """

    response = requests.post(
        "https://api.monday.com/v2",
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
        json={
            "query": mutation,
            "variables": {
                "item_id": str(item_id),
                "body": report_text[:60000],
            },
        },
        timeout=30,
    )

    response.raise_for_status()
    print("Monday update posted.")


def run_page_check(page, row: dict) -> dict:
    page_name = row["page_name"]
    target_url = row["target_url"]
    expected_ctas = row.get("expected_ctas", "")

    slug = slugify(page_name)

    result = {
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "page_name": page_name,
        "target_url": target_url,
        "ai_tool": "Page extraction proxy",
        "prompt": row.get("sample_prompt", ""),
        "access_status": "",
        "summary_accuracy": "",
        "cta_accuracy": "",
        "hallucination_flag": "",
        "missing_key_info": "",
        "recommendation": "",
        "access_score": 0,
        "summary_score": 0,
        "cta_score": 0,
        "screenshot": "",
        "evidence_json": "",
    }

    try:
        page.goto(target_url, wait_until="networkidle", timeout=60000)
        time.sleep(2)

        screenshot_path = SCREENSHOT_DIR / f"{slug}.png"
        evidence_path = EVIDENCE_DIR / f"{slug}.json"

        page.screenshot(path=str(screenshot_path), full_page=True)

        html = page.content()
        signals = extract_page_signals(html)

        access_score, access_note = score_accessibility(signals)
        summary_score, summary_note = score_summary_readiness(signals)
        cta_score, cta_note, matched_ctas = score_cta_accuracy(signals, expected_ctas)
        risk, risk_note = hallucination_risk(access_score, summary_score, cta_score)

        missing_ctas = []
        for cta in str(expected_ctas).split(";"):
            cta_clean = clean_text(cta).lower()
            if cta_clean and cta_clean not in matched_ctas:
                missing_ctas.append(cta)

        evidence = {
            "page_name": page_name,
            "target_url": target_url,
            "signals": signals,
            "scores": {
                "access_score": access_score,
                "summary_score": summary_score,
                "cta_score": cta_score,
                "hallucination_risk": risk,
            },
            "matched_ctas": matched_ctas,
            "missing_ctas": missing_ctas,
        }

        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

        result.update({
            "access_status": access_note,
            "summary_accuracy": summary_note,
            "cta_accuracy": cta_note,
            "hallucination_flag": f"{risk}: {risk_note}",
            "missing_key_info": "; ".join(missing_ctas) if missing_ctas else "None detected",
            "recommendation": recommendation(access_score, summary_score, cta_score, risk),
            "access_score": access_score,
            "summary_score": summary_score,
            "cta_score": cta_score,
            "screenshot": str(screenshot_path),
            "evidence_json": str(evidence_path),
        })

    except Exception as exc:
        result.update({
            "access_status": f"Failed: {exc}",
            "summary_accuracy": "Failed",
            "cta_accuracy": "Failed",
            "hallucination_flag": "High: page check failed",
            "missing_key_info": "Unable to evaluate",
            "recommendation": "Debug page loading, blocking, timeout, or selector issues.",
        })

    return result


def build_markdown_report(df: pd.DataFrame) -> str:
    report = "# AI Snippet Verification Report\n\n"
    report += f"Run date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"

    report += "## Summary\n\n"
    report += f"- Pages checked: {len(df)}\n"
    report += f"- Average access score: {df['access_score'].mean():.2f}/5\n"
    report += f"- Average summary score: {df['summary_score'].mean():.2f}/5\n"
    report += f"- Average CTA score: {df['cta_score'].mean():.2f}/5\n\n"

    risk_counts = df["hallucination_flag"].str.split(":").str[0].value_counts().to_dict()

    report += "## Hallucination Risk\n\n"
    for risk, count in risk_counts.items():
        report += f"- {risk}: {count}\n"

    report += "\n## Page Results\n\n"

    for _, row in df.iterrows():
        report += f"### {row['page_name']}\n"
        report += f"- URL: {row['target_url']}\n"
        report += f"- Access: {row['access_score']}/5 — {row['access_status']}\n"
        report += f"- Summary readiness: {row['summary_score']}/5 — {row['summary_accuracy']}\n"
        report += f"- CTA visibility: {row['cta_score']}/5 — {row['cta_accuracy']}\n"
        report += f"- Hallucination risk: {row['hallucination_flag']}\n"
        report += f"- Missing key info: {row['missing_key_info']}\n"
        report += f"- Recommendation: {row['recommendation']}\n"
        report += f"- Screenshot: `{row['screenshot']}`\n"
        report += f"- Evidence: `{row['evidence_json']}`\n\n"

    return report


def main() -> None:
    targets = pd.read_csv(TARGETS_FILE)
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1200},
            user_agent=(
                "Mozilla/5.0 AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for _, row in targets.iterrows():
            row_dict = row.fillna("").to_dict()
            print(f"Checking {row_dict['page_name']}...")
            results.append(run_page_check(page, row_dict))

        browser.close()

    df = pd.DataFrame(results)

    csv_path = REPORT_DIR / "ai_snippet_verification.csv"
    md_path = REPORT_DIR / "ai_snippet_verification.md"

    df.to_csv(csv_path, index=False)

    report = build_markdown_report(df)
    md_path.write_text(report, encoding="utf-8")

    update_monday(report)

    print(f"Report written to {csv_path}")
    print(f"Markdown written to {md_path}")


if __name__ == "__main__":
    main()
