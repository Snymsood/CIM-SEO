#!/usr/bin/env python3
"""Email the personal weekly action plan through an existing SMTP mailbox."""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path


def _address(value: str, label: str) -> str:
    _, address = parseaddr(value)
    if address != value.strip() or "@" not in address or "\n" in value or "\r" in value:
        raise ValueError(f"Invalid {label} email address")
    return address


def send(root: Path, *, smtp_factory=None) -> dict:
    recipient = _address(os.environ.get("SEO_ACTION_REPORT_TO", ""), "recipient")
    username = _address(os.environ.get("SEO_REPORT_SMTP_USER", ""), "sender")
    host = os.environ.get("SEO_REPORT_SMTP_HOST", "smtp.gmail.com")
    password = os.environ.get("SEO_REPORT_SMTP_PASSWORD", "")
    if host == "smtp.gmail.com":
        # Google displays app passwords in groups; pasted spaces are not part
        # of the 16-character credential.
        password = "".join(password.split())
    port = int(os.environ.get("SEO_REPORT_SMTP_PORT", "465"))
    if not password:
        raise ValueError("SEO_REPORT_SMTP_PASSWORD GitHub secret is not set")
    if not host or port not in (465, 587):
        raise ValueError("SMTP host and port 465 or 587 are required")

    report = json.loads((root / "weekly_personal_action_report.json").read_text(encoding="utf-8"))
    text_body = (root / "weekly_personal_action_report.txt").read_text(encoding="utf-8")
    html_body = (root / "weekly_personal_action_report.html").read_text(encoding="utf-8")
    if not report.get("actions") or not all(
        day and day in text_body for day in (report.get("period_start", ""), report.get("period_end", ""))
    ):
        raise ValueError("Personal action report is empty or period does not match its body")

    message = EmailMessage()
    message["Subject"] = f"Your {len(report['actions'])} SEO priorities | week ending {report['period_end']}"
    message["From"] = username
    message["To"] = recipient
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    if port == 465:
        factory = smtp_factory or smtplib.SMTP_SSL
        with factory(host, port, timeout=30, context=context) as server:
            server.login(username, password, initial_response_ok=False)
            server.send_message(message)
    else:
        factory = smtp_factory or smtplib.SMTP
        with factory(host, port, timeout=30) as server:
            server.starttls(context=context)
            server.login(username, password, initial_response_ok=False)
            server.send_message(message)
    return {"status": "delivered", "channel": "smtp", "period_id": report["period_id"],
            "action_count": len(report["actions"])}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    path = args.root / "personal_email_delivery_status.json"
    try:
        status = send(args.root)
    except Exception as exc:
        status = {"status": "failed", "channel": "smtp", "detail": str(exc)}
        path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        raise
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(f"Delivered personal weekly action plan for {status['period_id']} ({status['action_count']} actions).")


if __name__ == "__main__":
    main()
