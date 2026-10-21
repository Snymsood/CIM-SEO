import json
from pathlib import Path

import pandas as pd

from site_portfolio_trends import build_portfolio_trends, render_portfolio_trends


def test_site_trends_keep_properties_and_period_types_separate(tmp_path: Path):
    (tmp_path / "report_manifest.json").write_text(json.dumps({
        "period_start": "2026-10-12", "period_end": "2026-10-18",
    }), encoding="utf-8")
    pd.DataFrame([
        {"site_id": "main", "site_name": "CIM main site"},
        {"site_id": "cimconnect", "site_name": "CIM CONNECT"},
    ]).to_csv(tmp_path / "site_overview.csv", index=False)
    pd.DataFrame([
        {"site_id": "main", "host": "www.cim.org", "period_end": "2026-10-18",
         "previous_period_end": "2026-10-11", "sessions": 120, "previous_sessions": 100,
         "active_users": 80, "previous_active_users": 70},
        {"site_id": "cimconnect", "host": "cimconnect.ca", "period_end": "2026-10-18",
         "previous_period_end": "2026-10-11", "sessions": 60, "previous_sessions": 50,
         "active_users": 40, "previous_active_users": 35},
    ]).to_csv(tmp_path / "site_ga4_weekly.csv", index=False)
    pd.DataFrame([
        {"site_id": "cimconnect", "metric": "largest_contentful_paint",
         "form_factor": "ALL", "period_end": end, "p75_raw": value}
        for end, value in [
            ("2026-09-20", 2500), ("2026-09-27", 2450),
            ("2026-10-04", 2400), ("2026-10-11", 2350),
            ("2026-10-18", 2300),
        ]
    ]).to_csv(tmp_path / "site_crux_history.csv", index=False)

    trends = build_portfolio_trends(tmp_path, ("2026-10-12", "2026-10-18"))

    assert len(trends) == 5
    main_sessions = trends.loc[(trends.site_id == "main") & (trends.metric == "GA4 sessions")].iloc[0]
    connect_sessions = trends.loc[(trends.site_id == "cimconnect") & (trends.metric == "GA4 sessions")].iloc[0]
    assert (main_sessions.current, main_sessions.previous) == (120, 100)
    assert (connect_sessions.current, connect_sessions.previous) == (60, 50)
    crux = trends.loc[trends.source == "CrUX"].iloc[0]
    assert (crux.site_id, crux.form_factor, crux.current, crux.previous) == ("cimconnect", "ALL", 2300, 2500)
    assert "nonoverlapping 28-day windows" in crux.scope
    assert "Four-site portfolio trends" in render_portfolio_trends(trends)
    assert build_portfolio_trends(tmp_path, ("2026-10-19", "2026-10-25")).empty
