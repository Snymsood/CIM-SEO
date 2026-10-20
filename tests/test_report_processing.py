import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from issue_history import update_issue_history
from search_opportunities import rank_query_page_losses
from validate_source_artifact import validate_artifact
from weekly_trends import update_trend_history, history_signals


def test_source_artifact_rejects_stale_week_and_records_run(tmp_path, monkeypatch):
    monkeypatch.setattr("validate_source_artifact.get_weekly_date_windows",
                        lambda: (date(2026, 10, 12), date(2026, 10, 18), date(2026, 10, 5), date(2026, 10, 11)))
    folder = tmp_path / "artifact"
    folder.mkdir()
    manifest = {"report_name": "GSC Weekly", "period_start": "2026-10-05", "period_end": "2026-10-11",
                "period_id": "2026-10-05_2026-10-11", "run_id": "22"}
    (folder / "report_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="differs"):
        validate_artifact(folder, "gsc-weekly-report", "22", tmp_path / "runs.json")
    manifest.update(period_start="2026-10-12", period_end="2026-10-18", period_id="2026-10-12_2026-10-18")
    (folder / "report_manifest.json").write_text(json.dumps(manifest))
    validate_artifact(folder, "gsc-weekly-report", "22", tmp_path / "runs.json")
    assert json.loads((tmp_path / "runs.json").read_text())[0]["run_id"] == "22"
    manifest.update(period_start="2026-09-21", period_id="2026-09-21_2026-10-18")
    (folder / "report_manifest.json").write_text(json.dumps(manifest))
    validate_artifact(folder, "content-audit-schedule", "22", tmp_path / "runs.json")


def test_history_deduplicates_rerun_and_requires_distinct_weeks():
    trend = pd.DataFrame([{"metric": "GA4 sessions", "source": "GA4", "current": 100,
                           "unit": "count", "scope": "weekly"}])
    first = update_trend_history(pd.DataFrame(), trend, "2026-10-12", "2026-10-18")
    trend.loc[0, "current"] = 110
    rerun = update_trend_history(first, trend, "2026-10-12", "2026-10-18")
    assert len(rerun) == 1
    assert rerun.iloc[0]["value"] == 110
    assert history_signals(rerun) == []


def test_query_page_losses_are_allocated_by_impressions_and_labeled():
    comparison = pd.DataFrame([{"query": "mining jobs", "clicks_previous": 20, "clicks_current": 10}])
    mapping = pd.DataFrame([{"query": "mining jobs", "page": "/a", "impressions": 75},
                            {"query": "mining jobs", "page": "/b", "impressions": 25}])
    ranked = rank_query_page_losses(comparison, mapping)
    assert ranked["allocated_lost_clicks"].tolist() == [7.5, 2.5]
    assert ranked["demand_type"].eq("non-branded").all()
    assert "estimate" in ranked.iloc[0]["evidence_scope"]


def test_issue_lifecycle_preserves_first_seen_and_resolves_absent_target():
    old = pd.DataFrame([{"target_url": "/a", "first_seen": "2026-10-12", "last_seen": "2026-10-12", "status": "open"},
                        {"target_url": "/b", "first_seen": "2026-10-12", "last_seen": "2026-10-12", "status": "open"}])
    current = pd.DataFrame([{"target_url": "/a"}])
    result = update_issue_history(old, current, "target_url", "2026-10-19").set_index("target_url")
    assert result.loc["/a", "first_seen"] == "2026-10-12"
    assert result.loc["/a", "last_seen"] == "2026-10-19"
    assert result.loc["/b", "status"] == "resolved"


def test_mailchimp_executive_rates_exclude_test_sends_and_weight_by_delivery():
    from mailchimp_weekly_report import build_summary
    campaigns = pd.DataFrame({"campaign_id": ["test", "large", "small"]})
    reports = pd.DataFrame([
        {"campaign_id": "test", "emails_sent": 1, "emails_delivered_estimate": 1, "open_rate": 1.0, "click_rate": 1.0},
        {"campaign_id": "large", "emails_sent": 1000, "emails_delivered_estimate": 900, "open_rate": .2, "click_rate": .1},
        {"campaign_id": "small", "emails_sent": 100, "emails_delivered_estimate": 100, "open_rate": .5, "click_rate": .2},
    ])
    summary = build_summary(campaigns, reports, pd.DataFrame()).iloc[0]
    assert summary["test_sends_excluded"] == 1
    assert summary["emails_delivered_estimate"] == 1000
    assert summary["avg_open_rate"] == pytest.approx(.23)


def test_channel_comparison_exposes_contribution_to_channel_total(monkeypatch):
    monkeypatch.setenv("GA4_PROPERTY_ID", "test-property")
    from ga4_weekly_report import prepare_channel_comparison
    current = pd.DataFrame({"sessionDefaultChannelGroup": ["Direct", "Organic Search"], "sessions": [40, 60]})
    previous = pd.DataFrame({"sessionDefaultChannelGroup": ["Direct", "Organic Search"], "sessions": [100, 70]})
    result = prepare_channel_comparison(current, previous).set_index("sessionDefaultChannelGroup")
    assert result.loc["Direct", "sessions_change"] == -60
    assert result.loc["Direct", "share_of_net_change"] == pytest.approx(60 / 70)
