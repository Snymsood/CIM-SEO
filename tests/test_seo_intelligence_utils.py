"""
tests/test_seo_intelligence_utils.py
Unit tests for seo_intelligence_utils.py deterministic logic.
No live API calls — all tests use mock DataFrames.
Run with: python -m pytest tests/ -v
"""

import math
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest

from seo_intelligence_utils import (
    safe_pct_change,
    safe_float,
    clamp,
    classify_trend,
    compute_trend_fields,
    detect_anomaly,
    build_anomaly_table,
    score_content_decay,
    make_action,
    sort_action_queue,
    deduplicate_actions,
    score_action_priority,
    effort_label_to_score,
    severity_to_urgency,
    confidence_label_to_score,
    compute_conversion_rate,
    compute_conversions_per_100,
    estimate_business_value,
    make_warning,
    DEFAULT_THRESHOLDS,
)


# ══════════════════════════════════════════════════════════════════════════════
# BASIC MATH
# ══════════════════════════════════════════════════════════════════════════════

class TestSafePctChange:
    def test_positive_change(self):
        assert safe_pct_change(120, 100) == pytest.approx(0.20)

    def test_negative_change(self):
        assert safe_pct_change(80, 100) == pytest.approx(-0.20)

    def test_zero_previous(self):
        assert safe_pct_change(100, 0) is None

    def test_zero_both(self):
        assert safe_pct_change(0, 0) is None

    def test_no_change(self):
        assert safe_pct_change(100, 100) == pytest.approx(0.0)


class TestSafeFloat:
    def test_normal(self):
        assert safe_float(3.14) == pytest.approx(3.14)

    def test_string(self):
        assert safe_float("42") == pytest.approx(42.0)

    def test_none(self):
        assert safe_float(None) == 0.0

    def test_nan(self):
        assert safe_float(float("nan")) == 0.0

    def test_default(self):
        assert safe_float(None, default=99.0) == 99.0


class TestClamp:
    def test_within_range(self):
        assert clamp(50) == 50

    def test_below_min(self):
        assert clamp(-10) == 0

    def test_above_max(self):
        assert clamp(150) == 100

    def test_custom_range(self):
        assert clamp(5, lo=0, hi=10) == 5
        assert clamp(-1, lo=0, hi=10) == 0
        assert clamp(11, lo=0, hi=10) == 10


# ══════════════════════════════════════════════════════════════════════════════
# TREND CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyTrend:
    def test_rising(self):
        assert classify_trend([100, 110, 120, 130, 140]) == "rising"

    def test_falling(self):
        assert classify_trend([140, 130, 120, 110, 100]) == "falling"

    def test_flat(self):
        assert classify_trend([100, 101, 100, 99, 100]) == "flat"

    def test_insufficient_history(self):
        assert classify_trend([100, 110]) == "insufficient_history"

    def test_volatile(self):
        assert classify_trend([100, 200, 50, 300, 10, 400]) == "volatile"

    def test_empty(self):
        assert classify_trend([]) == "insufficient_history"


class TestComputeTrendFields:
    def test_with_enough_data(self):
        series = pd.Series([100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 150, 155])
        result = compute_trend_fields(series)
        assert result["trend_4w"] == "rising"
        assert result["trend_12w"] == "rising"
        assert result["pct_change_4w"] is not None
        assert result["pct_change_12w"] is not None

    def test_insufficient_data(self):
        series = pd.Series([100, 110])
        result = compute_trend_fields(series)
        assert result["trend_4w"] == "insufficient_history"
        assert result["pct_change_4w"] is None

    def test_empty_series(self):
        result = compute_trend_fields(pd.Series([], dtype=float))
        assert result["trend_4w"] == "insufficient_history"


