#!/usr/bin/env python3
"""Send the personal weekly plan as a one-recipient Mailchimp test email.

Uses the Mailchimp Marketing account already connected to this repository. It
creates a draft campaign and calls only the test-send endpoint; it never sends
the campaign to the audience.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from email.utils import parseaddr
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _address(value: str, label: str) -> str:
    _, address = parseaddr(value)
    if address != value.strip() or "@" not in address or "\n" in value or "\r" in value:
        raise ValueError(f"Invalid {label} email address")
    return address


def _api(base: str, key: str, method: str, path: str, payload: dict | None = None,
         *, opener=urlopen) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    basic = base64.b64encode(f"cim-seo:{key}".encode("utf-8")).decode("ascii")
    request = Request(base + path, data=data, method=method,
                      headers={"Authorization": f"Basic {basic}",
                               "Content-Type": "application/json"})
    try:
        with opener(request, timeout=45) as response:
            content = response.read()
            return json.loads(content) if content else {}
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail", "")
        except (ValueError, UnicodeError):
            detail = ""
        raise RuntimeError(f"Mailchimp {method} {path.split('?')[0]} returned HTTP {exc.code}: {detail[:300]}") from exc


def send(root: Path, *, api=_api) -> dict:
    key = os.environ.get("MAILCHIMP_API_KEY", "")
    audience = os.environ.get("MAILCHIMP_AUDIENCE_ID", "")
    recipient = _address(os.environ.get("SEO_ACTION_REPORT_TO", ""), "recipient")
    if not key or "-" not in key or not audience:
        raise ValueError("Existing MAILCHIMP_API_KEY and MAILCHIMP_AUDIENCE_ID secrets are required")
    prefix = key.rsplit("-", 1)[-1]
    if not prefix.startswith("us") or not prefix[2:].isdigit():
        raise ValueError("MAILCHIMP_API_KEY has no valid data-center suffix")
    base = f"https://{prefix}.api.mailchimp.com/3.0"

    report = json.loads((root / "weekly_personal_action_report.json").read_text(encoding="utf-8"))
    text_body = (root / "weekly_personal_action_report.txt").read_text(encoding="utf-8")
    html_body = (root / "weekly_personal_action_report.html").read_text(encoding="utf-8")
    if not report.get("actions") or len(report["actions"]) > 5 or not all(
        day and day in text_body for day in (report.get("period_start", ""), report.get("period_end", ""))
    ):
        raise ValueError("Personal action report is empty or period does not match its body")

    # Reuse the sender identity of a previously sent campaign in this audience.
    # Mailchimp has already accepted that identity for the organization's mail.
    query = urlencode({"status": "sent", "type": "regular", "list_id": audience,
                       "sort_field": "send_time", "sort_dir": "DESC", "count": 25})
    campaigns = api(base, key, "GET", f"/campaigns?{query}").get("campaigns", [])
    sender = next((c.get("settings", {}) for c in campaigns
                   if c.get("settings", {}).get("from_name") and
                   c.get("settings", {}).get("reply_to")), None)
    if not sender:
        raise ValueError("No sent Mailchimp campaign with a reusable sender was found for this audience")
    from_name = str(sender["from_name"]).strip()
    reply_to = _address(str(sender["reply_to"]), "Mailchimp reply-to")
    subject = f"Your {len(report['actions'])} SEO priorities | week ending {report['period_end']}"
    campaign = api(base, key, "POST", "/campaigns", {
        "type": "regular",
        "recipients": {"list_id": audience},
        "settings": {"subject_line": subject,
                     "title": f"CIM SEO personal action report {report['period_id']} (test only)",
                     "from_name": from_name, "reply_to": reply_to},
    })
    campaign_id = campaign.get("id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise RuntimeError("Mailchimp did not return a draft campaign ID")
    api(base, key, "PUT", f"/campaigns/{campaign_id}/content",
        {"html": html_body, "plain_text": text_body})
    # This endpoint addresses only the specified test recipient. Never use the
    # regular campaign-send endpoint, which could email the whole audience.
    api(base, key, "POST", f"/campaigns/{campaign_id}/actions/test",
        {"test_emails": [recipient], "send_type": "html"})
    return {"status": "submitted", "channel": "mailchimp_test",
            "period_id": report["period_id"], "action_count": len(report["actions"]),
            "campaign_id": campaign_id, "recipient_count": 1}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    path = args.root / "personal_email_delivery_status.json"
    try:
        status = send(args.root)
    except Exception as exc:
        status = {"status": "failed", "channel": "mailchimp_test", "detail": str(exc)}
        path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        raise
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(f"Mailchimp accepted one test email for {status['period_id']} (campaign {status['campaign_id']}).")


if __name__ == "__main__":
    main()
