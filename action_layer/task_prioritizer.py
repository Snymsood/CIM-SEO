from datetime import datetime, date
from typing import Tuple

from action_layer.task_schema import SEOTask, TaskList

ISSUE_WEIGHTS = {
    "broken_link":        1.0,
    "server_error":       1.0,
    "cwv_fail":           0.9,
    "slow_lcp":           0.9,
    "cls_issue":          0.8,
    "redirect_chain":     0.7,
    "content_decay":      0.8,
    "rank_drop":          0.7,
    "orphan_page":        0.6,
    "internal_link_gap":  0.5,
    "low_ctr":            0.5,
    "thin_content":       0.4,
    "missing_cta":        0.3,
    "ai_snippet_fail":    0.4,
}

DEFAULT_ISSUE_WEIGHT = 0.3

def _recency_score(detected_at: str) -> float:
    try:
        detected = datetime.strptime(detected_at, "%Y-%m-%d").date()
        days_old = (date.today() - detected).days
        return max(0.0, 1.0 - (days_old / 14.0))
    except ValueError:
        return 0.5  # fallback for malformed dates

def prioritize(tasks: TaskList) -> TaskList:
    """
    Score and sort a list of SEOTask objects.
    Mutates impact_score in-place, returns sorted list.
    """
    priority_map = {"high": 1.0, "medium": 0.5, "low": 0.2}
    effort_map = {"low": 1.0, "medium": 0.5, "high": 0.2}
    
    result = list(tasks)
    for task in result:
        p_score = priority_map.get(task.priority, 0.2)
        i_weight = ISSUE_WEIGHTS.get(task.issue_type, DEFAULT_ISSUE_WEIGHT)
        e_inversed = effort_map.get(task.effort, 0.5)
        r_score = _recency_score(task.detected_at)
        
        impact = (0.40 * p_score +
                  0.25 * i_weight +
                  0.20 * e_inversed +
                  0.15 * r_score)
        task.impact_score = round(impact, 4)
        
    sort_priority = {"high": 3, "medium": 2, "low": 1}
    result.sort(key=lambda t: (
        t.impact_score,
        sort_priority.get(t.priority, 1),
        t.detected_at
    ), reverse=True)
    return result

def split_by_bucket(tasks: TaskList) -> Tuple[TaskList, TaskList]:
    """
    Returns (technical_tasks, content_tasks), each sorted by impact_score desc.
    Call after prioritize().
    """
    tech = [t for t in tasks if t.bucket == "technical"]
    cont = [t for t in tasks if t.bucket == "content"]
    
    tech.sort(key=lambda t: t.impact_score, reverse=True)
    cont.sort(key=lambda t: t.impact_score, reverse=True)
    return tech, cont

def top_tasks(tasks: TaskList, n: int = 10) -> TaskList:
    """Return the top-n tasks by impact_score. Used by digest_generator."""
    sorted_tasks = sorted(tasks, key=lambda t: t.impact_score, reverse=True)
    return sorted_tasks[:n]
