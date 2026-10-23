#!/usr/bin/env python3
"""Send the weekly action plan to a Google Apps Script MailApp receiver."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def send(root: Path, *, opener=urlopen) -> dict:
    url = os.environ.get("SEO_ACTION_APPS_SCRIPT_URL", "")
    token = os.environ.get("SEO_ACTION_APPS_SCRIPT_TOKEN", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "script.google.com" or not parsed.path.startswith("/macros/s/") or not parsed.path.endswith("/exec"):
        raise ValueError("SEO_ACTION_APPS_SCRIPT_URL must be a deployed Google Apps Script /exec URL")
    if len(token) < 32:
        raise ValueError("SEO_ACTION_APPS_SCRIPT_TOKEN must be a random secret of at least 32 characters")

    report = json.loads((root / "weekly_personal_action_report.json").read_text(encoding="utf-8"))
    text_body = (root / "weekly_personal_action_report.txt").read_text(encoding="utf-8")
    html_body = (root / "weekly_personal_action_report.html").read_text(encoding="utf-8")
    if not report.get("actions") or not all(
        day and day in text_body for day in (report.get("period_start", ""), report.get("period_end", ""))
    ):
        raise ValueError("Personal action report is empty or period does not match its body")

    payload = {"token": token, "period_id": report["period_id"],
               "action_count": len(report["actions"]), "text_body": text_body,
               "html_body": html_body}
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    with opener(request, timeout=45) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok") or result.get("period_id") != report["period_id"]:
        raise RuntimeError(f"Google Apps Script did not confirm delivery: {result.get('error', 'invalid_response')}")
    return {"status": "delivered", "channel": "google_apps_script", "period_id": report["period_id"],
            "action_count": len(report["actions"]), "detail": "already_sent" if result.get("duplicate") else "sent"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    path = args.root / "personal_email_delivery_status.json"
    try:
        status = send(args.root)
    except Exception as exc:
        status = {"status": "failed", "channel": "google_apps_script", "detail": str(exc)}
        path.write_text(json.dumps(status, indent=2), encoding="utf-8")
        raise
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(f"Google Apps Script confirmed personal action email for {status['period_id']} ({status['detail']}).")


if __name__ == "__main__":
    main()
