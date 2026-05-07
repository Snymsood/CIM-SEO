"""
seo_intelligence_utils.py
CIM SEO — Reusable intelligence utilities for the weekly SEO intelligence layer.

Contains deterministic scoring, anomaly detection, trend analysis,
content decay scoring, and action queue helpers.
No live API calls — all functions operate on DataFrames.
"""

from __future__ import annotations

import math
import uuid
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS — default thresholds (overridden by seo_intelligence_thresholds.csv)
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_THRESHOLDS = {
    "clicks":            {"pct": 0.25, "abs": 50,    "dir": "drop"},
    "impressions":       {"pct": 0.30, "abs": 200,   "dir": "drop"},
    "ctr":               {"pct": 0.20, "abs": 0.005, "dir": "drop"},
    "avg_position":      {"pct": 0.0,  "abs": 2.0,   "dir": "worsen"},
    "sessions":          {"pct": 0.20, "abs": 100,   "dir": "drop"},
    "conversions":       {"pct": 0.20, "abs": 5,     "dir": "drop"},
    "conversion_rate":   {"pct": 0.15, "abs": 0.005, "dir": "drop"},
    "mobile_score":      {"pct": 0.0,  "abs": 10,    "dir": "drop"},
    "cwv_pass_rate":     {"pct": 0.15, "abs": 0.1,   "dir": "drop"},
    "broken_links":      {"pct": 0.0,  "abs": 10,    "dir": "spike"},
    "keyword_visibility":{"pct": 0.20, "abs": 3,     "dir": "drop"},
}


# ══════════════════════════════════════════════════════════════════════════════
# BASIC MATH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def safe_pct_change(current: float, previous: float) -> Optional[float]:
    """Return (current - previous) / previous, or None if previous == 0."""
    try:
        c, p = float(current), float(previous)
        if p == 0:
            return None
        return (c - p) / p
    except (TypeError, ValueError):
        return None


def safe_float(val, default: float = 0.0) -> float:
    try:
        v = float(val)
        return default if math.isnan(v) else v
    except (TypeError, ValueError):
        return default


def clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


# ══════════════════════════════════════════════════════════════════════════════
# TREND CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def classify_trend(values: list[float]) -> str:
    """
    Classify a time series as: rising / falling / flat / volatile / insufficient_history.
    Uses simple linear slope normalised by mean.
    """
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if len(clean) < 3:
        return "insufficient_history"
    mean_val = np.mean(clean)
    if mean_val == 0:
        return "flat"
    x = np.arange(len(clean), dtype=float)
    slope = np.polyfit(x, clean, 1)[0]
    normalised_slope = slope / mean_val  # slope per period as fraction of mean
    std_val = np.std(clean)
    cv = std_val / mean_val if mean_val != 0 else 0  # coefficient of variation
    if cv > 0.40:
        return "volatile"
    if normalised_slope > 0.03:
        return "rising"
    if normalised_slope < -0.03:
        return "falling"
    return "flat"


def compute_trend_fields(series: pd.Series) -> dict:
    """
    Given a time-ordered Series of numeric values, return trend metadata.
    Expects most-recent value last.
    """
    vals = [safe_float(v) for v in series.dropna().tolist()]
    result = {
        "trend_4w":  "insufficient_history",
        "trend_8w":  "insufficient_history",
        "trend_12w": "insufficient_history",
        "pct_change_4w":  None,
        "pct_change_12w": None,
        "slope_12w": None,
        "historical_baseline": None,
        "current_vs_baseline_pct": None,
    }
    if not vals:
        return result
    current = vals[-1]
    if len(vals) >= 4:
        result["trend_4w"] = classify_trend(vals[-4:])
        result["pct_change_4w"] = safe_pct_change(current, vals[-4])
    if len(vals) >= 8:
        result["trend_8w"] = classify_trend(vals[-8:])
    if len(vals) >= 12:
        result["trend_12w"] = classify_trend(vals[-12:])
        result["pct_change_12w"] = safe_pct_change(current, vals[-12])
        x = np.arange(12, dtype=float)
        result["slope_12w"] = float(np.polyfit(x, vals[-12:], 1)[0])
    if len(vals) >= 4:
        result["historical_baseline"] = float(np.mean(vals[:-1]))
        result["current_vs_baseline_pct"] = safe_pct_change(current, result["historical_baseline"])
    return result


