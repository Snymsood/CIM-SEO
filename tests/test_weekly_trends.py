"""Checks that cross-report trends preserve source scope and paired periods."""

import pandas as pd

from weekly_trends import build_weekly_trends, render_weekly_trends


def test_paired_metrics_and_cross_report_signal():
    data = {
        "ga4_summary": pd.DataFrame([
            {"metric": "sessions", "current": 40, "previous": 100},
        ]),
        "gsc_comparison": pd.DataFrame([
            {"clicks_current": 3, "clicks_previous": 5,
             "impressions_current": 200, "impressions_previous": 100},
        ]),
        "conv_summary": pd.DataFrame([
            {"current_count": 12, "previous_count": 10},
        ]),
        "speed": pd.DataFrame([
            {"strategy": "mobile", "performance_score": 60, "performance_score_previous": 50},
            {"strategy": "mobile", "performance_score": 90, "performance_score_previous": None},
        ]),
    }
    trends, insights = build_weekly_trends(data)
    by_metric = trends.set_index("metric")
    assert by_metric.loc["GSC query CTR", "current"] == 3 / 200
    assert by_metric.loc["Mobile performance score", "current"] == 60
    assert "not whole-site" in by_metric.loc["GSC query clicks", "scope"]
    assert any("impressions while clicks fell" in item for item in insights)
    assert any("sessions fell while tracked event counts rose" in item for item in insights)
    assert any("fell substantially faster" in item for item in insights)


def test_missing_previous_is_omitted_and_html_is_escaped():
    trends, insights = build_weekly_trends({
        "ga4_summary": pd.DataFrame([
            {"metric": "sessions", "current": 20, "previous": None},
        ]),
        "gsc_comparison": pd.DataFrame([
            {"clicks_current": 1, "clicks_previous": None,
             "impressions_current": 5, "impressions_previous": 5},
        ]),
    })
    assert trends.empty
    assert "No paired weekly metrics" in render_weekly_trends(trends, insights)

    html = render_weekly_trends(pd.DataFrame([{
        "metric": "<script>", "source": "test", "current": 2,
        "previous": 1, "change": 1, "change_pct": 1.0,
        "unit": "count", "scope": "<unsafe>",
    }]), ["<insight>"])
    assert "&lt;script&gt;" in html
    assert "&lt;unsafe&gt;" in html
    assert "&lt;insight&gt;" in html


def test_missing_mobile_scan_is_disclosed():
    trends, insights = build_weekly_trends({
        "speed": pd.DataFrame([
            {"strategy": "mobile", "performance_score": 61, "performance_score_previous": 60},
            {"strategy": "mobile", "performance_score": None, "performance_score_previous": 45},
        ]),
    })
    assert trends.iloc[0]["current"] == 61
    assert any("1 of 2 mobile pages" in item for item in insights)