# ══════════════════════════════════════════════════════════════════════════════
# ANOMALY DETECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectAnomaly:
    def test_click_drop_triggers(self):
        result = detect_anomaly("clicks", 50, 200, thresholds=DEFAULT_THRESHOLDS)
        assert result is not None
        assert result["severity"] in ("high", "medium")

    def test_small_drop_no_trigger(self):
        # 10% drop, only 5 absolute — below both thresholds
        result = detect_anomaly("clicks", 95, 100, thresholds=DEFAULT_THRESHOLDS)
        assert result is None

    def test_position_worsen_triggers(self):
        # Position worsened by 3 positions (above abs threshold of 2)
        result = detect_anomaly("avg_position", 15, 12, thresholds=DEFAULT_THRESHOLDS)
        assert result is not None

    def test_position_small_worsen_no_trigger(self):
        # Position worsened by 1 position (below abs threshold of 2)
        result = detect_anomaly("avg_position", 11, 10, thresholds=DEFAULT_THRESHOLDS)
        assert result is None

    def test_broken_link_spike_triggers(self):
        # 15 new broken links (above abs threshold of 10)
        result = detect_anomaly("broken_links", 15, 0, thresholds=DEFAULT_THRESHOLDS)
        assert result is not None

    def test_no_anomaly_returns_none(self):
        result = detect_anomaly("clicks", 100, 100, thresholds=DEFAULT_THRESHOLDS)
        assert result is None

    def test_zscore_upgrade_with_history(self):
        # Current is 3 std devs below mean — should upgrade to high confidence
        history = [100, 102, 98, 101, 99, 100, 103, 97]
        result = detect_anomaly("clicks", 50, 100, history=history, thresholds=DEFAULT_THRESHOLDS)
        assert result is not None
        assert result["confidence"] == "high"


class TestBuildAnomalyTable:
    def test_empty_signals(self):
        df = build_anomaly_table([], {})
        assert df.empty

    def test_with_signals(self):
        signals = [
            {
                "anomaly_id": "abc123",
                "metric": "clicks",
                "current_value": 50,
                "previous_value": 200,
                "pct_change": -0.75,
                "absolute_change": -150,
                "severity": "high",
                "confidence": "high",
                "direction": "drop",
            }
        ]
        df = build_anomaly_table(signals, {"clicks": "organic_visibility"})
        assert len(df) == 1
        assert df.iloc[0]["category"] == "organic_visibility"
        assert "evidence" in df.columns


# ══════════════════════════════════════════════════════════════════════════════
# CONTENT DECAY SCORING
# ══════════════════════════════════════════════════════════════════════════════

class TestScoreContentDecay:
    def test_declining_page_flagged(self):
        result = score_content_decay(
            page="https://www.cim.org/test-page/",
            current_clicks=50,
            previous_clicks=200,
            current_sessions=100,
            previous_sessions=300,
            current_impressions=2000,
            avg_position=12,
            ctr=0.025,
        )
        assert result is not None
        assert result["decay_score"] > 0
        assert result["recommendation"] in (
            "Refresh content", "Rewrite title/meta", "Add internal links",
            "Improve CTA", "Investigate ranking loss", "Monitor only",
        )

    def test_growing_page_not_flagged(self):
        result = score_content_decay(
            page="https://www.cim.org/growing-page/",
            current_clicks=200,
            previous_clicks=100,
            current_sessions=300,
            previous_sessions=200,
            current_impressions=5000,
            avg_position=5,
            ctr=0.04,
        )
        assert result is None

    def test_tiny_traffic_not_flagged(self):
        result = score_content_decay(
            page="https://www.cim.org/tiny-page/",
            current_clicks=2,
            previous_clicks=5,
            current_sessions=3,
            previous_sessions=8,
            current_impressions=10,  # below 50 threshold
            avg_position=25,
            ctr=0.02,
        )
        assert result is None

    def test_priority_page_gets_boost(self):
        result_normal = score_content_decay(
            page="https://www.cim.org/page/",
            current_clicks=50, previous_clicks=100,
            current_sessions=80, previous_sessions=150,
            current_impressions=500, avg_position=15, ctr=0.01,
            is_priority_page=False,
        )
        result_priority = score_content_decay(
            page="https://www.cim.org/page/",
            current_clicks=50, previous_clicks=100,
            current_sessions=80, previous_sessions=150,
            current_impressions=500, avg_position=15, ctr=0.01,
            is_priority_page=True,
        )
        assert result_priority["decay_score"] > result_normal["decay_score"]


# ══════════════════════════════════════════════════════════════════════════════
# PRIORITY SCORING
# ══════════════════════════════════════════════════════════════════════════════

