"""Regression checks for misleading actions found in the October 19 run."""

import pandas as pd

from weekly_seo_intelligence import build_action_queue


def test_action_queue_requires_measured_opportunity_and_counts_unique_targets():
    data = {
        "gsc_queries": pd.DataFrame([{
            "query": "small opportunity", "clicks_current": 5,
            "impressions_current": 110, "position_current": 6,
            "ctr_current": 5 / 110,
        }]),
        "broken_links": pd.DataFrame([
            {"source_url": "https://example.com/a", "target_url": "https://example.com/missing", "issue_type": "broken"},
            {"source_url": "https://example.com/b", "target_url": "https://example.com/missing", "issue_type": "broken"},
        ]),
        "content_strategy": pd.DataFrame([{
            "strategy_status": "Email interest, weak on-site engagement",
            "page_canonical": "https://example.com/unmeasured",
            "email_unique_clicks": 250, "ga4_sessions": 0,
            "ga4_engagement_rate": 0, "strategy_score": 75,
            "gsc_impressions": 0,
        }]),
    }
    actions = build_action_queue(data, {}, [], pd.DataFrame())
    titles = [item["action"] for item in actions]
    assert any("1 unique broken targets" in title for title in titles)
    assert not any("title/meta" in title for title in titles)
    assert not any("email-clicked content" in title for title in titles)


def test_unmeasured_email_destination_becomes_tracking_action():
    data = {"content_strategy": pd.DataFrame([{
        "strategy_status": "Email clicks, no matched GA4 data",
        "page_canonical": "https://example.com/unmeasured",
        "email_unique_clicks": 250, "ga4_sessions": 0,
        "ga4_engagement_rate": 0, "strategy_score": 75,
        "gsc_impressions": 0,
    }])}
    actions = build_action_queue(data, {}, [], pd.DataFrame())
    assert any("Verify tracking" in item["action"] for item in actions)
