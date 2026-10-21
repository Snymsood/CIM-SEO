import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reporting_ops import canonicalize_url, finalize_report_artifacts, record_delivery_status


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
    record_delivery_status("skipped", detail="test", root=tmp_path)

    manifest = finalize_report_artifacts("Sample Report", tmp_path)

    assert (tmp_path / "report_manifest.json").exists()
    assert (tmp_path / "reporting_quality_warnings.csv").exists()
    assert (tmp_path / "reporting_artifact_index.html").exists()
    assert (tmp_path / "normalized" / "sample_normalized.csv").exists()

    saved_manifest = json.loads((tmp_path / "report_manifest.json").read_text(encoding="utf-8"))
    assert saved_manifest["report_name"] == "Sample Report"
    assert saved_manifest["period_id"] == f"{saved_manifest['period_start']}_{saved_manifest['period_end']}"
    assert saved_manifest["delivery"]["status"] == "skipped"
    assert manifest["report_name"] == "Sample Report"

    html = (tmp_path / "sample.html").read_text(encoding="utf-8")
    assert "Run Quality And Downloads" in html
    assert "href=\"https://www.cim.org/page/\"" in html


def test_source_failures_appear_in_quality_warnings(tmp_path):
    (tmp_path / "site_source_status.csv").write_text(
        "site_id,source,status,record_count,detail\n"
        "main,sitemap,ok,126,Parsed\n"
        "magazine,ga4,failed,0,Check service account Viewer access\n"
        "cimconnect,gsc_url_inspection,not_configured,0,GSC property missing\n",
        encoding="utf-8",
    )

    finalize_report_artifacts("Site Source Portfolio", tmp_path)

    warnings = pd.read_csv(tmp_path / "reporting_quality_warnings.csv")
    assert "magazine ga4: failed" in warnings["issue"].values
    assert "cimconnect gsc_url_inspection: not_configured" in warnings["issue"].values
    assert "No obvious artifact quality issues detected" not in warnings["issue"].values
