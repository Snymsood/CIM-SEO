#!/usr/bin/env python3
"""Finalize CIM SEO report artifacts after a report script runs."""

import argparse
import json
from pathlib import Path

from reporting_ops import finalize_report_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reporting manifest, quality warnings, normalized CSVs, and HTML UX enhancements.")
    parser.add_argument("--report-name", required=True, help="Human-readable report name.")
    parser.add_argument("--root", default=".", help="Artifact root directory. Defaults to current directory.")
    args = parser.parse_args()

    manifest = finalize_report_artifacts(args.report_name, Path(args.root))
    summary = {
        "report_name": manifest["report_name"],
        "artifact_count": len(manifest["artifacts"]),
        "warning_count": len([w for w in manifest["warnings"] if w["severity"] != "info"]),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
