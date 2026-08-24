# ══════════════════════════════════════════════════════════════════════════════
# email_utils.py
# CIM SEO — Shared email helper
#
# Mirrors the SMTP configuration already used by action_layer/digest_generator.py.
# Uses the same env vars: SMTP_HOST, SMTP_PORT, SMTP_PASSWORD,
# DIGEST_EMAIL_SENDER, DIGEST_EMAIL_RECIPIENT — so no new secrets are needed.
#
# The only addition is EVENT_REPORT_RECIPIENTS (comma-separated) for sending
# the GA4 event report to multiple people.
# ══════════════════════════════════════════════════════════════════════════════

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Config — same variable names as action_layer/digest_generator.py ──────────
SMTP_HOST     = os.environ.get("SMTP_HOST")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", 587))
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")

# Sender: reuse digest sender if set, otherwise fall back to EVENT_ vars
EMAIL_SENDER  = (
    os.environ.get("DIGEST_EMAIL_SENDER") or
    os.environ.get("EMAIL_FROM_ADDRESS", "")
)
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "CIM SEO Reports")

# Recipients for the GA4 event report
# Can be a single address (DIGEST_EMAIL_RECIPIENT) or comma-separated list
def get_event_report_recipients() -> List[str]:
    """
    Return a list of recipient addresses for the GA4 event report.
    Checks EVENT_REPORT_RECIPIENTS first (comma-separated), then
    falls back to the existing DIGEST_EMAIL_RECIPIENT var.
    Raises ValueError if neither is set.
    """
    raw = (
        os.environ.get("EVENT_REPORT_RECIPIENTS", "") or
        os.environ.get("DIGEST_EMAIL_RECIPIENT", "")
    ).strip()
    if not raw:
        raise ValueError(
            "No email recipients configured.\n"
            "Set EVENT_REPORT_RECIPIENTS=a@example.com,b@example.com in your .env file.\n"
            "(Falls back to DIGEST_EMAIL_RECIPIENT if EVENT_REPORT_RECIPIENTS is not set.)"
        )
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def _validate_smtp_config():
    """Raise ValueError with a clear message if SMTP credentials are missing."""
    missing = [k for k in ("SMTP_HOST", "SMTP_PASSWORD") if not os.environ.get(k)]
    if missing or not EMAIL_SENDER:
        raise ValueError(
            f"Missing SMTP configuration: {missing + (['sender address'] if not EMAIL_SENDER else [])}.\n"
            "These are the same variables used by action_layer/digest_generator.py.\n"
            "Check your .env file: SMTP_HOST, SMTP_PORT, SMTP_PASSWORD, DIGEST_EMAIL_SENDER."
        )


# ── Core send function ─────────────────────────────────────────────────────────

def send_html_email(
    subject: str,
    html_body: str,
    recipients: Optional[List[str]] = None,
    plain_text: Optional[str] = None,
) -> bool:
    """
    Send a styled HTML email via SMTP.

    Uses the same SMTP credentials (SMTP_HOST / SMTP_PORT / SMTP_PASSWORD /
    DIGEST_EMAIL_SENDER) already configured for action_layer/digest_generator.py.

    Args:
        subject:     Email subject line.
        html_body:   Full HTML string. Should use inline CSS for email clients.
        recipients:  List of To: addresses. Reads from env if None.
        plain_text:  Plain-text fallback. Auto-stripped from HTML if None.

    Returns:
        True on success, False on failure (error is logged and printed).
    """
    try:
        _validate_smtp_config()

        if recipients is None:
            recipients = get_event_report_recipients()

        # Build message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{EMAIL_FROM_NAME} <{EMAIL_SENDER}>"
        msg["To"]      = ", ".join(recipients)

        # Auto-generate plain-text fallback
        if plain_text is None:
            import re
            plain_text = re.sub(r"<[^>]+>", " ", html_body)
            plain_text = re.sub(r"\s+", " ", plain_text).strip()

        msg.attach(MIMEText(plain_text, "plain", "utf-8"))
        msg.attach(MIMEText(html_body,  "html",  "utf-8"))

        port = SMTP_PORT
        host = SMTP_HOST

        # Match digest_generator.py pattern exactly
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as server:
                server.login(EMAIL_SENDER, SMTP_PASSWORD)
                server.sendmail(EMAIL_SENDER, recipients, msg.as_string())
        else:
            # Default: port 587 STARTTLS (used by digest_generator.py)
            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(EMAIL_SENDER, SMTP_PASSWORD)
                server.sendmail(EMAIL_SENDER, recipients, msg.as_string())

        logger.info("✓ Email sent: '%s' → %s", subject, recipients)
        print(f"  ✓ Email sent to {len(recipients)} recipient(s): {', '.join(recipients)}", flush=True)
        return True

    except Exception as exc:
        logger.error("✗ Email send failed: %s", exc)
        print(f"  ✗ Email send failed: {exc}", flush=True)
        return False