class TestScoreActionPriority:
    def test_high_impact_high_urgency(self):
        score = score_action_priority(90, 90, 90, 90, 20)
        assert score > 80

    def test_low_impact_low_urgency(self):
        score = score_action_priority(10, 10, 10, 10, 80)
        assert score < 30

    def test_effort_penalty_applied(self):
        score_low_effort  = score_action_priority(70, 70, 70, 70, 20)
        score_high_effort = score_action_priority(70, 70, 70, 70, 80)
        assert score_low_effort > score_high_effort

    def test_output_clamped_0_100(self):
        score = score_action_priority(100, 100, 100, 100, 0)
        assert 0 <= score <= 100


class TestEffortLabelToScore:
    def test_low(self):
        assert effort_label_to_score("low") == 20

    def test_medium(self):
        assert effort_label_to_score("medium") == 50

    def test_high(self):
        assert effort_label_to_score("high") == 80

    def test_unknown(self):
        assert effort_label_to_score("unknown") == 50


# ══════════════════════════════════════════════════════════════════════════════
# ACTION QUEUE
# ══════════════════════════════════════════════════════════════════════════════

class TestMakeAction:
    def test_creates_action_with_priority_score(self):
        action = make_action(
            action="Fix broken links",
            category="Technical Health",
            source="Broken Link Report",
            evidence="15 broken links found",
            why_it_matters="Damages UX and crawl budget",
            estimated_impact="medium",
            effort="low",
            confidence="high",
            urgency="medium",
        )
        assert "priority_score" in action
        assert action["priority_score"] > 0
        assert action["action"] == "Fix broken links"
        assert action["category"] == "Technical Health"


class TestSortActionQueue:
    def test_sorted_by_priority_score(self):
        actions = [
            make_action("Low priority action", "Technical", "Test", "evidence", "why", "low", "high", "low", "low"),
            make_action("High priority action", "Business", "Test", "evidence", "why", "high", "low", "high", "high"),
            make_action("Medium priority action", "Content", "Test", "evidence", "why", "medium", "medium", "medium", "medium"),
        ]
        sorted_actions = sort_action_queue(actions)
        assert sorted_actions[0]["priority"] == 1
        assert sorted_actions[0]["priority_score"] >= sorted_actions[1]["priority_score"]
        assert sorted_actions[1]["priority_score"] >= sorted_actions[2]["priority_score"]


class TestDeduplicateActions:
    def test_removes_duplicates(self):
        actions = [
            make_action("Fix broken links", "Technical", "Source A", "ev1", "why", "medium"),
            make_action("Fix broken links", "Technical", "Source B", "ev2", "why", "medium"),
            make_action("Rewrite title", "Content", "Source C", "ev3", "why", "medium"),
        ]
        deduped = deduplicate_actions(actions)
        assert len(deduped) == 2

    def test_keeps_highest_priority(self):
        a1 = make_action("Fix broken links", "Technical", "A", "ev", "why", "low",  "high", "high", "high")
        a2 = make_action("Fix broken links", "Technical", "B", "ev", "why", "high", "low",  "low",  "low")
        deduped = deduplicate_actions([a1, a2])
        assert len(deduped) == 1
        assert deduped[0]["priority_score"] == max(a1["priority_score"], a2["priority_score"])


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

class TestConversionRate:
    def test_normal(self):
        assert compute_conversion_rate(10, 100) == pytest.approx(0.10)

    def test_zero_sessions(self):
        assert compute_conversion_rate(10, 0) is None

    def test_per_100(self):
        assert compute_conversions_per_100(10, 100) == pytest.approx(10.0)


class TestEstimateBusinessValue:
    def test_with_matching_events(self):
        conv_df = pd.DataFrame([
            {"event_name": "event_registration_click", "event_count": 5},
            {"event_name": "membership_signup_click",  "event_count": 2},
        ])
        config_df = pd.DataFrame([
            {"conversion_event": "event_registration_click", "business_value_proxy": 100},
            {"conversion_event": "membership_signup_click",  "business_value_proxy": 150},
        ])
        value = estimate_business_value(conv_df, config_df)
        assert value == pytest.approx(5 * 100 + 2 * 150)

    def test_empty_inputs(self):
        assert estimate_business_value(pd.DataFrame(), pd.DataFrame()) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# DATA QUALITY WARNINGS
# ══════════════════════════════════════════════════════════════════════════════

class TestMakeWarning:
    def test_creates_warning_dict(self):
        w = make_warning("GA4", "No data", "high", "Missing metrics", "Fix config")
        assert w["source"] == "GA4"
        assert w["severity"] == "high"
        assert "suggested_fix" in w


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
