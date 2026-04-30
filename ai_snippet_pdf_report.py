import os
import json
import html
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

from pdf_report_formatter import html_table_from_df
from html_report_utils import (
    mm_html_shell, mm_kpi_card, mm_kpi_grid, mm_section, mm_report_section,
    mm_ai_block, generate_self_contained_html, upload_html_to_monday,
)

REPORT_DIR = Path("reports")
HTML_PATH  = REPORT_DIR / "ai_snippet_verification_report.html"
FINAL_PATH = REPORT_DIR / "ai_snippet_verification_report_final.html"
CSV_PATH   = REPORT_DIR / "ai_snippet_verification.csv"
MD_PATH    = REPORT_DIR / "ai_snippet_verification.md"

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


def build_html(df, ai_summary):
    REPORT_DIR.mkdir(exist_ok=True)

    df["hallucination_flag"] = df["hallucination_flag"].apply(risk_label)

    avg_access  = df["access_score"].mean()
    avg_summary = df["summary_score"].mean()
    avg_cta     = df["cta_score"].mean()
    high_risk   = int(sum(df["hallucination_flag"] == "High"))
    medium_risk = int(sum(df["hallucination_flag"] == "Medium"))
    low_risk    = int(sum(df["hallucination_flag"] == "Low"))

    kpi_grid = mm_kpi_grid(
        mm_kpi_card("Pages Checked",     len(df),     None),
        mm_kpi_card("Avg Access Score",  avg_access,  None, decimals=2),
        mm_kpi_card("Avg Summary Score", avg_summary, None, decimals=2),
        mm_kpi_card("Avg CTA Score",     avg_cta,     None, decimals=2),
    )
    risk_grid = mm_kpi_grid(
        mm_kpi_card("High Risk",   high_risk,   None),
        mm_kpi_card("Medium Risk", medium_risk, None),
        mm_kpi_card("Low Risk",    low_risk,    None),
        mm_kpi_card("Total Pages", len(df),     None),
    )

    results_tbl = html_table_from_df(
        df,
        ["page_name","access_score","summary_score","cta_score","hallucination_flag","recommendation"],
        {"page_name":"Page Name","access_score":"Access","summary_score":"Summary",
         "cta_score":"CTA","hallucination_flag":"Risk","recommendation":"Recommendation"}
    )

    body = (
        mm_section("AI Executive Summary",
            mm_report_section(mm_ai_block(ai_summary))
        ) +
        f'<div class="section" style="padding-top:0;">{kpi_grid}</div>'
        '<hr class="rule-thick">' +
        mm_section("Hallucination Risk Summary",
            f'<div class="section" style="padding-top:0;">{risk_grid}</div>'
        ) +
        mm_section("Page-Level Results",
            mm_report_section(results_tbl)
        )
    )

    doc = mm_html_shell(
        title="AI Snippet Verification Report",
        eyebrow="CIM SEO — AI Visibility",
        headline="AI Snippet\nVerification",
        meta_line=f"Generated {datetime.now(timezone.utc).strftime('%B %d, %Y at %H:%M UTC')}",
        body_content=body,
    )
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"Saved {HTML_PATH}")


def generate_self_contained():
    generate_self_contained_html(str(HTML_PATH), str(FINAL_PATH))


def upload_to_monday():
    upload_html_to_monday(
        str(FINAL_PATH),
        "ai-snippet-verification-report.html",
        body_text="AI Snippet Verification Report attached as self-contained HTML.",
    )


def main():
    df, md_text = read_inputs()
    ai_summary  = groq_summary(df, md_text)
    build_html(df, ai_summary)
    generate_self_contained()

    try:
        upload_to_monday()
    except Exception as e:
        print(f"Monday upload failed: {e}")


if __name__ == "__main__":
    main()
