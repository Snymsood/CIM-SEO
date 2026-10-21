#!/usr/bin/env python3
"""Collect free, site-scoped SEO sources using the existing weekly report pattern.

Public sitemaps always run. GSC inspection, CrUX, and GA4 run when their existing
credentials and per-site configuration are available. Missing access is recorded
as coverage, never converted into a zero metric.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import html
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


MAX_XML_BYTES = 8_000_000
MAX_SITEMAPS = 50
MAX_URLS = 100_000
SOURCES = {"sitemap", "inspection", "crux", "ga4"}
CRUX_METRICS = (
    "largest_contentful_paint",
    "interaction_to_next_paint",
    "cumulative_layout_shift",
)


@dataclass(frozen=True)
class Site:
    site_id: str
    site_name: str
    base_url: str
    sitemap_url: str
    gsc_property: str
    ga4_property_id: str
    ga4_measurement_id: str
    inspection_limit: int

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    @property
    def origin(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def allowed_hosts(self) -> set[str]:
        # The main site's supplied URL list and public sitemap use the apex,
        # which currently redirects to the chosen www reporting standard.
        return {self.host, "cim.org"} if self.site_id == "main" else {self.host}


def read_sites(config_path: Path) -> list[Site]:
    with config_path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Site configuration is empty")
    sites = []
    seen = set()
    for row in rows:
        site_id = row["site_id"].strip()
        base_url = row["base_url"].strip()
        sitemap_url = row["sitemap_url"].strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", site_id) or site_id in seen:
            raise ValueError(f"Invalid or duplicate site_id: {site_id}")
        if not all(urlsplit(url).scheme == "https" and urlsplit(url).hostname for url in (base_url, sitemap_url)):
            raise ValueError(f"Site {site_id} requires HTTPS base and sitemap URLs")
        if urlsplit(sitemap_url).hostname not in ({urlsplit(base_url).hostname, "cim.org"} if site_id == "main" else {urlsplit(base_url).hostname}):
            raise ValueError(f"Sitemap host differs from site host: {site_id}")
        ga4_id = row.get("ga4_property_id", "").strip()
        if ga4_id and not ga4_id.isdigit():
            raise ValueError(f"GA4 property ID must be numeric for {site_id}")
        limit = int(row.get("inspection_limit", "5") or "5")
        if not 0 <= limit <= 50:
            raise ValueError(f"Inspection limit must be 0–50 for {site_id}")
        sites.append(Site(
            site_id=site_id,
            site_name=row["site_name"].strip(),
            base_url=base_url,
            sitemap_url=sitemap_url,
            gsc_property=row.get("gsc_property", "").strip(),
            ga4_property_id=ga4_id,
            ga4_measurement_id=row.get("ga4_measurement_id", "").strip(),
            inspection_limit=limit,
        ))
        seen.add(site_id)
    return sites


def _fetch_xml(url: str, allowed_hosts: set[str]) -> tuple[bytes, str]:
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname not in allowed_hosts:
        raise ValueError("Sitemap URL is outside the configured site")
    request = urllib.request.Request(url, headers={"User-Agent": "CIM-SEO-Site-Inventory/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        final_url = response.geturl()
        if urlsplit(final_url).scheme != "https" or urlsplit(final_url).hostname not in allowed_hosts:
            raise ValueError("Sitemap redirect left the configured site")
        content = response.read(MAX_XML_BYTES + 1)
    if len(content) > MAX_XML_BYTES:
        raise ValueError("Sitemap exceeds the per-file size limit")
    if content.startswith(b"\x1f\x8b"):
        content = gzip.decompress(content)
        if len(content) > MAX_XML_BYTES:
            raise ValueError("Uncompressed sitemap exceeds the per-file size limit")
    return content, final_url


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _normalize_url(site: Site, url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or host not in site.allowed_hosts:
        return ""
    if site.site_id == "main" and host == "cim.org":
        host = "www.cim.org"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urlunsplit(("https", host, path, parts.query, ""))


def collect_sitemaps(site: Site, fetch=_fetch_xml) -> tuple[list[dict], list[dict], list[str]]:
    pending = deque([site.sitemap_url])
    visited = set()
    urls: dict[str, dict] = {}
    sitemap_rows: list[dict] = []
    warnings: list[str] = []

    while pending:
        sitemap_url = pending.popleft()
        if sitemap_url in visited:
            continue
        if len(visited) >= MAX_SITEMAPS:
            warnings.append("Sitemap index exceeded the 50-file safety limit")
            break
        visited.add(sitemap_url)
        try:
            payload, final_url = fetch(sitemap_url, site.allowed_hosts)
            root = ET.fromstring(payload)
            kind = _local_name(root.tag)
            if kind not in {"urlset", "sitemapindex"}:
                raise ValueError(f"Unexpected sitemap XML root: {kind}")
            entries = [node for node in root if _local_name(node.tag) in {"url", "sitemap"}]
            sitemap_rows.append({"site_id": site.site_id, "sitemap_url": sitemap_url,
                                 "final_url": final_url, "kind": kind, "entry_count": len(entries), "status": "ok"})
            for entry in entries:
                loc = _child_text(entry, "loc")
                if not loc:
                    continue
                if kind == "sitemapindex":
                    parsed = urlsplit(loc)
                    if parsed.scheme == "https" and parsed.hostname in site.allowed_hosts:
                        pending.append(loc)
                    else:
                        warnings.append(f"Ignored sitemap outside {site.site_id}: {loc}")
                    continue
                normalized = _normalize_url(site, loc)
                if not normalized:
                    warnings.append(f"Ignored URL outside {site.site_id}: {loc}")
                    continue
                if len(urls) >= MAX_URLS:
                    warnings.append("Sitemap inventory exceeded the 100,000-URL safety limit")
                    pending.clear()
                    break
                lastmod = _child_text(entry, "lastmod")
                candidate = {"site_id": site.site_id, "url": normalized, "raw_url": loc,
                             "lastmod": lastmod, "source_sitemap": sitemap_url}
                previous = urls.get(normalized)
                if previous is None or lastmod > previous["lastmod"]:
                    urls[normalized] = candidate
        except Exception as exc:
            sitemap_rows.append({"site_id": site.site_id, "sitemap_url": sitemap_url,
                                 "final_url": "", "kind": "", "entry_count": 0, "status": "failed"})
            warnings.append(f"{sitemap_url}: {type(exc).__name__}")
    return list(urls.values()), sitemap_rows, warnings


def _week_dates() -> tuple[str, str]:
    today = date.today()
    days_since_sunday = (today.weekday() + 1) % 7 or 7
    end = today - timedelta(days=days_since_sunday)
    return (end - timedelta(days=6)).isoformat(), end.isoformat()


def _status(site: Site, source: str, state: str, count: int = 0, detail: str = "") -> dict:
    return {"site_id": site.site_id, "source": source, "status": state,
            "record_count": count, "detail": detail}


def collect_inspections(site: Site, urls: list[dict], key_file: Path) -> tuple[list[dict], dict]:
    if not site.gsc_property:
        return [], _status(site, "gsc_url_inspection", "not_configured", detail="GSC property missing")
    if not key_file.exists():
        return [], _status(site, "gsc_url_inspection", "not_configured", detail="Service account key missing")
    if site.inspection_limit == 0:
        return [], _status(site, "gsc_url_inspection", "disabled")

    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession

    credentials = service_account.Credentials.from_service_account_file(
        str(key_file), scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    session = AuthorizedSession(credentials)
    candidates = [site.base_url]
    candidates.extend(row["url"] for row in sorted(urls, key=lambda r: r["lastmod"], reverse=True))
    selected = list(dict.fromkeys(candidates))[:site.inspection_limit]
    rows = []
    failures = 0
    for url in selected:
        try:
            response = session.post(
                "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
                json={"inspectionUrl": url, "siteUrl": site.gsc_property}, timeout=30)
            if not response.ok:
                failures += 1
                rows.append({"site_id": site.site_id, "url": url, "status": f"http_{response.status_code}",
                             "verdict": "", "coverage_state": "", "google_canonical": "",
                             "user_canonical": "", "last_crawl_time": "", "page_fetch_state": ""})
                continue
            result = response.json().get("inspectionResult", {}).get("indexStatusResult", {})
            rows.append({"site_id": site.site_id, "url": url, "status": "ok",
                         "verdict": result.get("verdict", ""),
                         "coverage_state": result.get("coverageState", ""),
                         "google_canonical": result.get("googleCanonical", ""),
                         "user_canonical": result.get("userCanonical", ""),
                         "last_crawl_time": result.get("lastCrawlTime", ""),
                         "page_fetch_state": result.get("pageFetchState", "")})
        except Exception as exc:
            failures += 1
            rows.append({"site_id": site.site_id, "url": url, "status": type(exc).__name__,
                         "verdict": "", "coverage_state": "", "google_canonical": "",
                         "user_canonical": "", "last_crawl_time": "", "page_fetch_state": ""})
    state = "ok" if not failures else ("partial" if failures < len(selected) else "failed")
    return rows, _status(site, "gsc_url_inspection", state, len(rows),
                         f"{len(selected) - failures}/{len(selected)} inspected successfully; property={site.gsc_property}")


def collect_crux(site: Site, api_key: str) -> tuple[list[dict], dict]:
    if not api_key:
        return [], _status(site, "crux_history", "not_configured", detail="Chrome UX Report API key unavailable")

    import requests

    response = requests.post(
        "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord",
        params={"key": api_key},
        json={"origin": site.origin, "formFactor": "PHONE", "metrics": list(CRUX_METRICS),
              "collectionPeriodCount": 40}, timeout=30)
    if not response.ok:
        # Never include the request URL: it contains the API key.
        detail = _crux_error_detail(response)
        return [], _status(site, "crux_history", f"http_{response.status_code}",
                           detail=detail)
    record = response.json().get("record", {})
    periods = record.get("collectionPeriods", [])
    rows = []
    for metric, values in record.get("metrics", {}).items():
        p75s = values.get("percentilesTimeseries", {}).get("p75s", [])
        for index, period in enumerate(periods):
            start = period.get("firstDate", {})
            end = period.get("lastDate", {})
            rows.append({
                "site_id": site.site_id, "origin": site.origin, "form_factor": "PHONE",
                "metric": metric,
                "period_start": f"{start.get('year', 0):04d}-{start.get('month', 0):02d}-{start.get('day', 0):02d}",
                "period_end": f"{end.get('year', 0):04d}-{end.get('month', 0):02d}-{end.get('day', 0):02d}",
                "p75_raw": p75s[index] if index < len(p75s) else "",
            })
    return rows, _status(site, "crux_history", "ok" if rows else "empty", len(rows),
                         "Origin-level phone data; each weekly point covers an overlapping 28-day window")


def _crux_error_detail(response) -> str:
    if response.status_code == 404:
        return "No origin-level phone field data"
    project = ""
    try:
        error = response.json().get("error", {})
        error_info = [item for item in error.get("details", [])
                      if item.get("@type", "").endswith("google.rpc.ErrorInfo")]
        reasons = [item.get("reason", "") for item in error_info]
        reason = next((value for value in reasons if re.fullmatch(r"[A-Z_]+", value)), "")
        consumers = [item.get("metadata", {}).get("consumer", "") for item in error_info]
        project = next((value.removeprefix("projects/") for value in consumers
                        if re.fullmatch(r"projects/[0-9]+", value)), "")
    except (AttributeError, TypeError, ValueError):
        reason = ""
    guidance = {
        "API_KEY_SERVICE_BLOCKED": "Enable Chrome UX Report API and allow it in the API key restrictions",
        "SERVICE_DISABLED": "Enable Chrome UX Report API in the API key's Google Cloud project",
        "API_KEY_HTTP_REFERRER_BLOCKED": "Use an API key permitted for GitHub Actions server requests",
        "API_KEY_IP_ADDRESS_BLOCKED": "Use an API key permitted for GitHub Actions server requests",
        "API_KEY_INVALID": "Replace the invalid API key in GitHub Secrets",
        "QUOTA_EXCEEDED": "Check Chrome UX Report API quota",
    }
    detail = f"{reason}: {guidance[reason]}" if reason in guidance else (
        f"Google API reason {reason}" if reason else
        "Check Chrome UX Report API enablement and key restrictions")
    return f"{detail}; Google Cloud project number {project}" if project else detail


def collect_ga4(site: Site, key_file: Path) -> tuple[list[dict], list[dict], dict]:
    if not site.ga4_property_id:
        return [], [], _status(site, "ga4", "not_configured",
                                detail=f"Numeric property ID missing; measurement ID={site.ga4_measurement_id or 'unknown'}")
    if not key_file.exists():
        return [], [], _status(site, "ga4", "not_configured", detail="Service account key missing")

    from google.oauth2 import service_account
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Filter, FilterExpression, Metric, RunReportRequest)

    credentials = service_account.Credentials.from_service_account_file(
        str(key_file), scopes=["https://www.googleapis.com/auth/analytics.readonly"])
    client = BetaAnalyticsDataClient(credentials=credentials)
    start, end = _week_dates()
    host_filter = FilterExpression(filter=Filter(
        field_name="hostName", string_filter=Filter.StringFilter(value=site.host)))
    property_name = f"properties/{site.ga4_property_id}"
    total = client.run_report(RunReportRequest(
        property=property_name, date_ranges=[DateRange(start_date=start, end_date=end)],
        metrics=[Metric(name="sessions"), Metric(name="activeUsers")],
        dimension_filter=host_filter, limit=1))
    summary = [{"site_id": site.site_id, "host": site.host,
                "ga4_property_id": site.ga4_property_id,
                "period_start": start, "period_end": end,
                "sessions": total.rows[0].metric_values[0].value if total.rows else "",
                "active_users": total.rows[0].metric_values[1].value if total.rows else ""}]
    events = client.run_report(RunReportRequest(
        property=property_name, date_ranges=[DateRange(start_date=start, end_date=end)],
        dimensions=[Dimension(name="eventName")], metrics=[Metric(name="eventCount")],
        dimension_filter=host_filter, limit=1000))
    event_rows = [{"site_id": site.site_id, "host": site.host,
                   "ga4_property_id": site.ga4_property_id, "period_start": start,
                   "period_end": end, "event_name": row.dimension_values[0].value,
                   "event_count": row.metric_values[0].value} for row in events.rows]
    state = "ok" if total.rows or event_rows else "empty"
    detail = (f"Filtered to hostName={site.host}; event names are descriptive, not classified as conversions"
              if state == "ok" else f"No rows for hostName={site.host}; verify property and web-stream mapping")
    return summary, event_rows, _status(site, "ga4", state, len(event_rows), detail)


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_html(sites: list[Site], overview: list[dict], statuses: list[dict], output: Path) -> None:
    by_status = {(row["site_id"], row["source"]): row for row in statuses}
    def cell(value: object) -> str:
        return html.escape(str(value or ""))
    site_rows = []
    for site, row in zip(sites, overview):
        source_cells = []
        for source in ("sitemap", "gsc_url_inspection", "crux_history", "ga4"):
            status = by_status.get((site.site_id, source), {})
            source_cells.append(f"<td title='{cell(status.get('detail', ''))}'>{cell(status.get('status', 'not run'))}</td>")
        site_rows.append(
            f"<tr><th><a href='{cell(site.base_url)}'>{cell(site.site_name)}</a><small>{cell(site.host)}</small></th>"
            f"<td>{cell(row['sitemap_urls'])}</td><td>{cell(row['latest_sitemap_lastmod'])}</td>"
            f"<td>{cell(row['ga4_sessions'])}</td><td>{cell(row['inspected_ok'])}</td>"
            + "".join(source_cells) + "</tr>")
    status_rows = [f"<tr><td>{cell(s['site_id'])}</td><td>{cell(s['source'])}</td>"
                   f"<td>{cell(s['status'])}</td><td>{cell(s['record_count'])}</td>"
                   f"<td>{cell(s['detail'])}</td></tr>" for s in statuses]
    output.write_text("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>CIM Site Source Portfolio</title>
<style>body{font:16px/1.5 system-ui,sans-serif;color:#17233c;background:#f4f7fb;margin:0}
main{max-width:1200px;margin:auto;padding:28px}h1{color:#212878}section{background:white;padding:20px;
border-radius:12px;margin:18px 0;box-shadow:0 1px 5px #d7deea}table{border-collapse:collapse;width:100%}
th,td{border-bottom:1px solid #dde4ed;padding:9px;text-align:left;vertical-align:top}th{white-space:nowrap}
small{display:block;color:#667085}a{color:#212878}p{max-width:85ch}div.scroll{overflow:auto}</style></head><body><main>
<h1>CIM Site Source Portfolio</h1><p>Each site is reported separately. Sitemaps and GSC inspection are
snapshots collected during this run; GA4 uses the last completed Monday–Sunday week; CrUX returns historical
28-day windows. A missing property, key, or API response is shown as unavailable or failed,
never as zero traffic or zero indexed pages.</p>
<section><h2>Site coverage</h2><div class="scroll"><table><thead><tr><th>Site</th><th>Sitemap URLs</th>
<th>Latest sitemap lastmod</th><th>GA4 sessions</th><th>URLs inspected successfully</th>
<th>Sitemap</th><th>GSC inspection</th><th>CrUX</th><th>GA4</th></tr></thead><tbody>"""
        + "".join(site_rows) + """</tbody></table></div></section>
<section><h2>Source status</h2><div class="scroll"><table><thead><tr><th>Site</th><th>Source</th>
<th>Status</th><th>Rows</th><th>Detail</th></tr></thead><tbody>"""
        + "".join(status_rows) + """</tbody></table></div></section>
<section><h2>How to read this report</h2><p>Sitemap URLs are discovery candidates, not proof of indexing.
Sitemap <code>lastmod</code> values are publisher-provided and may be stale. GSC inspection describes Google's indexed version of a selected URL. CrUX history is real-user data
for the origin and uses overlapping 28-day periods. GA4 sessions are filtered to each site's hostname;
event names are listed without assuming which represent business outcomes.</p></section></main></body></html>""",
        encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("site_sources.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("portfolio_output"))
    parser.add_argument("--sources", default="sitemap,inspection,crux,ga4",
                        help="Comma-separated sources to run; sitemap is always included")
    parser.add_argument("--key-file", type=Path, default=Path("gsc-key.json"))
    args = parser.parse_args()
    selected = {s.strip() for s in args.sources.split(",") if s.strip()} | {"sitemap"}
    if selected - SOURCES:
        parser.error(f"Unknown sources: {', '.join(sorted(selected - SOURCES))}")
    sites = read_sites(args.config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    overview, statuses, url_rows, sitemap_rows, warning_rows = [], [], [], [], []
    inspection_rows, crux_rows, ga4_rows, event_rows = [], [], [], []
    for site in sites:
        print(f"Collecting {site.site_id}: {site.base_url}", flush=True)
        urls, maps, warnings = collect_sitemaps(site)
        url_rows.extend(urls)
        sitemap_rows.extend(maps)
        warning_rows.extend({"site_id": site.site_id, "source": "sitemap", "warning": warning}
                            for warning in warnings)
        good_maps = sum(row["status"] == "ok" for row in maps)
        sitemap_state = "ok" if good_maps and not warnings else "partial" if good_maps else "failed"
        statuses.append(_status(site, "sitemap", sitemap_state, len(urls),
                                f"{good_maps}/{len(maps)} files parsed; {len(warnings)} warnings"))
        site_inspections = []
        site_ga4 = []
        if "inspection" in selected:
            try:
                rows, status = collect_inspections(site, urls, args.key_file)
                site_inspections = rows
                inspection_rows.extend(rows); statuses.append(status)
            except Exception as exc:
                statuses.append(_status(site, "gsc_url_inspection", "failed",
                                        detail=f"{type(exc).__name__}; check property access and URL Inspection API"))
        if "crux" in selected:
            try:
                rows, status = collect_crux(site, os.getenv("CRUX_API_KEY") or os.getenv("PAGESPEED_API_KEY", ""))
                crux_rows.extend(rows); statuses.append(status)
            except Exception as exc:
                statuses.append(_status(site, "crux_history", "failed", detail=type(exc).__name__))
        if "ga4" in selected:
            try:
                rows, events, status = collect_ga4(site, args.key_file)
                site_ga4 = rows
                ga4_rows.extend(rows); event_rows.extend(events); statuses.append(status)
            except Exception as exc:
                statuses.append(_status(site, "ga4", "failed",
                                        detail=f"{type(exc).__name__}; check numeric property ID and service-account Viewer access"))
        overview.append({"site_id": site.site_id, "site_name": site.site_name,
                         "base_url": site.base_url, "sitemap_urls": len(urls),
                         "latest_sitemap_lastmod": max((row["lastmod"][:10] for row in urls), default=""),
                         "ga4_sessions": site_ga4[0]["sessions"] if site_ga4 else "",
                         "inspected_ok": sum(row["status"] == "ok" for row in site_inspections) if site_inspections else "",
                         "gsc_property": site.gsc_property, "ga4_property_id": site.ga4_property_id,
                         "ga4_measurement_id": site.ga4_measurement_id, "collected_at_utc": now})
    out = args.output_dir
    write_csv(out / "site_overview.csv", ["site_id", "site_name", "base_url", "sitemap_urls",
              "latest_sitemap_lastmod", "ga4_sessions", "inspected_ok", "gsc_property",
              "ga4_property_id", "ga4_measurement_id", "collected_at_utc"], overview)
    write_csv(out / "site_source_status.csv", ["site_id", "source", "status", "record_count", "detail"], statuses)
    write_csv(out / "site_sitemaps.csv", ["site_id", "sitemap_url", "final_url", "kind", "entry_count", "status"], sitemap_rows)
    write_csv(out / "site_sitemap_urls.csv", ["site_id", "url", "raw_url", "lastmod", "source_sitemap"], url_rows)
    if warning_rows:
        write_csv(out / "site_source_warnings.csv", ["site_id", "source", "warning"], warning_rows)
    if inspection_rows:
        write_csv(out / "site_url_inspection.csv", ["site_id", "url", "status", "verdict", "coverage_state",
                  "google_canonical", "user_canonical", "last_crawl_time", "page_fetch_state"], inspection_rows)
    if crux_rows:
        write_csv(out / "site_crux_history.csv", ["site_id", "origin", "form_factor", "metric", "period_start",
                  "period_end", "p75_raw"], crux_rows)
    if ga4_rows:
        write_csv(out / "site_ga4_weekly.csv", ["site_id", "host", "ga4_property_id", "period_start", "period_end",
                  "sessions", "active_users"], ga4_rows)
    if event_rows:
        write_csv(out / "site_ga4_events.csv", ["site_id", "host", "ga4_property_id", "period_start", "period_end",
                  "event_name", "event_count"], event_rows)
    render_html(sites, overview, statuses, out / "site_source_portfolio.html")
    for status in statuses:
        if status["status"] in {"failed", "partial", "empty"} or status["status"].startswith("http_"):
            print(f"::warning title=Site Source Portfolio::{status['site_id']} {status['source']}: "
                  f"{status['status']} ({status['detail']})")
    print(f"Wrote {len(url_rows)} sitemap URLs for {len(sites)} sites to {out}")
    return 1 if all(s["status"] == "failed" for s in statuses if s["source"] == "sitemap") else 0


if __name__ == "__main__":
    raise SystemExit(main())
