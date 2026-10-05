#!/usr/bin/env python3
"""Run missed weekly reports in one GitHub Actions job.

This is a recovery path for days when GitHub Actions accepts many workflow
dispatches but cancels queued jobs before they receive runners. Running the
missed reports serially inside one runner avoids asking Actions to allocate a
separate runner for every report.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


STATUS_CSV = Path("weekly_backfill_status.csv")
STATUS_JSON = Path("weekly_backfill_status.json")
STATUS_MD = Path("weekly_backfill_summary.md")


def _env(overrides: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({k: str(v) for k, v in overrides.items() if v is not None})
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _run(label: str, script: str, overrides: dict[str, str]) -> dict[str, object]:
    print("\n" + "=" * 78, flush=True)
    print(f"STARTING: {label} ({script})", flush=True)
    print("=" * 78, flush=True)

    started = datetime.now(timezone.utc)
    process = subprocess.Popen(
        [sys.executable, "-u", script],
        env=_env(overrides),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert process.stdout is not None
    for line in process.stdout:
        print(f"[{label}] {line.rstrip()}", flush=True)

    return_code = process.wait()
    finished = datetime.now(timezone.utc)
    status = "success" if return_code == 0 else "failed"
    duration = round((finished - started).total_seconds(), 1)
    print(f"FINISHED: {label} -> {status} in {duration}s", flush=True)

    return {
        "report": label,
        "script": script,
        "status": status,
        "return_code": return_code,
        "started_at": started.replace(microsecond=0).isoformat(),
        "finished_at": finished.replace(microsecond=0).isoformat(),
        "duration_seconds": duration,
    }


def _write_status(rows: list[dict[str, object]]) -> None:
    fields = [
        "report",
        "script",
        "status",
        "return_code",
        "started_at",
        "finished_at",
        "duration_seconds",
    ]
    with STATUS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    STATUS_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    lines = ["# Weekly Report Backfill Status", ""]
    for row in rows:
        marker = "OK" if row["status"] == "success" else "FAILED"
        lines.append(f"- {marker}: {row['report']} ({row['duration_seconds']}s)")
    STATUS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


SOURCE_REPORTS = [
    {
        "label": "GSC Weekly Report",
        "script": "gsc_weekly_report.py",
        "env": {
            "GSC_PROPERTY": "https://www.cim.org/",
            "GROQ_MODEL": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "MONDAY_ITEM_ID": os.getenv("MONDAY_GSC_ITEM_ID") or os.getenv("MONDAY_ITEM_ID", ""),
        },
    },
    {
        "label": "Keyword Ranking Review",
        "script": "gsc_keyword_ranking_report.py",
        "env": {
            "GSC_PROPERTY": "sc-domain:cim.org",
            "GROQ_MODEL": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "MONDAY_ITEM_ID": os.getenv("MONDAY_GSC_KEYWORD_ITEM_ID", ""),
        },
    },
    {
        "label": "Critical Landing Pages",
        "script": "gsc_landing_pages_report.py",
        "env": {
            "GSC_PROPERTY": "sc-domain:cim.org",
            "GROQ_MODEL": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "MONDAY_ITEM_ID": os.getenv("MONDAY_GSC_LANDING_ITEM_ID", ""),
        },
    },
    {
        "label": "Site Speed Monitoring",
        "script": "site_speed_monitoring.py",
        "env": {
            "GROQ_MODEL": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "MONDAY_ITEM_ID": os.getenv("MONDAY_SITE_SPEED_ITEM_ID", ""),
        },
    },
    {
        "label": "GA4 Weekly Report",
        "script": "ga4_weekly_report.py",
        "env": {
            "GA4_PROPERTY_ID": "341629008",
            "GROQ_MODEL": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "MONDAY_ITEM_ID": os.getenv("MONDAY_GA4_WEEKLY_ITEM_ID", ""),
        },
    },
    {
        "label": "GA4 Event Report",
        "script": "ga4_event_report.py",
        "env": {
            "GA4_PROPERTY_ID": "341629008",
            "MONDAY_ITEM_ID": os.getenv("MONDAY_EVENT_REPORT_ITEM_ID", ""),
            "EVENT_CONFIG_PATH": "event_tracking_config.csv",
        },
    },
    {
        "label": "Content Audit Schedule",
        "script": "content_audit_schedule_report.py",
        "env": {
            "GSC_PROPERTY": "https://www.cim.org/",
            "GROQ_MODEL": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            "MONDAY_ITEM_ID": os.getenv("MONDAY_CONTENT_AUDIT_ITEM_ID", ""),
        },
    },
    {
        "label": "Content Category Performance",
        "script": "content_category_performance.py",
        "env": {
            "GSC_PROPERTY": "https://www.cim.org/",
            "GA4_PROPERTY_ID": "341629008",
            "MONDAY_ITEM_ID": os.getenv("MONDAY_CONTENT_CATEGORY_ITEM_ID", ""),
        },
    },
]


DEPENDENT_REPORTS = [
    {
        "label": "Content Strategy Report",
        "script": "content_strategy_report.py",
        "env": {
            "MONDAY_ITEM_ID": os.getenv("MONDAY_CONTENT_STRATEGY_ITEM_ID", ""),
        },
    },
    {
        "label": "Weekly SEO Intelligence",
        "script": "weekly_seo_intelligence.py",
        "env": {
            "ENABLE_WEEKLY_INTELLIGENCE": "true",
            "ENABLE_AI_ACTION_PLAN": "true",
        },
    },
]


def main() -> int:
    rows: list[dict[str, object]] = []

    for report in SOURCE_REPORTS:
        rows.append(_run(report["label"], report["script"], report["env"]))
        _write_status(rows)

    source_failures = [row for row in rows if row["status"] != "success"]
    if source_failures:
        failed = ", ".join(str(row["report"]) for row in source_failures)
        print(f"Skipping dependent reports because source reports failed: {failed}", flush=True)
        _write_status(rows)
        return 1

    for report in DEPENDENT_REPORTS:
        rows.append(_run(report["label"], report["script"], report["env"]))
        _write_status(rows)

    failures = [row for row in rows if row["status"] != "success"]
    _write_status(rows)
    if failures:
        failed = ", ".join(str(row["report"]) for row in failures)
        print(f"Backfill completed with failures: {failed}", flush=True)
        return 1

    print("Backfill completed successfully.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
