from dataclasses import dataclass, field, asdict
from typing import Literal, List
import hashlib
import json
from datetime import datetime

def _get_today() -> str:
    return datetime.now().date().isoformat()

def make_task_id(url: str, issue_type: str) -> str:
    raw = f"{url}::{issue_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]

@dataclass
class SEOTask:
    task_id: str
    bucket: Literal["technical", "content"]
    priority: Literal["high", "medium", "low"]
    issue_type: str
    url: str
    title: str
    action: str
    context: str
    source_report: str
    effort: Literal["low", "medium", "high"]
    detected_at: str = field(default_factory=_get_today)
    impact_score: float = field(default=0.0)

TaskList = List[SEOTask]

TECHNICAL_ISSUE_TYPES = {
    "broken_link", "cwv_fail", "orphan_page", "redirect_chain",
    "slow_lcp", "cls_issue", "server_error"
}

CONTENT_ISSUE_TYPES = {
    "content_decay", "rank_drop", "low_ctr", "internal_link_gap",
    "missing_cta", "thin_content", "ai_snippet_fail"
}

def to_dict(task: SEOTask) -> dict:
    return asdict(task)

def from_dict(d: dict) -> SEOTask:
    d.setdefault("detected_at", _get_today())
    d.setdefault("impact_score", 0.0)
    return SEOTask(**d)

def to_monday_payload(task: SEOTask) -> dict:
    column_values = {
        "text0": str(task.url),
        "status": {"label": str(task.issue_type)},
        "status4": {"label": str(task.priority)},
        "long_text": str(task.action),
        "long_text7": str(task.context),
        "status2": {"label": str(task.effort)},
        "date4": {"date": str(task.detected_at)},
        "numbers": str(round(task.impact_score, 2)),
        "text8": str(task.task_id)
    }
    
    return {
        "name": str(task.title),
        "column_values": json.dumps(column_values)
    }
