"""Shared reporting operations utilities for CIM SEO pipelines.

This module is intentionally additive: report scripts can keep producing their
existing CSV/HTML artifacts, and this layer adds operational metadata,
normalization, quality checks, and light HTML UX improvements after the fact.
"""

from __future__ import annotations

import csv
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd
from bs4 import BeautifulSoup


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "gbraid",
    "wbraid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "ref",
}

ROW_CAP_HINTS = {100, 200, 500, 1000, 5000, 10000, 25000}
URL_COLUMN_HINTS = ("url", "page", "landing", "source", "target", "link", "href")
FINDING_TABLE_HINTS = (
    "gainers",
    "losers",
    "entered_top",
    "issues_only",
    "opportunities",
    "anomalies",
    "decay",
    "selection",
    "flagged",
)


def infer_artifact_lineage(name: str) -> dict[str, str]:
    lower = name.lower()
    if lower.endswith("_config.csv") or lower in {"tracked_keywords.csv", "tracked_pages.csv", "tracked_conversions.csv"}:
        return {"source_system": "configuration", "data_stage": "input"}
    if "gsc" in lower or "keyword" in lower or "landing" in lower or "query" in lower:
        return {"source_system": "google_search_console", "data_stage": "processed"}
    if "ga4" in lower or "conversion" in lower or "event" in lower or "channel" in lower:
        return {"source_system": "google_analytics_4", "data_stage": "processed"}
    if "speed" in lower or "pagespeed" in lower:
        return {"source_system": "pagespeed_insights", "data_stage": "processed"}
    if "broken_link" in lower or "internal_link" in lower or "crawled" in lower or "discovered" in lower:
        return {"source_system": "site_crawl", "data_stage": "processed"}
    if "content_audit" in lower or "content_category" in lower:
        return {"source_system": "content_reporting", "data_stage": "processed"}
    if "ai_snippet" in lower:
        return {"source_system": "ai_snippet_verification", "data_stage": "processed"}
    if "weekly_seo" in lower or "intelligence" in lower or "decay" in lower or "anomal" in lower:
        return {"source_system": "weekly_intelligence", "data_stage": "derived"}
    return {"source_system": "unknown", "data_stage": "artifact"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonicalize_url(value: Any, default_scheme: str = "https") -> str:
    """Normalize a URL enough for cross-report joins without changing meaning."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""

    raw = str(value).strip()
    if not raw or raw.lower() in {"nan", "none"}:
        return ""

    if raw.startswith("//"):
        raw = f"{default_scheme}:{raw}"
    elif raw.startswith("/"):
        raw = f"{default_scheme}://www.cim.org{raw}"
    elif not re.match(r"^[a-z][a-z0-9+.-]*://", raw, flags=re.I):
        return raw

    parsed = urlparse(raw)
    scheme = (parsed.scheme or default_scheme).lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    query_pairs = []
    for key, val in parse_qsl(parsed.query, keep_blank_values=False):
        lower_key = key.lower()
        if lower_key in TRACKING_QUERY_KEYS:
            continue
        if any(lower_key.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_pairs.append((key, val))
    query = urlencode(sorted(query_pairs))

    return urlunparse((scheme, netloc, path, "", query, ""))


def likely_url_columns(columns: list[str]) -> list[str]:
    matches = []
    for col in columns:
        lower = col.lower()
        if any(hint in lower for hint in URL_COLUMN_HINTS):
            matches.append(col)
    return matches


def _safe_read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _numeric_null_pct(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return float(df.isna().sum().sum() / max(1, df.shape[0] * df.shape[1]))


def profile_csv(path: Path) -> dict[str, Any]:
    df = _safe_read_csv(path)
    profile = {
        "path": str(path),
        "name": path.name,
        **infer_artifact_lineage(path.name),
        "rows": int(len(df)),
        "columns": int(len(df.columns)) if not df.empty or len(df.columns) else 0,
        "empty": bool(df.empty),
        "url_columns": likely_url_columns(list(df.columns)),
        "null_cell_pct": round(_numeric_null_pct(df), 4),
        "duplicate_rows": int(df.duplicated().sum()) if not df.empty else 0,
    }

    if not df.empty:
        profile["columns_list"] = list(df.columns)
    return profile


def normalize_csv_urls(csv_path: Path, output_dir: Path) -> str | None:
    df = _safe_read_csv(csv_path)
    if df.empty and not list(df.columns):
        return None

    url_cols = likely_url_columns(list(df.columns))
    if not url_cols:
        return None

    normalized = df.copy()
    added = False
    for col in url_cols:
        canonical_col = f"{col}_canonical"
        normalized[canonical_col] = normalized[col].apply(canonicalize_url)
        added = True

    if not added:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{csv_path.stem}_normalized.csv"
    normalized.to_csv(out_path, index=False)
    return str(out_path)


def quality_warnings(report_name: str, profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for profile in profiles:
        name = profile["name"]
        rows = int(profile.get("rows", 0))
        cols = int(profile.get("columns", 0))

        if name.endswith(".csv") and rows == 0:
            is_finding_table = any(hint in name.lower() for hint in FINDING_TABLE_HINTS)
            warnings.append({
                "severity": "info" if is_finding_table else "high",
                "artifact": name,
                "issue": "Finding table has zero rows" if is_finding_table else "CSV output is empty",
                "recommendation": "Confirm whether zero qualifying findings is expected for this run." if is_finding_table else "Check source API credentials, date range, filters, and upstream artifact availability.",
            })

        if rows in ROW_CAP_HINTS:
            warnings.append({
                "severity": "medium",
                "artifact": name,
                "issue": f"Row count equals common API/reporting cap ({rows})",
                "recommendation": "Confirm pagination is enabled or raise the query limit to avoid silent truncation.",
            })

        if profile.get("null_cell_pct", 0) >= 0.5 and rows > 0 and cols > 3:
            warnings.append({
                "severity": "medium",
                "artifact": name,
                "issue": f"{profile['null_cell_pct']:.0%} of cells are blank/null",
                "recommendation": "Check previous-period joins, optional API fields, and field-data coverage labels.",
            })

    content_cat = next((p for p in profiles if p["name"] == "content_category_performance.csv"), None)
    if content_cat:
        df = _safe_read_csv(Path(content_cat["path"]))
        if not df.empty and "category" in df.columns:
            value_col = "sessions" if "sessions" in df.columns else "clicks" if "clicks" in df.columns else None
            if value_col:
                total = pd.to_numeric(df[value_col], errors="coerce").fillna(0).sum()
                other = pd.to_numeric(
                    df.loc[df["category"].astype(str).str.lower() == "other", value_col],
                    errors="coerce",
                ).fillna(0).sum()
                if total and other / total >= 0.35:
                    warnings.append({
                        "severity": "medium",
                        "artifact": "content_category_performance.csv",
                        "issue": f"'Other' accounts for {other / total:.0%} of {value_col}",
                        "recommendation": "Expand URL-to-category taxonomy and list unmatched URLs for cleanup.",
                    })

    broken = next((p for p in profiles if p["name"] == "broken_link_results.csv"), None)
    if broken:
        df = _safe_read_csv(Path(broken["path"]))
        if not df.empty and "status_type" in df.columns:
            issue_count = int((df["status_type"].astype(str).str.lower() != "ok").sum())
            unique_targets = int(df.loc[df["status_type"].astype(str).str.lower() != "ok", "target_url"].nunique()) if "target_url" in df.columns else issue_count
            if issue_count:
                warnings.append({
                    "severity": "high",
                    "artifact": "broken_link_results.csv",
                    "issue": f"{issue_count:,} non-OK link rows across {unique_targets:,} unique targets",
                    "recommendation": "Prioritize unique targets by source-page count; separate redirects from true broken URLs.",
                })

    if not warnings:
        warnings.append({
            "severity": "info",
            "artifact": report_name,
            "issue": "No obvious artifact quality issues detected",
            "recommendation": "Review report insights and source-data coverage as usual.",
        })
    return warnings


def _write_warnings_csv(warnings: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["severity", "artifact", "issue", "recommendation"])
        writer.writeheader()
        writer.writerows(warnings)


def _append_css(soup: BeautifulSoup) -> None:
    style = soup.new_tag("style")
    style.string = """
.ops-panel{border:2px solid #000;background:#fff;margin:24px 0;padding:20px 24px;font-family:Arial,sans-serif}
.ops-panel h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;margin:0 0 12px}
.ops-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:12px 0}
.ops-card{border:1px solid #111;padding:12px;background:#fafafa}
.ops-card strong{display:block;font-size:20px;line-height:1.1}
.ops-card span,.ops-panel li,.ops-panel a{font-size:12px}
.ops-warn-high{border-left:6px solid #dc2626}
.ops-warn-medium{border-left:6px solid #d97706}
.ops-warn-info{border-left:6px solid #2563eb}
.ops-panel a{color:#111;text-decoration:underline;text-underline-offset:2px}
table a{color:inherit;text-decoration:underline;text-underline-offset:2px}
details.ops-details{margin-top:12px}
details.ops-details summary{cursor:pointer;font-size:12px;font-weight:700;text-transform:uppercase}
"""
    if soup.head:
        soup.head.append(style)


def _linkify_table_urls(soup: BeautifulSoup) -> int:
    changed = 0
    for cell in soup.find_all(["td", "th"]):
        if cell.find("a"):
            continue
        text = cell.get_text(strip=True)
        if not re.match(r"^https?://", text):
            continue
        href = html.escape(text, quote=True)
        label = html.escape(text if len(text) <= 96 else text[:93] + "...")
        cell.clear()
        link = soup.new_tag("a", href=href, target="_blank", rel="noopener")
        link.string = label
        cell.append(link)
        changed += 1
    return changed


def enhance_html_report(
    html_path: Path,
    report_name: str,
    manifest: dict[str, Any],
    warnings: list[dict[str, Any]],
    root: Path | str = ".",
) -> bool:
    if not html_path.exists():
        return False
    try:
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    except Exception:
        return False

    if soup.find(attrs={"data-reporting-ops": "true"}):
        return False

    _append_css(soup)
    _linkify_table_urls(soup)

    body = soup.body or soup
    panel = soup.new_tag("section", **{"class": "ops-panel", "data-reporting-ops": "true"})
    h2 = soup.new_tag("h2")
    h2.string = "Run Quality And Downloads"
    panel.append(h2)

    grid = soup.new_tag("div", **{"class": "ops-grid"})
    stats = [
        ("CSV artifacts", len([a for a in manifest["artifacts"] if a["type"] == "csv"])),
        ("HTML reports", len([a for a in manifest["artifacts"] if a["type"] == "html"])),
        ("Rows profiled", sum(a.get("rows", 0) for a in manifest["artifacts"] if a["type"] == "csv")),
        ("Warnings", len([w for w in warnings if w["severity"] != "info"])),
    ]
    for label, value in stats:
        card = soup.new_tag("div", **{"class": "ops-card"})
        strong = soup.new_tag("strong")
        strong.string = f"{value:,}" if isinstance(value, int) else str(value)
        span = soup.new_tag("span")
        span.string = label
        card.append(strong)
        card.append(span)
        grid.append(card)
    panel.append(grid)

    details = soup.new_tag("details", **{"class": "ops-details", "open": ""})
    summary = soup.new_tag("summary")
    summary.string = "Quality signals"
    details.append(summary)
    ul = soup.new_tag("ul")
    for warning in warnings[:8]:
        li = soup.new_tag("li", **{"class": f"ops-warn-{warning['severity']}"})
        li.string = f"{warning['severity'].upper()}: {warning['artifact']} - {warning['issue']}"
        ul.append(li)
    details.append(ul)
    panel.append(details)

    root_path = Path(root).resolve()
    try:
        rel_parent = html_path.parent.resolve().relative_to(root_path)
        prefix = "" if str(rel_parent) == "." else "../" * len(rel_parent.parts)
    except Exception:
        prefix = ""

    links = soup.new_tag("p")
    for i, filename in enumerate(("reporting_artifact_index.html", "report_manifest.json", "reporting_quality_warnings.csv")):
        if i:
            links.append(" | ")
        a = soup.new_tag("a", href=f"{prefix}{filename}")
        a.string = filename
        links.append(a)
    panel.append(links)

    if body.contents:
        body.insert(1 if body.contents[0].name == "header" else 0, panel)
    else:
        body.append(panel)

    html_path.write_text(str(soup), encoding="utf-8")
    return True


def write_artifact_index(report_name: str, manifest: dict[str, Any], warnings: list[dict[str, Any]], path: Path) -> None:
    rows = []
    for artifact in manifest["artifacts"]:
        href = artifact["path"]
        meta = ""
        if artifact["type"] == "csv":
            meta = f"{artifact.get('rows', 0):,} rows, {artifact.get('columns', 0):,} columns"
        lineage = ""
        if artifact.get("source_system"):
            lineage = f"{artifact.get('source_system', '')} / {artifact.get('data_stage', '')}"
        rows.append(
            "<tr>"
            f"<td><a href=\"{html.escape(href)}\">{html.escape(artifact['name'])}</a></td>"
            f"<td>{html.escape(artifact['type'])}</td>"
            f"<td>{html.escape(lineage)}</td>"
            f"<td>{html.escape(meta)}</td>"
            "</tr>"
        )

    warning_items = "".join(
        f"<li><strong>{html.escape(w['severity'])}</strong>: {html.escape(w['artifact'])} - {html.escape(w['issue'])}</li>"
        for w in warnings
    )

    output = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(report_name)} Artifact Index</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;line-height:1.5;color:#111}}
table{{border-collapse:collapse;width:100%;margin-top:16px}}th,td{{border:1px solid #ddd;padding:8px;text-align:left}}th{{background:#111;color:#fff}}
a{{color:#111;text-decoration:underline;text-underline-offset:2px}}
.panel{{border:2px solid #111;padding:16px;margin:20px 0;background:#fafafa}}
</style>
</head>
<body>
<h1>{html.escape(report_name)} Artifact Index</h1>
<p>Generated {html.escape(manifest['generated_at'])}.</p>
<div class="panel">
<h2>Quality Signals</h2>
<ul>{warning_items}</ul>
</div>
<table>
<thead><tr><th>Artifact</th><th>Type</th><th>Lineage</th><th>Profile</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body>
</html>"""
    path.write_text(output, encoding="utf-8")


def finalize_report_artifacts(report_name: str, root: Path | str = ".") -> dict[str, Any]:
    root = Path(root)
    normalized_dir = root / "normalized"

    csv_paths = sorted(p for p in root.glob("*.csv") if p.is_file())
    html_paths = sorted(p for p in root.glob("*.html") if p.is_file())
    other_suffixes = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".pdf", ".md", ".json"}
    other_paths = sorted(
        p for p in root.glob("*")
        if p.is_file() and p.suffix.lower() in other_suffixes
    )
    for subdir in ("reports", "monthly_data"):
        if (root / subdir).exists():
            csv_paths.extend(sorted((root / subdir).glob("*.csv")))
            html_paths.extend(sorted((root / subdir).glob("*.html")))
            other_paths.extend(
                sorted(
                    p for p in (root / subdir).glob("*")
                    if p.is_file() and p.suffix.lower() in other_suffixes
                )
            )
    for subdir in ("charts", "site_speed_charts", "screenshots", "evidence", "outputs"):
        if (root / subdir).exists():
            other_paths.extend(
                sorted(
                    p for p in (root / subdir).glob("*")
                    if p.is_file() and p.suffix.lower() in other_suffixes
                )
            )

    profiles = [profile_csv(path) for path in csv_paths]
    normalized_paths = []
    for path in csv_paths:
        normalized = normalize_csv_urls(path, normalized_dir)
        if normalized:
            normalized_paths.append(normalized)

    warnings = quality_warnings(report_name, profiles)
    _write_warnings_csv(warnings, root / "reporting_quality_warnings.csv")

    artifacts: list[dict[str, Any]] = []
    for profile in profiles:
        profile["type"] = "csv"
        profile["path"] = os.path.relpath(profile["path"], root)
        artifacts.append(profile)
    for path in html_paths:
        artifacts.append({
            "type": "html",
            "name": path.name,
            "path": os.path.relpath(path, root),
            "size_bytes": path.stat().st_size,
        })
    seen_paths = {artifact["path"] for artifact in artifacts}
    for path in other_paths:
        rel_path = os.path.relpath(path, root)
        if rel_path in seen_paths:
            continue
        artifacts.append({
            "type": path.suffix.lower().lstrip(".") or "file",
            "name": path.name,
            "path": rel_path,
            "size_bytes": path.stat().st_size,
        })
    for path in normalized_paths:
        p = Path(path)
        artifacts.append({
            "type": "normalized_csv",
            "name": p.name,
            "path": os.path.relpath(p, root),
            "size_bytes": p.stat().st_size,
        })

    manifest = {
        "report_name": report_name,
        "generated_at": utc_now_iso(),
        "run_id": os.getenv("GITHUB_RUN_ID", ""),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""),
        "workflow": os.getenv("GITHUB_WORKFLOW", ""),
        "sha": os.getenv("GITHUB_SHA", ""),
        "artifacts": artifacts,
        "warnings": warnings,
    }

    (root / "report_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_artifact_index(report_name, manifest, warnings, root / "reporting_artifact_index.html")

    for path in html_paths:
        enhance_html_report(path, report_name, manifest, warnings, root)

    return manifest
