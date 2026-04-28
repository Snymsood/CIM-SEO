import os
import json
import html
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from weasyprint import HTML

from pdf_report_formatter import get_pdf_css, html_table_from_df, build_card
from monday_utils import upload_pdf_to_monday as _upload_pdf

REPORT_DIR = Path("reports")
PDF_PATH = REPORT_DIR / "ai_snippet_verification_report.pdf"
HTML_PATH = REPORT_DIR / "ai_snippet_verification_report.html"
CSV_PATH = REPORT_DIR / "ai_snippet_verification.csv"
MD_PATH = REPORT_DIR / "ai_snippet_verification.md"

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")


def read_inputs():
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Missing {CSV_PATH}. Run ai_snippet_verification.py first.")

    df = pd.read_csv(CSV_PATH)

    md_text = ""
    if MD_PATH.exists():
        md_text = MD_PATH.read_text(encoding="utf-8")

    return df, md_text


def groq_summary(df, md_text):
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return "Groq summary skipped because GROQ_API_KEY is not set."

    compact_rows = df[
        [
            "page_name",
            "target_url",
            "access_score",
            "summary_score",
            "cta_score",
            "hallucination_flag",
            "missing_key_info",
            "recommendation",
        ]
    ].to_dict(orient="records")

    prompt = f"""
You are writing a concise executive SEO/AI visibility report for CIM.

Use the data below to produce:
1. Executive summary, max 120 words.
2. Top 3 findings.
3. Top 3 recommended actions.
4. One sentence explaining AI hallucination risk.

Do not invent facts.
Keep it business-focused and concise.

DATA:
{json.dumps(compact_rows, indent=2)}

MARKDOWN REPORT EXCERPT:
{md_text[:8000]}
"""

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a concise SEO/SEM reporting analyst.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0.2,
            "max_tokens": 900,
        },
        timeout=60,
    )

    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def risk_label(value):
    value = str(value)
    if value.startswith("High"):
        return "High"
    if value.startswith("Medium"):
        return "Medium"
    if value.startswith("Low"):
        return "Low"
    return "Unknown"


def build_pdf(df, ai_summary):
    REPORT_DIR.mkdir(exist_ok=True)

    df["hallucination_flag"] = df["hallucination_flag"].apply(risk_label)
    
    avg_access = df["access_score"].mean()
    avg_summary = df["summary_score"].mean()
    avg_cta = df["cta_score"].mean()

    high_risk = sum(df["hallucination_flag"] == "High")
    medium_risk = sum(df["hallucination_flag"] == "Medium")
    low_risk = sum(df["hallucination_flag"] == "Low")

    html_output = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AI Snippet Verification Report</title>
<style>
{get_pdf_css()}
</style>
</head>
<body>
    <div class="header-bar">
        <h1>AI Snippet Verification Report</h1>
        <div class="subtitle">Generated: {datetime.now(timezone.utc).strftime('%B %d, %Y at %H:%M UTC')}</div>
    </div>

    <div class="panel">
        <h2>AI Executive Summary</h2>
        <div class="ai-block">{html.escape(ai_summary)}</div>
    </div>

    <div class="grid">
        {build_card("Pages Checked", len(df), None)}
        {build_card("Avg Access Score", avg_access, None, decimals=2)}
        {build_card("Avg Summary Score", avg_summary, None, decimals=2)}
        {build_card("Avg CTA Score", avg_cta, None, decimals=2)}
    </div>

    <h2>Hallucination Risk Summary</h2>
    <div class="grid">
        {build_card("High Risk", high_risk, None)}
        {build_card("Medium Risk", medium_risk, None)}
        {build_card("Low Risk", low_risk, None)}
    </div>

    <div class="break-before"></div>
    <h2>Page-Level Results</h2>
    {html_table_from_df(
        df,
        ["page_name", "access_score", "summary_score", "cta_score", "hallucination_flag", "recommendation"],
        {
            "page_name": "Page Name",
            "access_score": "Access",
            "summary_score": "Summary",
            "cta_score": "CTA",
            "hallucination_flag": "Risk",
            "recommendation": "Recommendation"
        }
    )}
</body>
</html>
"""
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html_output)

    HTML(filename=str(HTML_PATH)).write_pdf(str(PDF_PATH))
    print(f"PDF created: {PDF_PATH}")


def upload_pdf_to_monday():
    _upload_pdf(
        str(PDF_PATH),
        body_text="AI Snippet Verification PDF report attached.",
        pdf_filename="ai-snippet-verification-report.pdf"
    )


def main():
    df, md_text = read_inputs()
    ai_summary = groq_summary(df, md_text)
    build_pdf(df, ai_summary)

    upload_pdf_to_monday()


if __name__ == "__main__":
    main()
