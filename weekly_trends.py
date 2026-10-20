"""Comparable, evidence-labelled week-over-week signals for combined reports."""

from __future__ import annotations

import html
import math

import pandas as pd


TREND_COLUMNS = ["metric", "source", "current", "previous", "change", "change_pct", "unit", "scope"]
HISTORY_COLUMNS = ["period_id", "period_start", "period_end", "metric", "source", "value", "unit", "scope"]


def update_trend_history(previous: pd.DataFrame, trends: pd.DataFrame, start, end) -> pd.DataFrame:
    """Retain one comparable KPI snapshot per metric and completed week."""
    period_id = f"{start}_{end}"
    old = previous.reindex(columns=HISTORY_COLUMNS) if not previous.empty else pd.DataFrame(columns=HISTORY_COLUMNS)
    current = trends.rename(columns={"current": "value"}).reindex(columns=["metric", "source", "value", "unit", "scope"]).copy()
    current.insert(0, "period_end", str(end))
    current.insert(0, "period_start", str(start))
    current.insert(0, "period_id", period_id)
    combined = pd.concat([old, current], ignore_index=True)
    return combined.drop_duplicates(["period_id", "metric", "source"], keep="last").sort_values(["metric", "period_end"]).reset_index(drop=True)


def history_signals(history: pd.DataFrame) -> list[str]:
    """Use four distinct weeks for slope and eight earlier weeks for a baseline."""
    signals = []
    for metric, group in history.groupby("metric") if not history.empty else []:
        ordered = group.sort_values("period_end").drop_duplicates("period_id", keep="last")
        values = pd.to_numeric(ordered["value"], errors="coerce").dropna()
        if len(values) >= 4:
            latest = values.tail(4).tolist()
            slope = (latest[-1] - latest[0]) / 3
            unit = str(ordered.iloc[-1].get("unit", "count"))
            slope_label = f"{slope * 100:+.2f} percentage points" if unit == "rate" else f"{slope:+,.1f} score points" if unit == "score" else f"{slope:+,.1f}"
            signals.append(f"{metric}: four-week slope {slope_label} per week.")
        if len(values) >= 9:
            baseline = values.iloc[-9:-1]
            spread = baseline.std(ddof=1)
            if spread > 0 and abs(values.iloc[-1] - baseline.mean()) >= 2 * spread:
                signals.append(f"{metric}: latest value is at least two standard deviations from the preceding eight-week baseline.")
    return signals


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def build_weekly_trends(data: dict) -> tuple[pd.DataFrame, list[str]]:
    """Use paired periods only; never fill missing previous values with zero."""
    rows = []

    def add(metric, source, current, previous, unit="count", scope="Comparable weekly periods"):
        current, previous = _number(current), _number(previous)
        if current is None or previous is None:
            return
        change = current - previous
        rows.append({"metric": metric, "source": source, "current": current,
                     "previous": previous, "change": change,
                     "change_pct": change / previous if previous else None,
                     "unit": unit, "scope": scope})

    ga4 = data.get("ga4_summary", pd.DataFrame())
    if {"metric", "current", "previous"}.issubset(ga4.columns):
        for metric, label in (("sessions", "GA4 sessions"), ("activeUsers", "GA4 active users")):
            matches = ga4[ga4["metric"] == metric]
            if len(matches) == 1:
                row = matches.iloc[0]
                add(label, "GA4", row["current"], row["previous"])

    gsc = data.get("gsc_comparison", pd.DataFrame())
    required = {"clicks_current", "clicks_previous", "impressions_current", "impressions_previous"}
    if not gsc.empty and required.issubset(gsc.columns):
        values = gsc[list(required)].apply(pd.to_numeric, errors="coerce")
        if values.notna().all().all():
            totals = values.sum()
            scope = f"Exported query set ({len(gsc):,} rows); not whole-site GSC totals"
            add("GSC query clicks", "GSC", totals["clicks_current"], totals["clicks_previous"], scope=scope)
            add("GSC query impressions", "GSC", totals["impressions_current"], totals["impressions_previous"], scope=scope)
            if totals["impressions_current"] > 0 and totals["impressions_previous"] > 0:
                add("GSC query CTR", "GSC", totals["clicks_current"] / totals["impressions_current"],
                    totals["clicks_previous"] / totals["impressions_previous"], "rate", scope)

    conversions = data.get("conv_summary", pd.DataFrame())
    if not conversions.empty and {"current_count", "previous_count"}.issubset(conversions.columns):
        counts = conversions[["current_count", "previous_count"]].apply(pd.to_numeric, errors="coerce")
        if counts.notna().all().all():
            add("Tracked conversion events", "GA4 events", counts["current_count"].sum(),
                counts["previous_count"].sum(), scope="Configured event counts; not unique conversions")

    speed = data.get("speed", pd.DataFrame())
    if not speed.empty and {"strategy", "performance_score", "performance_score_previous"}.issubset(speed.columns):
        mobile = speed.loc[speed["strategy"] == "mobile", ["performance_score", "performance_score_previous"]]
        paired = mobile.apply(pd.to_numeric, errors="coerce").dropna()
        if not paired.empty:
            add("Mobile performance score", "PageSpeed", paired["performance_score"].mean(),
                paired["performance_score_previous"].mean(), "score",
                f"Matched mobile pages ({len(paired):,}); lab score")

    trends = pd.DataFrame(rows, columns=TREND_COLUMNS)
    insights = []
    by_name = {row["metric"]: row for row in rows}
    clicks, impressions, ctr = (by_name.get(name) for name in
                                ("GSC query clicks", "GSC query impressions", "GSC query CTR"))
    if clicks and impressions and ctr and impressions["change"] > 0 and clicks["change"] < 0:
        insights.append("Exported queries gained impressions while clicks fell; inspect high-impression queries with falling CTR.")
    sessions, events = by_name.get("GA4 sessions"), by_name.get("Tracked conversion events")
    if sessions and events and sessions["change"] < 0 and events["change"] > 0:
        insights.append("GA4 sessions fell while tracked event counts rose; inspect event mix and landing pages before attributing the change.")
    if sessions and clicks and sessions["previous"] > 0 and clicks["previous"] > 0:
        session_change = sessions["change"] / sessions["previous"]
        click_change = clicks["change"] / clicks["previous"]
        if session_change < -0.3 and click_change > session_change + 0.15:
            insights.append("GA4 sessions fell substantially faster than exported-query clicks; inspect channel mix and measurement coverage. These sources measure different traffic scopes.")
    mobile = by_name.get("Mobile performance score")
    if mobile and mobile["change"] < -5:
        insights.append("Mean mobile lab score fell by more than five points across matched pages; review page-level regressions.")
    speed = data.get("speed", pd.DataFrame())
    if not speed.empty and {"strategy", "performance_score"}.issubset(speed.columns):
        mobile_rows = speed[speed["strategy"] == "mobile"]
        missing = int(pd.to_numeric(mobile_rows["performance_score"], errors="coerce").isna().sum())
        if missing:
            insights.append(f"{missing} of {len(mobile_rows)} mobile pages lack a current score; the matched-page trend excludes them.")
    keywords = data.get("kw_comparison", pd.DataFrame())
    if not keywords.empty and "position_change" in keywords.columns:
        changes = pd.to_numeric(keywords["position_change"], errors="coerce").dropna()
        if not changes.empty:
            improved, declined = int((changes < 0).sum()), int((changes > 0).sum())
            insights.append(f"Among {len(changes):,} tracked keywords, {improved:,} improved and {declined:,} declined in position; prioritize movers with material impressions.")
    if not insights:
        insights.append("Review the paired metrics below for the largest weekly changes; no cross-report divergence rule fired.")
    return trends, insights


