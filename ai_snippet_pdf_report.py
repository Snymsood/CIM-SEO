import os
import json
import textwrap
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

REPORT_DIR = Path("reports")
PDF_PATH = REPORT_DIR / "ai_snippet_verification_report.pdf"
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

    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=letter,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Small",
            parent=styles["BodyText"],
            fontSize=8,
            leading=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading2"],
            spaceBefore=12,
            spaceAfter=6,
        )
    )

    story = []

    story.append(Paragraph("CIM AI Snippet Verification Report", styles["Title"]))
    story.append(
        Paragraph(
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            styles["Small"],
        )
    )
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("AI Executive Summary", styles["SectionHeading"]))
    for line in ai_summary.split("\n"):
        if line.strip():
            story.append(Paragraph(line.strip(), styles["BodyText"]))
            story.append(Spacer(1, 0.05 * inch))

    story.append(Spacer(1, 0.2 * inch))

    avg_access = df["access_score"].mean()
    avg_summary = df["summary_score"].mean()
    avg_cta = df["cta_score"].mean()

    high_risk = sum(df["hallucination_flag"].astype(str).str.startswith("High"))
    medium_risk = sum(df["hallucination_flag"].astype(str).str.startswith("Medium"))
    low_risk = sum(df["hallucination_flag"].astype(str).str.startswith("Low"))

    story.append(Paragraph("Score Summary", styles["SectionHeading"]))

    summary_table = Table(
        [
            ["Metric", "Value"],
            ["Pages checked", str(len(df))],
            ["Average access score", f"{avg_access:.2f}/5"],
            ["Average summary score", f"{avg_summary:.2f}/5"],
            ["Average CTA score", f"{avg_cta:.2f}/5"],
            ["High risk pages", str(high_risk)],
            ["Medium risk pages", str(medium_risk)],
            ["Low risk pages", str(low_risk)],
        ],
        colWidths=[2.6 * inch, 3.6 * inch],
    )

    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    story.append(summary_table)
    story.append(PageBreak())

    story.append(Paragraph("Page-Level Results", styles["SectionHeading"]))

    table_data = [
        [
            "Page",
            "Access",
            "Summary",
            "CTA",
            "Risk",
            "Recommendation",
        ]
    ]

    for _, row in df.iterrows():
        table_data.append(
            [
                Paragraph(str(row["page_name"]), styles["Small"]),
                str(row["access_score"]),
                str(row["summary_score"]),
                str(row["cta_score"]),
                risk_label(row["hallucination_flag"]),
                Paragraph(str(row["recommendation"]), styles["Small"]),
            ]
        )

    results_table = Table(
        table_data,
        colWidths=[
            1.35 * inch,
            0.55 * inch,
            0.65 * inch,
            0.45 * inch,
            0.7 * inch,
            3.0 * inch,
        ],
        repeatRows=1,
    )

    results_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )

    story.append(results_table)
    story.append(PageBreak())

    story.append(Paragraph("Detailed Findings", styles["SectionHeading"]))

    for _, row in df.iterrows():
        story.append(Paragraph(str(row["page_name"]), styles["Heading3"]))
        story.append(Paragraph(f"URL: {row['target_url']}", styles["Small"]))
        story.append(Paragraph(f"Access: {row['access_score']}/5 - {row['access_status']}", styles["Small"]))
        story.append(Paragraph(f"Summary readiness: {row['summary_score']}/5 - {row['summary_accuracy']}", styles["Small"]))
        story.append(Paragraph(f"CTA visibility: {row['cta_score']}/5 - {row['cta_accuracy']}", styles["Small"]))
        story.append(Paragraph(f"Hallucination risk: {row['hallucination_flag']}", styles["Small"]))
        story.append(Paragraph(f"Missing key info: {row['missing_key_info']}", styles["Small"]))
        story.append(Paragraph(f"Recommendation: {row['recommendation']}", styles["Small"]))
        story.append(Spacer(1, 0.15 * inch))

    doc.build(story)
    print(f"PDF created: {PDF_PATH}")


def create_monday_update(body):
    api_key = os.getenv("MONDAY_API_KEY")
    item_id = os.getenv("MONDAY_AI_SNIPPET_ITEM_ID")

    if not api_key or not item_id:
        print("Monday update skipped. Missing MONDAY_API_KEY or MONDAY_AI_SNIPPET_ITEM_ID.")
        return None

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
                "body": body[:60000],
            },
        },
        timeout=30,
    )

    response.raise_for_status()
    return response.json()["data"]["create_update"]["id"]


def upload_pdf_to_monday(update_id):

    api_key = os.getenv("MONDAY_API_KEY")

    if not api_key or not update_id:

        print("PDF upload skipped.")

        return

    mutation = """

    mutation ($file: File!, $update_id: ID!) {

      add_file_to_update (file: $file, update_id: $update_id) {

        id

      }

    }

    """

    with open(PDF_PATH, "rb") as file_handle:

        data = {

            "query": mutation,

            "variables": json.dumps({

                "file": None,

                "update_id": str(update_id)

            }),

            "map": json.dumps({

                "0": ["variables.file"]

            }),

        }

        files = {

            "0": (

                PDF_PATH.name,

                file_handle,

                "application/pdf"

            )

        }

        response = requests.post(

            "https://api.monday.com/v2/file",

            headers={

                "Authorization": api_key

            },

            data=data,

            files=files,

            timeout=60,

        )

    if not response.ok:

        print("Monday file upload failed.")

        print("Status:", response.status_code)

        print("Response:", response.text)

        response.raise_for_status()

    print("PDF uploaded to Monday update.")


def main():
    df, md_text = read_inputs()
    ai_summary = groq_summary(df, md_text)
    build_pdf(df, ai_summary)

    monday_body = f"""
AI Snippet Verification PDF report generated.

Pages checked: {len(df)}
Average access score: {df['access_score'].mean():.2f}/5
Average summary score: {df['summary_score'].mean():.2f}/5
Average CTA score: {df['cta_score'].mean():.2f}/5

{ai_summary}
"""

    update_id = create_monday_update(monday_body)
    upload_pdf_to_monday(update_id)


if __name__ == "__main__":
    main()
