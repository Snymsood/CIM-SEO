import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from send_weekly_action_email import send
from weekly_personal_action_report import build_report, render_html, render_text


def _csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _base(tmp_path):
    period = "2026-10-12_2026-10-18"
    (tmp_path / "source_report_runs.json").write_text(json.dumps([
        {"artifact": name, "period_id": period, "run_id": str(index)}
        for index, name in enumerate(("gsc-weekly-report", "ga4-weekly-report"), 1)
    ]))
    return period


def test_personal_report_uses_page_evidence_and_labels_lab_scope(tmp_path):
    _base(tmp_path)
    (tmp_path / "weekly_seo_action_queue.json").write_text(json.dumps([
        {"source": "Site Speed Report", "action": "Improve mobile PageSpeed for: https://www.cim.org/",
         "priority_score": 70, "category": "Technical Health", "estimated_impact": "high", "effort": "medium", "confidence": "high"},
    ]))
    _csv(tmp_path / "site_speed_latest_snapshot.csv", [
        {"page": "https://www.cim.org/", "strategy": "mobile", "performance_score": "27",
         "lcp_lab_ms": "15000", "cwv_pass": "True"},
    ])
    _csv(tmp_path / "site_speed_opportunities.csv", [
        {"page": "https://www.cim.org/", "issue": "Unused JavaScript", "savings_ms": "750"},
    ])
    _csv(tmp_path / "site_portfolio_trends.csv", [
        {"site_id": "magazine", "site_name": "CIM Magazine", "metric": "GA4 sessions",
         "current": "1357", "previous": "1227", "change_pct": "0.1059"},
    ])
    report = build_report(tmp_path)
    assert report["period_id"] == "2026-10-12_2026-10-18"
    assert report["actions"][0]["details"]["page"] == "https://www.cim.org/"
    assert "Field Core Web Vitals pass" in report["actions"][0]["evidence"]
    assert "Unused JavaScript" in render_html(report)
    assert "CIM Magazine" in render_html(report)


def test_personal_report_rejects_missing_or_mixed_source_weeks(tmp_path):
    _base(tmp_path)
    (tmp_path / "source_report_runs.json").write_text(json.dumps([
        {"artifact": "gsc-weekly-report", "period_id": "2026-10-12_2026-10-18"},
        {"artifact": "ga4-weekly-report", "period_id": "2026-10-05_2026-10-11"},
    ]))
    with pytest.raises(ValueError, match="Current GSC and GA4"):
        build_report(tmp_path)


def test_smtp_delivery_has_plain_text_and_html_without_exposing_password(tmp_path, monkeypatch):
    report = {"period_start": "2026-10-12", "period_end": "2026-10-18", "period_id": "2026-10-12_2026-10-18",
              "actions": [{"title": "Check a page", "evidence": "One affected URL", "steps": [],
                           "verify": "Recheck next week", "links": []}]}
    (tmp_path / "weekly_personal_action_report.json").write_text(json.dumps(report))
    (tmp_path / "weekly_personal_action_report.txt").write_text(render_text(report))
    (tmp_path / "weekly_personal_action_report.html").write_text("<h1>Check a page</h1>")
    monkeypatch.setenv("SEO_ACTION_REPORT_TO", "specialist@example.com")
    monkeypatch.setenv("SEO_REPORT_SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SEO_REPORT_SMTP_PASSWORD", "test- password")
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, **kwargs):
            captured["endpoint"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def login(self, user, password):
            assert (user, password) == ("sender@example.com", "test-password")

        def send_message(self, message):
            captured["message"] = message

    assert send(tmp_path, smtp_factory=FakeSMTP)["status"] == "delivered"
    message = captured["message"]
    assert message["To"] == "specialist@example.com"
    assert "Check a page" in message.get_body(preferencelist=("plain",)).get_content()
    assert "<h1>Check a page</h1>" in message.get_body(preferencelist=("html",)).get_content()
    assert "test-password" not in message.as_string()