# ══════════════════════════════════════════════════════════════════════════════
# ANOMALY DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def load_thresholds(path: str = "seo_intelligence_thresholds.csv") -> dict:
    """Load thresholds from CSV, fall back to defaults on any error."""
    try:
        df = pd.read_csv(path)
        thresholds = {}
        for _, row in df.iterrows():
            thresholds[row["metric"]] = {
                "pct": safe_float(row.get("pct_threshold", 0)),
                "abs": safe_float(row.get("absolute_threshold", 0)),
                "dir": str(row.get("direction", "drop")),
            }
        return thresholds
    except Exception:
        return DEFAULT_THRESHOLDS


def detect_anomaly(
    metric: str,
    current: float,
    previous: float,
    history: Optional[list[float]] = None,
    thresholds: Optional[dict] = None,
) -> Optional[dict]:
    """
    Return an anomaly dict if the metric change is anomalous, else None.
    Uses relative + absolute thresholds. Optionally uses z-score if 8+ history points.
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    cfg = thresholds.get(metric, {"pct": 0.25, "abs": 0, "dir": "drop"})
    pct_thresh = cfg["pct"]
    abs_thresh = cfg["abs"]
    direction  = cfg["dir"]

    pct_chg = safe_pct_change(current, previous)
    abs_chg = current - previous

    is_anomaly = False
    confidence = "low"

    if direction in ("drop", "worsen"):
        # For position: "worsen" means current > previous (higher number = worse)
        if direction == "worsen":
            triggered = abs_chg >= abs_thresh
        else:
            triggered = (
                pct_chg is not None and pct_chg <= -pct_thresh
                and abs(abs_chg) >= abs_thresh
            )
        if triggered:
            is_anomaly = True
            confidence = "medium"
    elif direction == "spike":
        triggered = abs_chg >= abs_thresh
        if triggered:
            is_anomaly = True
            confidence = "medium"

    # Z-score upgrade if enough history
    if history and len(history) >= 8:
        arr = np.array([safe_float(v) for v in history])
        mean_h, std_h = arr.mean(), arr.std()
        if std_h > 0:
            z = (current - mean_h) / std_h
            if direction in ("drop", "worsen") and z <= -2.0:
                is_anomaly = True
                confidence = "high"
            elif direction == "spike" and z >= 2.0:
                is_anomaly = True
                confidence = "high"

    if not is_anomaly:
        return None

    severity = _anomaly_severity(metric, pct_chg, abs_chg, direction)
    return {
        "anomaly_id":      str(uuid.uuid4())[:8],
        "metric":          metric,
        "current_value":   current,
        "previous_value":  previous,
        "pct_change":      pct_chg,
        "absolute_change": abs_chg,
        "severity":        severity,
        "confidence":      confidence,
        "direction":       direction,
    }


def _anomaly_severity(metric: str, pct_chg: Optional[float], abs_chg: float, direction: str) -> str:
    if direction == "worsen":
        if abs_chg >= 5:
            return "high"
        if abs_chg >= 2:
            return "medium"
        return "low"
    if pct_chg is None:
        return "medium"
    magnitude = abs(pct_chg)
    if magnitude >= 0.40:
        return "high"
    if magnitude >= 0.20:
        return "medium"
    return "low"


def build_anomaly_table(signals: list[dict], category_map: dict) -> pd.DataFrame:
    """Convert a list of anomaly dicts into a DataFrame with category column."""
    if not signals:
        return pd.DataFrame(columns=[
            "anomaly_id", "category", "metric", "entity",
            "current_value", "previous_value", "pct_change",
            "absolute_change", "severity", "confidence", "evidence",
        ])
    rows = []
    for s in signals:
        s["category"] = category_map.get(s["metric"], "general")
        s.setdefault("entity", "site-wide")
        pct_str = f"{s['pct_change']:+.1%}" if s["pct_change"] is not None else "n/a"
        s["evidence"] = (
            f"{s['metric']}: {s['current_value']:,.1f} vs {s['previous_value']:,.1f} "
            f"({pct_str})"
        )
        rows.append(s)
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# CONTENT DECAY SCORING
# ══════════════════════════════════════════════════════════════════════════════

def score_content_decay(
    page: str,
    current_clicks: float,
    previous_clicks: float,
    current_sessions: float,
    previous_sessions: float,
    current_impressions: float,
    avg_position: float,
    ctr: float,
    current_conversions: float = 0,
    previous_conversions: float = 0,
    category: str = "Other",
    is_priority_page: bool = False,
) -> Optional[dict]:
    """
    Score a page for content decay. Returns None if traffic is too small to flag.
    Minimum threshold: 50 impressions or 20 sessions.
    """
    if current_impressions < 50 and current_sessions < 20:
        return None

    click_pct   = safe_pct_change(current_clicks, previous_clicks) or 0.0
    session_pct = safe_pct_change(current_sessions, previous_sessions) or 0.0
    conv_pct    = safe_pct_change(current_conversions, previous_conversions) or 0.0

    # Only flag pages that are actually declining
    if click_pct >= 0 and session_pct >= 0:
        return None

    # Component scores (0-100, higher = more decayed)
    click_score   = clamp(abs(click_pct) * 100) if click_pct < 0 else 0
    session_score = clamp(abs(session_pct) * 100) if session_pct < 0 else 0
    # Impression opportunity: high impressions + low CTR = underperforming
    impr_opp_score = clamp((1 - min(ctr / 0.05, 1)) * 50) if current_impressions >= 100 else 0
    # Position decline: position > 10 is bad
    pos_score = clamp((avg_position - 10) * 5) if avg_position > 10 else 0
    # CTR decline
    ctr_score = clamp((1 - min(ctr / 0.03, 1)) * 40)
    # Conversion decline
    conv_score = clamp(abs(conv_pct) * 60) if conv_pct < 0 else 0
    # Priority boost
    priority_boost = 15 if is_priority_page else 0

    decay_score = clamp(
        click_score   * 0.30
        + session_score * 0.25
        + impr_opp_score * 0.15
        + pos_score     * 0.10
        + ctr_score     * 0.10
        + conv_score    * 0.10
        + priority_boost
    )

    recommendation = _decay_recommendation(
        click_pct, session_pct, avg_position, ctr, current_impressions, conv_pct
    )

    return {
        "page":                    page,
        "category":                category,
        "current_clicks":          current_clicks,
        "previous_clicks":         previous_clicks,
        "pct_change_clicks":       click_pct,
        "current_sessions":        current_sessions,
        "previous_sessions":       previous_sessions,
        "pct_change_sessions":     session_pct,
        "current_conversions":     current_conversions,
        "pct_change_conversions":  conv_pct,
        "avg_position":            avg_position,
        "ctr":                     ctr,
        "current_impressions":     current_impressions,
        "decay_score":             round(decay_score, 1),
        "recommendation":          recommendation,
        "is_priority_page":        is_priority_page,
    }


def _decay_recommendation(
    click_pct: float,
    session_pct: float,
    avg_position: float,
    ctr: float,
    impressions: float,
    conv_pct: float,
) -> str:
    if avg_position > 20:
        return "Investigate ranking loss"
    if ctr < 0.01 and impressions >= 200:
        return "Rewrite title/meta"
    if click_pct < -0.40:
        return "Refresh content"
    if conv_pct < -0.30:
        return "Improve CTA"
    if avg_position > 10 and ctr < 0.03:
        return "Rewrite title/meta"
    if click_pct < -0.20:
        return "Refresh content"
    if session_pct < -0.20:
        return "Add internal links"
    return "Monitor only"


# ══════════════════════════════════════════════════════════════════════════════
# PRIORITY SCORING
# ══════════════════════════════════════════════════════════════════════════════

def score_action_priority(
    impact_score: float,
    urgency_score: float,
    confidence_score: float,
    business_value_score: float,
    effort_score: float,
) -> float:
    """
    Compute a 0-100 priority score.
    impact_score, urgency_score, confidence_score, business_value_score, effort_score: all 0-100.
    Higher effort = lower priority (penalty).
    """
    raw = (
        impact_score        * 0.40
        + urgency_score     * 0.25
        + confidence_score  * 0.20
        + business_value_score * 0.15
        - effort_score      * 0.10  # effort penalty
    )
    return round(clamp(raw), 1)


def effort_label_to_score(effort: str) -> float:
    """Convert effort label to numeric score (higher = more effort = lower priority)."""
    return {"low": 20, "medium": 50, "high": 80}.get(effort.lower(), 50)


def severity_to_urgency(severity: str) -> float:
    return {"high": 85, "medium": 55, "low": 25}.get(severity.lower(), 40)


def confidence_label_to_score(confidence: str) -> float:
    return {"high": 90, "medium": 60, "low": 30}.get(confidence.lower(), 50)


# ══════════════════════════════════════════════════════════════════════════════
# ACTION QUEUE ITEM BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def make_action(
    action: str,
    category: str,
    source: str,
    evidence: str,
    why_it_matters: str,
    estimated_impact: str,
    effort: str = "medium",
    confidence: str = "medium",
    urgency: str = "medium",
    business_value: float = 50.0,
    owner: str = "SEO Team",
    status: str = "Open",
) -> dict:
    """Create a single action queue item with a computed priority score."""
    effort_score    = effort_label_to_score(effort)
    urgency_score   = severity_to_urgency(urgency)
    conf_score      = confidence_label_to_score(confidence)
    impact_score    = {"high": 80, "medium": 50, "low": 25}.get(estimated_impact.lower(), 50) \
                      if isinstance(estimated_impact, str) else clamp(float(estimated_impact))
    priority_score  = score_action_priority(
        impact_score, urgency_score, conf_score, business_value, effort_score
    )
    return {
        "priority_score":   priority_score,
        "action":           action,
        "category":         category,
        "source":           source,
        "evidence":         evidence,
        "why_it_matters":   why_it_matters,
        "estimated_impact": estimated_impact,
        "effort":           effort,
        "confidence":       confidence,
        "owner":            owner,
        "status":           status,
    }


def sort_action_queue(actions: list[dict]) -> list[dict]:
    """Sort actions by priority_score descending, assign rank."""
    sorted_actions = sorted(actions, key=lambda x: x.get("priority_score", 0), reverse=True)
    for i, a in enumerate(sorted_actions, 1):
        a["priority"] = i
    return sorted_actions


# ══════════════════════════════════════════════════════════════════════════════
# CONVERSION RATE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def compute_conversion_rate(conversions: float, sessions: float) -> Optional[float]:
    if sessions <= 0:
        return None
    return conversions / sessions


def compute_conversions_per_100(conversions: float, sessions: float) -> Optional[float]:
    rate = compute_conversion_rate(conversions, sessions)
    return rate * 100 if rate is not None else None


def estimate_business_value(conversions_df: pd.DataFrame, config_df: pd.DataFrame) -> float:
    """
    Multiply conversion counts by business_value_proxy from config.
    Returns total estimated value.
    """
    if conversions_df.empty or config_df.empty:
        return 0.0
    total = 0.0
    value_map = dict(zip(
        config_df["conversion_event"].str.lower(),
        pd.to_numeric(config_df["business_value_proxy"], errors="coerce").fillna(0)
    ))
    for _, row in conversions_df.iterrows():
        event = str(row.get("event_name", "")).lower()
        count = safe_float(row.get("event_count", 0))
        total += count * value_map.get(event, 0)
    return round(total, 2)


# ══════════════════════════════════════════════════════════════════════════════
# DATA QUALITY WARNINGS
# ══════════════════════════════════════════════════════════════════════════════

def make_warning(source: str, issue: str, severity: str, effect: str, suggested_fix: str) -> dict:
    return {
        "source":        source,
        "issue":         issue,
        "severity":      severity,
        "effect":        effect,
        "suggested_fix": suggested_fix,
    }


def check_csv_available(path: str, source_name: str, effect: str) -> Optional[dict]:
    """Return a warning dict if the CSV file is missing or empty."""
    import os
    if not os.path.exists(path):
        return make_warning(
            source_name,
            f"CSV file not found: {path}",
            "medium",
            effect,
            f"Ensure {source_name} pipeline ran successfully before intelligence layer.",
        )
    try:
        df = pd.read_csv(path)
        if df.empty:
            return make_warning(
                source_name,
                f"CSV file is empty: {path}",
                "medium",
                effect,
                f"Check {source_name} pipeline for data fetch errors.",
            )
    except Exception as e:
        return make_warning(
            source_name,
            f"CSV file unreadable: {path} — {e}",
            "high",
            effect,
            f"Fix CSV format in {source_name} pipeline.",
        )
    return None


# ══════════════════════════════════════════════════════════════════════════════
# AI PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_action_plan_prompt(
    action_queue: list[dict],
    anomalies: list[dict],
    kpi_summary: dict,
    date_range: str,
    max_actions: int = 8,
) -> str:
    """
    Build a structured prompt for the AI action plan.
    The prompt instructs the model to be grounded in supplied evidence only.
    """
    top_actions = action_queue[:max_actions]
    actions_csv = "\n".join(
        f"- [{a.get('category','?')}] {a.get('action','?')} | Evidence: {a.get('evidence','?')} | Impact: {a.get('estimated_impact','?')} | Effort: {a.get('effort','?')}"
        for a in top_actions
    )
    anomaly_csv = "\n".join(
        f"- {a.get('metric','?')}: {a.get('evidence','?')} (severity: {a.get('severity','?')})"
        for a in anomalies[:5]
    ) or "None detected."

    kpi_lines = "\n".join(
        f"- {k}: {v}" for k, v in kpi_summary.items()
    )

    return f"""You are a senior SEO analyst writing a weekly action plan for the CIM digital team.

