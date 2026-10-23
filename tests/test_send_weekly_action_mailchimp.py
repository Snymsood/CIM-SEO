import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from send_weekly_action_mailchimp import send


class MailchimpPersonalSendTests(unittest.TestCase):
    def test_only_one_test_recipient_and_no_audience_send(self):
        calls = []

        def fake_api(_base, _key, method, path, payload=None):
            calls.append((method, path, payload))
            if path.startswith("/campaigns?"):
                return {"campaigns": [{"settings": {"from_name": "CIM",
                                                    "reply_to": "reports@cim.org"}}]}
            if method == "POST" and path == "/campaigns":
                return {"id": "draft123"}
            return {}

        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            "MAILCHIMP_API_KEY": "secret-us6",
            "MAILCHIMP_AUDIENCE_ID": "audience123",
            "SEO_ACTION_REPORT_TO": "specialist@example.com",
        }):
            root = Path(temp)
            report = {"period_id": "2026-10-12_2026-10-18",
                      "period_start": "2026-10-12", "period_end": "2026-10-18",
                      "actions": [{"title": "Fix page"}]}
            (root / "weekly_personal_action_report.json").write_text(json.dumps(report))
            (root / "weekly_personal_action_report.txt").write_text("2026-10-12 to 2026-10-18")
            (root / "weekly_personal_action_report.html").write_text("<p>Fix page</p>")

            result = send(root, api=fake_api)

        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["recipient_count"], 1)
        self.assertEqual(calls[-1], ("POST", "/campaigns/draft123/actions/test",
                                     {"test_emails": ["specialist@example.com"], "send_type": "html"}))
        self.assertFalse(any(path.endswith("/actions/send") for _, path, _ in calls))


if __name__ == "__main__":
    unittest.main()
