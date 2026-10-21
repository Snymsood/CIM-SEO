"""Reject downloaded report artifacts whose declared week differs from this run."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from seo_utils import get_weekly_date_windows


def validate_artifact(directory: Path, artifact: str, run_id: str, ledger: Path) -> dict:
    manifest_path = directory / "report_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"{artifact}: report_manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    start, end, _, _ = get_weekly_date_windows()
    expected = (start.isoformat(), end.isoformat())
    actual = (manifest.get("period_start"), manifest.get("period_end"))
    if str(manifest.get("run_id", "")) != str(run_id):
        raise ValueError(f"{artifact}: manifest run ID differs from downloaded run {run_id}")
    if any(manifest.get(field) is not None for field in ("period_start", "period_end", "period_id")):
        if manifest.get("period_id") != f"{actual[0]}_{actual[1]}":
            raise ValueError(f"{artifact}: period ID does not match manifest start/end")
        is_rolling_audit = artifact == "content-audit-schedule" and actual[1] == expected[1] and actual[0] == (start - timedelta(days=21)).isoformat()
        if actual != expected and not is_rolling_audit:
            raise ValueError(f"{artifact}: period {actual} differs from expected {expected}")
        period_id = manifest["period_id"]
    else:
        # Manifests written before the period fields were added still identify the
        # run and generation time. Only accept one generated during the current
        # reporting week; do not infer freshness from the download time.
        try:
            generated = datetime.fromisoformat(manifest["generated_at"].replace("Z", "+00:00"))
            if generated.tzinfo is None:
                raise ValueError("timestamp has no timezone")
            generated = generated.astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{artifact}: legacy manifest has no valid generation time") from exc
        generated_day = generated.date()
        report_start, report_end, _, _ = get_weekly_date_windows(as_of=generated_day)
        if ((report_start.isoformat(), report_end.isoformat()) != expected
                or generated_day > datetime.now(timezone.utc).date()):
            raise ValueError(f"{artifact}: legacy manifest generation week differs from expected {expected}")
        period_id = f"{expected[0]}_{expected[1]}"
    record = {"artifact": artifact, "report_name": manifest.get("report_name", ""),
              "run_id": str(run_id), "period_id": period_id}
    existing = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else []
    existing = [item for item in existing if item.get("artifact") != artifact]
    existing.append(record)
    ledger.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("artifact")
    parser.add_argument("run_id")
    parser.add_argument("--ledger", type=Path, default=Path("source_report_runs.json"))
    args = parser.parse_args()
    try:
        print(json.dumps(validate_artifact(args.directory, args.artifact, args.run_id, args.ledger)))
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Rejected source artifact: {exc}\n")
