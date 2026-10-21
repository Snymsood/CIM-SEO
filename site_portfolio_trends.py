"""Comparable, site-scoped signals from the weekly source portfolio."""

from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

import pandas as pd


COLUMNS = ["site_id", "site_name", "metric", "source", "current", "previous",
           "change", "change_pct", "unit", "current_period_end", "previous_period_end",
           "form_factor", "scope"]
CRUX_METRICS = {
    "largest_contentful_paint": ("LCP p75", "ms"),
    "interaction_to_next_paint": ("INP p75", "ms"),
    "cumulative_layout_shift": ("CLS p75", "score"),
}


def _read(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def build_portfolio_trends(root: Path, expected_period: tuple[str, str] | None = None) -> pd.DataFrame:
    manifest_path = root / "report_manifest.json"
    if expected_period:
        if not manifest_path.is_file():
            return pd.DataFrame(columns=COLUMNS)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return pd.DataFrame(columns=COLUMNS)
        if (manifest.get("period_start"), manifest.get("period_end")) != expected_period:
            return pd.DataFrame(columns=COLUMNS)

    overview = _read(root / "site_overview.csv")
    ga4 = _read(root / "site_ga4_weekly.csv")
    crux = _read(root / "site_crux_history.csv")
    names = dict(zip(overview.get("site_id", []), overview.get("site_name", [])))
    rows: list[dict] = []

    if {"site_id", "period_end", "previous_period_end"}.issubset(ga4.columns):
        for _, record in ga4.iterrows():
            site_id = str(record["site_id"])
            for current_key, previous_key, label in (
                ("sessions", "previous_sessions", "GA4 sessions"),
                ("active_users", "previous_active_users", "GA4 active users"),
            ):
                current = pd.to_numeric(record.get(current_key), errors="coerce")
                previous = pd.to_numeric(record.get(previous_key), errors="coerce")
                if pd.isna(current) or pd.isna(previous):
                    continue
                rows.append({"site_id": site_id, "site_name": names.get(site_id, site_id),
                             "metric": label, "source": "GA4", "current": current,
                             "previous": previous, "change": current - previous,
                             "change_pct": (current - previous) / previous if previous else None,
                             "unit": "count", "current_period_end": str(record["period_end"]),
                             "previous_period_end": str(record["previous_period_end"]),
                             "form_factor": "", "scope": f"{record.get('host', '')}; distinct Monday–Sunday weeks"})

    needed = {"site_id", "metric", "form_factor", "period_end", "p75_raw"}
    if needed.issubset(crux.columns):
        for (site_id, metric, factor), group in crux.groupby(["site_id", "metric", "form_factor"]):
            if metric not in CRUX_METRICS:
                continue
            ordered = group.sort_values("period_end").drop_duplicates("period_end", keep="last")
            if len(ordered) < 5:
                continue
            current_row, previous_row = ordered.iloc[-1], ordered.iloc[-5]
            current = pd.to_numeric(current_row["p75_raw"], errors="coerce")
            previous = pd.to_numeric(previous_row["p75_raw"], errors="coerce")
            if pd.isna(current) or pd.isna(previous):
                continue
            try:
                gap = (date.fromisoformat(str(current_row["period_end"])) -
                       date.fromisoformat(str(previous_row["period_end"]))).days
            except ValueError:
                continue
            if gap < 28:
                continue
            label, unit = CRUX_METRICS[metric]
            rows.append({"site_id": site_id, "site_name": names.get(site_id, site_id),
                         "metric": label, "source": "CrUX", "current": current,
                         "previous": previous, "change": current - previous,
                         "change_pct": (current - previous) / previous if previous else None,
                         "unit": unit, "current_period_end": str(current_row["period_end"]),
                         "previous_period_end": str(previous_row["period_end"]),
                         "form_factor": factor,
                         "scope": f"Origin {factor}; nonoverlapping 28-day windows; lower is better"})

    return pd.DataFrame(rows, columns=COLUMNS)


def render_portfolio_trends(trends: pd.DataFrame) -> str:
    heading = "<h3>Four-site portfolio trends</h3>"
    if trends.empty:
        return heading + "<p>No validated, comparable site portfolio data is available for this week.</p>"

    def value(number, unit):
        return f"{number:,.3f}" if unit == "score" else f"{number:,.0f}"

    body = []
    for _, row in trends.iterrows():
        unit = row["unit"]
        current = value(row["current"], unit)
        previous = value(row["previous"], unit)
        change = f"{row['change']:+,.3f}" if unit == "score" else f"{row['change']:+,.0f}"
        body.append("<tr>" + "".join(
            f"<td>{html.escape(str(item))}</td>" for item in
            (row["site_name"], row["metric"], current, previous, change,
             row["current_period_end"], row["previous_period_end"], row["form_factor"])) + "</tr>")
    return (heading +
            "<p>GA4 compares distinct weeks by site. CrUX compares origin p75 values from "
            "28-day windows four weeks apart; lower LCP, INP, and CLS are better. "
            "Device groups and site populations remain separate. CrUX metrics without "
            "five usable history points are omitted until enough data exists.</p>"
            "<div style='overflow:auto'><table><thead><tr><th>Site</th><th>Metric</th>"
            "<th>Current</th><th>Prior</th><th>Change</th><th>Current ends</th>"
            "<th>Prior ends</th><th>Device</th></tr></thead><tbody>" +
            "".join(body) + "</tbody></table></div>")