def render_weekly_trends(trends: pd.DataFrame, insights: list[str], history: pd.DataFrame | None = None) -> str:
    if trends.empty:
        return "<p>No paired weekly metrics are available. Check source artifacts and reporting periods.</p>"

    def fmt(value, unit):
        if unit == "rate":
            return f"{value:.2%}"
        if unit == "score":
            return f"{value:.1f}"
        return f"{value:,.0f}"

    lines = []
    for row in trends.to_dict("records"):
        unit = row["unit"]
        delta = row["change"] * 100 if unit == "rate" else row["change"]
        delta_label = f"{delta:+.2f} pp" if unit == "rate" else f"{delta:+,.1f}" if unit == "score" else f"{delta:+,.0f}"
        pct = row["change_pct"]
        if pct is not None and pd.notna(pct) and unit != "rate":
            delta_label += f" ({pct:+.1%})"
        lines.append("<tr>" + "".join(f"<td style='padding:8px;border-bottom:1px solid #ddd'>{html.escape(str(x))}</td>"
            for x in (row["metric"], row["source"], fmt(row["current"], unit), fmt(row["previous"], unit), delta_label,
                      row["scope"])) + "</tr>")
    historical = history_signals(history) if history is not None else []
    bullets = "".join(f"<li>{html.escape(item)}</li>" for item in insights + historical)
    return ("<p>Paired current and previous reporting weeks. Each row names its measurement scope.</p>"
            f"<ul style='margin:12px 0 18px;padding-left:22px'>{bullets}</ul>"
            "<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;font-size:12px'>"
            "<thead><tr><th>Metric</th><th>Source</th><th>Current</th><th>Previous</th><th>Change</th><th>Scope</th></tr></thead>"
            f"<tbody>{''.join(lines)}</tbody></table></div>")
