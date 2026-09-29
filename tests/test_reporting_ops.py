import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reporting_ops import canonicalize_url, finalize_report_artifacts


def test_canonicalize_url_removes_tracking_and_normalizes_host():
    url = "HTTPS://WWW.CIM.ORG/Example/Page/?utm_source=newsletter&b=2&a=1#section"

    assert canonicalize_url(url) == "https://cim.org/Example/Page?a=1&b=2"


def test_canonicalize_relative_url_to_cim_domain():
    assert canonicalize_url("/events/?gclid=abc") == "https://cim.org/events"


def test_finalize_report_artifacts_creates_manifest_and_enhances_html(tmp_path):
    pd.DataFrame({
        "page": ["https://www.cim.org/page/?utm_medium=email"],
        "clicks": [12],
    }).to_csv(tmp_path / "sample.csv", index=False)
    (tmp_path / "sample.html").write_text(
        "<html><head><title>Sample</title></head><body><table><tr><td>https://www.cim.org/page/</td></tr></table></body></html>",
        encoding="utf-8",
    )

    manifest = finalize_report_artifacts("Sample Report", tmp_path)

    assert (tmp_path / "report_manifest.json").exists()
    assert (tmp_path / "reporting_quality_warnings.csv").exists()
    assert (tmp_path / "reporting_artifact_index.html").exists()
    assert (tmp_path / "normalized" / "sample_normalized.csv").exists()

    saved_manifest = json.loads((tmp_path / "report_manifest.json").read_text(encoding="utf-8"))
    assert saved_manifest["report_name"] == "Sample Report"
    assert manifest["report_name"] == "Sample Report"

    html = (tmp_path / "sample.html").read_text(encoding="utf-8")
    assert "Run Quality And Downloads" in html
    assert "href=\"https://www.cim.org/page/\"" in html
