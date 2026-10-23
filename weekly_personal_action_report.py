#!/usr/bin/env python3
"""Build an evidence-linked five-action work plan from validated weekly reports."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse


REQUIRED_SOURCES = {"gsc-weekly-report", "ga4-weekly-report"}
ACTION_SOURCE_ARTIFACT = {
    "Keyword Ranking Report": "keyword-ranking-review",
    "Anomaly Detection": "ga4-weekly-report",
    "Site Speed Report": "site-speed-monitoring",
    "GSC CTR Gap Analysis": "gsc-weekly-report",
    "Broken Link Report": "broken-link-check",
    "Internal Linking Audit": "internal-linking-audit",
    "Content Decay Detection": "content-audit-schedule",
}


def _rows(root: Path, name: str) -> list[dict]:
    for path in (root / f"{name}.csv", root / "normalized" / f"{name}_normalized.csv"):
        if path.is_file():
            with path.open(newline="", encoding="utf-8-sig") as stream:
                return list(csv.DictReader(stream))
    return []


def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def _url(value: object) -> str:
    value = str(value or "")
    return value if urlparse(value).scheme in {"http", "https"} else ""


def _match_page(rows: list[dict], page: str, field: str = "page") -> dict:
    return next((row for row in rows if str(row.get(field, "")).rstrip("/") == page.rstrip("/")), {})


def _candidate(action: dict, root: Path) -> dict | None:
    title = str(action.get("action", ""))
    source = str(action.get("source", ""))
    score = _number(action.get("priority_score"))
    evidence = str(action.get("evidence", ""))
    details: dict = {}

    if source == "Keyword Ranking Report":
        found = re.search(r"'([^']+)'", title)
        keyword = found.group(1) if found else ""
        row = next((r for r in _rows(root, "tracked_keywords_comparison") if r.get("keyword", "").lower() == keyword.lower()), {})
        page = _url(row.get("top_page"))
        if not row or not page:
            return None
        title = f"Investigate the ranking loss for “{keyword}”"
        evidence = (f"Average position {_number(row.get('position_previous')):.1f} → "
                    f"{_number(row.get('position_current')):.1f}; "
                    f"{_number(row.get('clicks_current')):,.0f} clicks and "
                    f"{_number(row.get('impressions_current')):,.0f} impressions this week.")
        if _number(row.get("impressions_current")) < 50:
            score -= 18
            evidence += " Low impression volume limits the likely short-term impact."
        steps = ["Compare this query and landing page in GSC by country and device; confirm the preferred URL and index status.",
                 "Review the page against current search results and update stale event information, title, or internal links only where the evidence supports a change."]
        verify = "Check the query’s position and clicks in the next GSC weekly report."
        details = {"keyword": keyword, "page": page}
        links = [("Affected page", page)]
    elif source == "Anomaly Detection" and "sessions" in title.lower():
        anomaly = next((r for r in _rows(root, "weekly_seo_anomalies") if r.get("metric") == "sessions"), {})
        if not anomaly:
            return None
        current, previous = _number(anomaly.get("current_value")), _number(anomaly.get("previous_value"))
        pages = [r for r in _rows(root, "ga4_pages_comparison") if str(r.get("landingPage", "")).startswith("/")]
        pages.sort(key=lambda r: _number(r.get("sessions_change")))
        error_route = next((r for r in pages if r.get("landingPage", "").lower() in {"/404", "/404/"}), {})
        content_pages = [r for r in pages if r.get("landingPage", "").lower() not in {"/404", "/404/", "/unsubscribe"}]
        loser = content_pages[0] if content_pages and _number(content_pages[0].get("sessions_change")) < 0 else {}
        page = _url(loser.get("landingPage_canonical")) if loser else ""
        title = "Diagnose the main-site GA4 session decline"
        evidence = f"{current:,.0f} vs {previous:,.0f} sessions ({(current / previous - 1):+.1%} week over week)." if previous else f"{current:,.0f} sessions this week."
        if error_route:
            evidence += (f" The /404 landing route fell from {_number(error_route.get('sessions_previous')):,.0f} "
                         f"to {_number(error_route.get('sessions_current')):,.0f} sessions, so the prior-week baseline needs checking.")
        if page:
            evidence += f" Largest other URL loss: {page}, {_number(loser.get('sessions_change')):+,.0f} sessions."
        steps = ["Break the decline down by channel, landing page, and device in GA4; compare organic clicks in GSC to separate demand changes from tracking changes.",
                 "Audit the prior-week /404 traffic and tag firing for bot, routing, or consent effects before changing content."]
        verify = "Confirm the cause in GA4/GSC and compare sessions in the next completed week."
        details = {"current_sessions": current, "previous_sessions": previous, "largest_losing_page": page}
        links = [("Largest losing page", page)] if page else []
    elif source == "Site Speed Report" and title.startswith("Improve mobile PageSpeed for:"):
        page = _url(title.split("for:", 1)[1].strip())
        row = next((r for r in _rows(root, "site_speed_latest_snapshot") if r.get("page") == page and r.get("strategy") == "mobile"), {})
        if not row:
            return None
        issues = [r for r in _rows(root, "site_speed_opportunities") if r.get("page") == page]
        issues.sort(key=lambda r: _number(r.get("savings_ms")), reverse=True)
        opportunity = issues[0] if issues else {}
        title = "Improve the homepage’s mobile lab speed"
        evidence = f"PageSpeed lab score {_number(row.get('performance_score')):.0f}/100; lab LCP {_number(row.get('lcp_lab_ms')) / 1000:.1f}s."
        if opportunity:
            evidence += f" Largest listed opportunity: {opportunity.get('issue')} (~{_number(opportunity.get('savings_ms')):,.0f} ms estimated savings)."
        if row.get("cwv_pass") == "True":
            evidence += " Field Core Web Vitals pass; this is a lab performance task."
        steps = ["Open the mobile PageSpeed diagnostics and capture the slow resource or script behind the largest opportunity.",
                 "Give the web team a focused ticket to defer/remove that resource; compare repeat lab runs before and after deployment."]
        verify = "Recheck mobile lab LCP and score; keep field Core Web Vitals separately labeled."
        details = {"page": page, "lab_score": _number(row.get("performance_score"))}
        links = [("Page", page)]
    elif source == "GSC CTR Gap Analysis":
        found = re.search(r"'([^']+)'", title)
        keyword = found.group(1) if found else ""
        mapping = [r for r in _rows(root, "keyword_page_mapping") if r.get("query", "").lower() == keyword.lower()]
        mapping.sort(key=lambda r: _number(r.get("impressions")), reverse=True)
        page = _url(mapping[0].get("page")) if mapping else ""
        if not page:
            return None
        title = f"Review the search snippet for “{keyword}”"
        evidence = f"Mapped page: {page}. {evidence.rstrip('. ')}; the click gain is a scenario, not a forecast."
        steps = ["Inspect the actual SERP and GSC query/page pair; check whether sitelinks or brand intent explain the measured CTR.",
                 "If the snippet is weak, revise the page title/meta to describe the page accurately, then request indexing."]
        verify = "Compare query CTR and clicks over the next two comparable weeks."
        details = {"keyword": keyword, "page": page}
        links = [("Mapped page", page)]
        if keyword.lower() == "cim":
            score -= 8  # Broad branded queries need SERP review before editing.
    elif source == "Broken Link Report":
        broken = [r for r in _rows(root, "broken_link_results") if r.get("issue_type") == "broken"]
        grouped: dict[str, list[dict]] = {}
        for row in broken:
            target = _url(row.get("target_url"))
            if target:
                grouped.setdefault(target, []).append(row)
        if not grouped:
            return None
        # Prefer an active portfolio site when counts are similar.
        target, occurrences = max(grouped.items(), key=lambda pair: (len(pair[1]) + (8 if "magazine.cim.org" in pair[0] else 0), len(pair[1])))
        source_page = _url(occurrences[0].get("source_url"))
        title = "Repair a repeated broken link"
        evidence = f"{len(occurrences)} source-link occurrences point to {target}; example source: {source_page}."
        steps = ["Check whether the target should exist; restore it or choose the closest live replacement.",
                 "Update the source links and retest the target and source page; add a redirect only when the replacement matches intent."]
        verify = "The target or replacement returns 200, and the next link crawl no longer flags those occurrences."
        details = {"target": target, "example_source": source_page, "occurrences": len(occurrences)}
        links = [("Broken target", target), ("Example source", source_page)]
        score += 8
    elif source == "Internal Linking Audit":
        rows = [r for r in _rows(root, "internal_linking_priority_targets") if r.get("flag_low_inlinks", "").lower() == "true"]
        if not rows:
            return None
        target = _url(rows[0].get("priority_target"))
        if not target:
            return None
        title = "Verify and strengthen links to a priority registration page"
        evidence = f"The crawl found {_number(rows[0].get('inlinks')):.0f} inlinks to {target}; crawl coverage may be incomplete."
        steps = ["Confirm this is the current registration destination and that the crawler covered its referring site.",
                 "If valid, add contextual links from current event pages and navigation where useful to visitors."]
        verify = "Re-crawl and confirm the page is reachable through internal links."
        details = {"target": target}
        links = [("Priority target", target)]
        score -= 10
    elif source == "Content Decay Detection":
        match = next((r for r in _rows(root, "weekly_content_decay_candidates") if str(r.get("page", ""))[:50] in title), {})
        page = _url(match.get("page"))
        if not page:
            return None
        title = f"Review declining content: {urlparse(page).path}"
        evidence = f"{_number(match.get('current_clicks')):.0f} vs {_number(match.get('previous_clicks')):.0f} clicks; {_number(match.get('current_impressions')):,.0f} current impressions."
        steps = ["Check GSC query losses and current SERP intent for this page.",
                 "Refresh only outdated information, title, or internal links supported by that review."]
        verify = "Compare clicks and CTR over the next two completed weeks."
        details = {"page": page}
        links = [("Page", page)]
    else:
        return None

    return {"title": title, "category": action.get("category", ""), "score": round(score, 1),
            "impact": action.get("estimated_impact", ""), "effort": action.get("effort", ""),
            "confidence": action.get("confidence", ""), "source": source, "evidence": evidence,
            "steps": steps, "verify": verify, "links": [(label, link) for label, link in links if link],
            "details": details}


def build_report(root: Path) -> dict:
    ledger = json.loads((root / "source_report_runs.json").read_text(encoding="utf-8"))
    period_ids = {str(r.get("period_id", "")) for r in ledger}
    period_id = next(iter(period_ids)) if len(period_ids) == 1 else ""
    manifest_path = root / "report_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("period_id") != period_id:
            raise ValueError("Intelligence manifest and source runs have different periods")
    if not period_id or not REQUIRED_SOURCES.issubset({r.get("artifact") for r in ledger}):
        raise ValueError("Current GSC and GA4 source runs are required")
    dates = period_id.split("_")
    if len(dates) != 2 or not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in dates):
        raise ValueError("Source runs have an invalid reporting period")
    queue = json.loads((root / "weekly_seo_action_queue.json").read_text(encoding="utf-8"))
    candidates = [_candidate(action, root) for action in queue]
    candidates = [candidate for candidate in candidates if candidate]
    candidates.sort(key=lambda item: item["score"], reverse=True)
    selected = candidates[:5]
    if not selected:
        raise ValueError("No evidence-backed actions could be built from this week's source reports")
    source_lookup = {record.get("artifact"): record for record in ledger}
    for action in selected:
        artifact = ACTION_SOURCE_ARTIFACT.get(action["source"])
        run_id = str(source_lookup.get(artifact, {}).get("run_id", ""))
        if run_id.isdigit():
            repository = os.environ.get("GITHUB_REPOSITORY", "Snymsood/CIM-SEO")
            action["source_run_url"] = f"https://github.com/{repository}/actions/runs/{run_id}"
    site_watchlist = []
    for row in _rows(root, "site_portfolio_trends"):
        if row.get("metric") == "GA4 sessions" and row.get("site_id"):
            site_watchlist.append({"site_id": row["site_id"], "site_name": row.get("site_name", row["site_id"]),
                                   "current": _number(row.get("current")), "previous": _number(row.get("previous")),
                                   "change_pct": _number(row.get("change_pct")) if row.get("change_pct") else None})
    ai_analysis = None
    ai_path = root / "weekly_ai_analysis.json"
    if ai_path.is_file():
        ai_analysis = json.loads(ai_path.read_text(encoding="utf-8"))
        if ai_analysis.get("period_id") != period_id:
            raise ValueError("AI analysis and source runs have different periods")
    return {"period_start": dates[0], "period_end": dates[1],
            "period_id": period_id, "source_runs": ledger, "actions": selected,
            "candidate_count": len(candidates), "source_action_count": len(queue),
            "site_watchlist": site_watchlist, "ai_analysis": ai_analysis}


def render_html(report: dict) -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    cards = []
    for index, action in enumerate(report["actions"], 1):
        steps = "".join(f"<li>{esc(step)}</li>" for step in action["steps"])
        links = " · ".join(f'<a href="{esc(url)}">{esc(label)}</a>' for label, url in action["links"])
        if action.get("source_run_url"):
            links += f' · <a href="{esc(action["source_run_url"])}">Source run</a>'
        cards.append(f'<section class="card"><div class="eyebrow">ACTION {index} · {esc(action["category"])} · SCORE {esc(action["score"])}</div>'
                     f'<h2>{esc(action["title"])}</h2><p><strong>Why now:</strong> {esc(action["evidence"])}</p>'
                     f'<p><strong>Do this:</strong></p><ol>{steps}</ol><p><strong>Check:</strong> {esc(action["verify"])}</p>'
                     f'<p class="meta">Impact {esc(action["impact"])} · Effort {esc(action["effort"])} · '
                     f'Confidence {esc(action["confidence"])} · Source {esc(action["source"])}</p>'
                     f'<p>{links}</p></section>')
    coverage = ", ".join(sorted({str(r.get("report_name", r.get("artifact"))) for r in report["source_runs"]}))
    watchlist = ""
    if report.get("site_watchlist"):
        rows = "".join(
            f'<tr><td>{esc(site["site_name"])}</td><td>{site["current"]:,.0f}</td>'
            f'<td>{site["previous"]:,.0f}</td><td>{site["change_pct"]:+.1%}</td></tr>'
            if site["change_pct"] is not None else
            f'<tr><td>{esc(site["site_name"])}</td><td>{site["current"]:,.0f}</td>'
            f'<td>{site["previous"]:,.0f}</td><td>—</td></tr>'
            for site in report["site_watchlist"])
        watchlist = ("<section class=\"card\"><h2>Four-site traffic watchlist</h2>"
                     "<p>GA4 sessions, distinct completed Monday–Sunday weeks. These site signals are context for the actions above.</p>"
                     "<table width=\"100%\" cellspacing=\"0\" cellpadding=\"5\"><thead><tr><th align=\"left\">Site</th>"
                     "<th align=\"right\">Current</th><th align=\"right\">Previous</th><th align=\"right\">Change</th>"
                     f"</tr></thead><tbody>{rows}</tbody></table></section>")
    ai_section = ""
    analysis = report.get("ai_analysis")
    if analysis:
        cover = analysis.get("coverage", {})
        status = str(analysis.get("status", "unavailable"))
        summary = str(analysis.get("summary", ""))
        patterns = analysis.get("patterns", [])[:4]
        detail = (f"{cover.get('successful_categories', 0)}/{cover.get('total_categories', 0)} "
                  f"domain reviews; {cover.get('files', 0)} files and {cover.get('rows', 0):,} file rows profiled. "
                  "File rows may overlap and are not unique events.")
        items = "".join(
            f'<li><strong>{esc(item.get("title", ""))}</strong> — {esc(item.get("insight", ""))}'
            f'<br><strong>Check or do:</strong> {esc(item.get("next_step", ""))}'
            f'<br><span class="meta">Evidence: {esc(", ".join(item.get("evidence_ids", [])[:3]))} · '
            f'Confidence: {esc(item.get("confidence", ""))}</span></li>' for item in patterns)
        gaps = "".join(f"<li>{esc(gap)}</li>" for gap in analysis.get("data_gaps", [])[:3])
        ai_section = (f'<section class="card"><div class="eyebrow">CROSS-REPORT AI READOUT · {esc(status.upper())}</div>'
                      f'<h2>Patterns across the reports</h2><p>AI-generated hypotheses to verify against the linked source data.</p>'
                      f'<p>{esc(summary or "Analysis unavailable for this run.")}</p>'
                      + (f'<ol>{items}</ol>' if items else "")
                      + (f'<p><strong>Data gaps</strong></p><ul>{gaps}</ul>' if gaps else "")
                      + f'<p class="meta">{esc(detail)} Model: {esc(analysis.get("model", ""))}.</p></section>')
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Weekly SEO action plan</title><style>body{font-family:Arial,sans-serif;color:#182c3a;max-width:760px;margin:auto;padding:24px;background:#f5f8fa}"
            ".card{background:#fff;border:1px solid #dce5e9;border-radius:10px;padding:20px;margin:18px 0}.eyebrow{font-size:12px;font-weight:700;color:#116c70;letter-spacing:.05em}"
            "h1{font-size:29px}h2{font-size:20px}p,li{line-height:1.5}.meta,.foot{color:#52626b;font-size:13px}a{color:#075d9b}</style></head><body>"
            f'<h1>Your weekly SEO action plan</h1><p>Completed week: {esc(report["period_start"])} to {esc(report["period_end"])}. '
            f'{len(report["actions"])} evidence-backed priorities from {len(report["source_runs"])} validated source reports.</p>'
            + "".join(cards) + watchlist + ai_section
            + f'<p class="foot">Selection: ranked intelligence queue with source-level checks; uncertain claims are framed as verification tasks. '
              f'Coverage: {esc(coverage)}. A source can contribute context without generating a top-five action.</p></body></html>')


def render_text(report: dict) -> str:
    lines = [f"Weekly SEO action plan — {report['period_start']} to {report['period_end']}", ""]
    for index, action in enumerate(report["actions"], 1):
        lines += [f"{index}. {action['title']}", f"Why now: {action['evidence']}"]
        lines += [f"   {step}" for step in action["steps"]]
        lines += [f"Check: {action['verify']}"]
        lines += [f"{label}: {url}" for label, url in action["links"]]
        if action.get("source_run_url"):
            lines += [f"Source run: {action['source_run_url']}"]
        lines += [""]
    if report.get("site_watchlist"):
        lines += ["Four-site traffic watchlist (GA4 sessions):"]
        for site in report["site_watchlist"]:
            change = f"{site['change_pct']:+.1%}" if site["change_pct"] is not None else "unavailable"
            lines += [f"- {site['site_name']}: {site['current']:,.0f} vs {site['previous']:,.0f} ({change})"]
        lines += [""]
    analysis = report.get("ai_analysis")
    if analysis:
        cover = analysis.get("coverage", {})
        lines += [f"Cross-report AI readout ({analysis.get('status', 'unavailable')}; verify hypotheses against source data):",
                  str(analysis.get("summary") or "Analysis unavailable for this run.")]
        for item in analysis.get("patterns", [])[:4]:
            lines += [f"- {item.get('title', '')}: {item.get('insight', '')}",
                      f"  Check or do: {item.get('next_step', '')}",
                      f"  Evidence: {', '.join(item.get('evidence_ids', [])[:3])}; confidence: {item.get('confidence', '')}"]
        for gap in analysis.get("data_gaps", [])[:3]:
            lines += [f"Data gap: {gap}"]
        lines += [f"Coverage: {cover.get('successful_categories', 0)}/{cover.get('total_categories', 0)} domain reviews; "
                  f"{cover.get('files', 0)} files and {cover.get('rows', 0):,} file rows profiled "
                  "(file rows may overlap).", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    report = build_report(args.root)
    (args.root / "weekly_personal_action_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.root / "weekly_personal_action_report.html").write_text(render_html(report), encoding="utf-8")
    (args.root / "weekly_personal_action_report.txt").write_text(render_text(report), encoding="utf-8")
    print(f"Generated {len(report['actions'])} personal actions for {report['period_id']}.")


if __name__ == "__main__":
    main()
