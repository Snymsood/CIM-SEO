import json
import os
from typing import List
from urllib.parse import urlparse

from action_layer.task_schema import (
    SEOTask, make_task_id, TaskList,
    TECHNICAL_ISSUE_TYPES, CONTENT_ISSUE_TYPES
)

def _url_path(url: str) -> str:
    """Extract path from URL for use in titles. Returns last 60 chars of path."""
    path = urlparse(url).path or url
    return path[-60:] if len(path) > 60 else path

def _extract_action_queue(items: list, run_date: str) -> TaskList:
    """Maps action_queue items → SEOTask."""
    tasks = []
    tech_patterns = ["broken", "404", "500", "speed", "lcp", "cls", "orphan", "redirect", "crawl"]
    for item in items:
        issue = item.get("issue", "").lower()
        detail = item.get("detail", "")
        url = item.get("url", "")
        source = item.get("source", "")
        
        is_tech = any(pat in issue for pat in tech_patterns)
        bucket = "technical" if is_tech else "content"
        
        if "broken" in issue or "404" in issue or "500" in issue:
            issue_type = "broken_link"
        elif "orphan" in issue:
            issue_type = "orphan_page"
        elif "speed" in issue or "lcp" in issue:
            issue_type = "cwv_fail"
        elif "cls" in issue:
            issue_type = "cls_issue"
        elif "redirect" in issue:
            issue_type = "redirect_chain"
        elif "decay" in issue:
            issue_type = "content_decay"
        elif "rank" in issue or "position" in issue:
            issue_type = "rank_drop"
        elif "ctr" in issue:
            issue_type = "low_ctr"
        elif "link" in issue and "broken" not in issue:
            issue_type = "internal_link_gap"
        else:
            issue_type = "broken_link" if bucket == "technical" else "content_decay"
            
        priority = "high" if "high" in detail.lower() or "critical" in detail.lower() else "medium"
        effort = "medium"
        
        tasks.append(SEOTask(
            task_id=make_task_id(url, issue_type),
            bucket=bucket,
            priority=priority,
            issue_type=issue_type,
            url=url,
            title=item.get("issue", "")[:80],
            action=("Investigate and fix: " + detail)[:200],
            context=detail,
            source_report=source,
            detected_at=run_date,
            effort=effort
        ))
    return tasks

def _extract_anomalies(items: list, run_date: str) -> TaskList:
    """Maps anomaly_report items → SEOTask."""
    tasks = []
    for item in items:
        metric = item.get("metric", "")
        source = item.get("source", "").lower()
        url = item.get("url", "")
        delta = item.get("delta", 0.0)
        threshold = item.get("threshold", 0.0)
        
        bucket = "technical" if "speed" in source or "cwv" in source else "content"
        
        if metric in ("sessions", "clicks", "position"):
            issue_type = "rank_drop"
        elif metric == "ctr":
            issue_type = "low_ctr"
        elif metric in ("lcp", "cls"):
            issue_type = "cwv_fail"
        else:
            issue_type = "rank_drop"
            
        abs_delta = abs(delta)
        if abs_delta > 0.40:
            priority = "high"
        elif abs_delta > 0.20:
            priority = "medium"
        else:
            priority = "low"
            
        effort = "medium"
        
        tasks.append(SEOTask(
            task_id=make_task_id(url, issue_type),
            bucket=bucket,
            priority=priority,
            issue_type=issue_type,
            url=url,
            title=f"Anomaly: {metric} dropped {abs_delta*100:.0f}% on {_url_path(url)}",
            action=f"Investigate {metric} decline on this page. Delta: {delta:.0%} vs threshold {threshold:.0%}",
            context=f"{metric} delta: {delta:.2%}, threshold was {threshold:.2%}, source: {item.get('source')}",
            source_report=item.get("source", ""),
            detected_at=run_date,
            effort=effort
        ))
    return tasks

def _extract_content_decay(items: list, run_date: str) -> TaskList:
    """Maps content_decay_candidates → SEOTask."""
    tasks = []
    for item in items:
        url = item.get("url", "")
        delta_pct = item.get("traffic_delta_pct", 0.0)
        sessions = item.get("current_sessions", 0)
        keyword = item.get("top_keyword", "")
        
        priority = "high" if delta_pct < -50 else ("medium" if delta_pct < -25 else "low")
        effort = "low" if sessions < 100 else ("medium" if sessions < 500 else "high")
        
        tasks.append(SEOTask(
            task_id=make_task_id(url, "content_decay"),
            bucket="content",
            priority=priority,
            issue_type="content_decay",
            url=url,
            title=f"Content decay: {_url_path(url)}",
            action=f"Refresh or archive this page. Traffic down {abs(delta_pct):.0f}%, currently {sessions} sessions/mo. Top keyword: '{keyword}'",
            context=f"Sessions: {sessions}/mo, traffic delta: {delta_pct:.1f}%, top keyword: {keyword}",
            source_report="content_audit_schedule_report",
            detected_at=run_date,
            effort=effort
        ))
    return tasks

def _deduplicate(tasks: TaskList) -> TaskList:
    """Remove duplicate task_ids, keeping highest priority."""
    priority_map = {"high": 3, "medium": 2, "low": 1}
    deduped = {}
    for task in tasks:
        tid = task.task_id
        if tid not in deduped:
            deduped[tid] = task
        else:
            if priority_map.get(task.priority, 1) > priority_map.get(deduped[tid].priority, 1):
                deduped[tid] = task
    return list(deduped.values())

def extract_tasks(intelligence_path: str) -> TaskList:
    """Load weekly_intelligence.json and return a flat list of SEOTask objects."""
    if not os.path.exists(intelligence_path):
        raise FileNotFoundError(f"Intelligence file not found: {intelligence_path}")
        
    with open(intelligence_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    run_date = data.get("run_date", "")
    tasks = []
    
    aq = data.get("action_queue", [])
    aq_tasks = _extract_action_queue(aq, run_date)
    print(f"[extractor] action_queue: {len(aq_tasks)} tasks")
    tasks.extend(aq_tasks)
    
    ar = data.get("anomaly_report", [])
    ar_tasks = _extract_anomalies(ar, run_date)
    print(f"[extractor] anomaly_report: {len(ar_tasks)} tasks")
    tasks.extend(ar_tasks)
    
    cd = data.get("content_decay_candidates", [])
    cd_tasks = _extract_content_decay(cd, run_date)
    print(f"[extractor] content_decay_candidates: {len(cd_tasks)} tasks")
    tasks.extend(cd_tasks)
    
    return _deduplicate(tasks)
