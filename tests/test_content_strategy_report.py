"""Email clicks without matched analytics must not be called poor engagement."""

import pandas as pd

import content_strategy_report as report


def test_email_destination_without_ga4_is_coverage_gap(monkeypatch):
    url = "https://register.example.com/signup"
    monkeypatch.setattr(report, "build_gsc_page_signals", lambda: pd.DataFrame(columns=["page_canonical"]))
    monkeypatch.setattr(report, "build_ga4_page_signals", lambda: pd.DataFrame(columns=["page_canonical"]))
    monkeypatch.setattr(report, "build_mailchimp_signals", lambda: pd.DataFrame([{
        "page_canonical": url, "email_unique_clicks": 250,
    }]))
    monkeypatch.setattr(report, "build_internal_link_signals", lambda: pd.DataFrame(columns=["page_canonical"]))
    monkeypatch.setattr(report, "build_content_audit_signals", lambda: pd.DataFrame(columns=["page_canonical"]))

    scorecard = report.build_strategy_scorecard()
    assert scorecard.iloc[0]["strategy_status"] == "Email clicks, no matched GA4 data"
    opportunities = report.build_opportunities(scorecard)
    assert "Verify destination URL mapping" in opportunities.iloc[0]["recommended_action"]
