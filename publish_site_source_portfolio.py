#!/usr/bin/env python3
"""Publish the four-site report to its dedicated Monday item."""

from __future__ import annotations

import argparse
import csv
import html
import os
from pathlib import Path

from html_report_utils import upload_html_to_monday


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def summary_body(root: Path) -> str:
    overview = _read_csv(root / "site_overview.csv")
    status = _read_csv(root / "site_source_status.csv")
    ga4 = _read_csv(root / "site_ga4_weekly.csv") if (root / "site_ga4_weekly.csv").exists() else []
    period = f"{ga4[0]['period_start']} to {ga4[0]['period_end']}" if ga4 else "latest completed week"
    source_ok = sum(row["status"] == "ok" for row in status)
    lines = []
    for site in overview:
        sessions = site.get("ga4_sessions", "")
        label = html.escape(site["site_name"])
        count = f"{int(sessions):,} sessions" if sessions.isdigit() else "GA4 unavailable"
        lines.append(f"<li>{label}: {count}; {site['sitemap_urls']} sitemap URLs</li>")
    run_url = "/".join(filter(None, [os.getenv("GITHUB_SERVER_URL", ""),
                                      os.getenv("GITHUB_REPOSITORY", ""), "actions", "runs",
                                      os.getenv("GITHUB_RUN_ID", "")]))
    run_link = f'<p><a href="{html.escape(run_url)}">GitHub run and raw CSVs</a></p>' if run_url.startswith("https://") else ""
    return (
        f"<h2>CIM Site Source Portfolio — {html.escape(period)}</h2>"
        f"<p>Four sites reported separately; {source_ok}/{len(status)} source checks succeeded. "
        "The full HTML report is attached.</p>"
        f"<ul>{''.join(lines)}</ul>{run_link}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("portfolio_output"))
    args = parser.parse_args()
    report = args.root / "site_source_portfolio.html"
    if not report.is_file():
        parser.error(f"Report missing: {report}")
    sent = upload_html_to_monday(
        report, report.name, summary_body(args.root),
        item_id=os.getenv("MONDAY_SITE_SOURCE_PORTFOLIO_ITEM_ID"),
        delivery_root=args.root,
        finalize_before_upload=False,
    )
    if not sent:
        parser.error("Monday report delivery was skipped; check token and item ID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