STRICT RULES:
- Only use the data supplied below. Do not invent metrics, pages, or events.
- Each recommended action must cite specific evidence from the data.
- Separate facts from interpretation. Use "data suggests" not "data proves".
- If evidence is incomplete, say so and recommend investigation rather than action.
- Do not give generic SEO advice. Every point must be grounded in the supplied numbers.
- Prioritise by business impact and urgency.
- Output format: numbered list of actions, each with: Action | Why | Evidence | Expected Impact | Effort | Urgency.
- Maximum 8 actions. Under 400 words total.

REPORTING PERIOD: {date_range}

KPI SUMMARY:
{kpi_lines}

ANOMALIES DETECTED:
{anomaly_csv}

PRIORITISED ACTION QUEUE (deterministic):
{actions_csv}

Write the weekly SEO action plan now:"""


# ══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION
# ══════════════════════════════════════════════════════════════════════════════

def deduplicate_actions(actions: list[dict], key_fields: tuple = ("action", "category")) -> list[dict]:
    """Remove duplicate actions based on key fields, keeping highest priority_score."""
    seen: dict[tuple, dict] = {}
    for a in actions:
        key = tuple(str(a.get(f, "")).lower()[:60] for f in key_fields)
        if key not in seen or a.get("priority_score", 0) > seen[key].get("priority_score", 0):
            seen[key] = a
    return list(seen.values())
