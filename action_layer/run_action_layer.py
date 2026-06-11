import json
import os
import sys
from datetime import date
from pathlib import Path

from action_layer.task_extractor import extract_tasks
from action_layer.task_prioritizer import prioritize, split_by_bucket
from action_layer.task_schema import to_dict, TaskList

def _build_dashboard(tasks: TaskList, run_date: str, output_path: str) -> str:
    """
    1. Load the template from action_layer/dashboard/index.html
    2. Serialize tasks to JSON with wrapper
    3. Replace __TASK_DATA_PLACEHOLDER__ with the JSON string
    4. Write the result to output_path
    5. Return output_path
    """
    template_path = Path(__file__).parent / "dashboard" / "index.html"
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()
        
    dashboard_json = json.dumps({
        "tasks": [to_dict(t) for t in tasks],
        "run_date": run_date
    })
    html = html.replace("__TASK_DATA_PLACEHOLDER__", dashboard_json)
    
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
        
    return str(out_path)

def run(
    intelligence_path: str = "outputs/weekly_intelligence.json",
    dashboard_output_path: str = None
) -> dict:
    """
    Full ActionLayer pipeline orchestrator.
    """
    with open(intelligence_path, "r", encoding="utf-8") as f:
        intel = json.load(f)
        
    wins = intel.get("wins", [])
    run_date = intel.get("run_date", str(date.today()))
    print(f"[action_layer] Starting run for {run_date}")
    
    try:
        tasks = extract_tasks(intelligence_path)
        tasks = prioritize(tasks)
        technical, content = split_by_bucket(tasks)
        print(f"[action_layer] Extracted {len(tasks)} tasks")
        print(f"[action_layer] Prioritized: {len(technical)} technical, {len(content)} content")
    except Exception as e:
        print(f"[action_layer] Extractor/Prioritizer failed: {e}")
        raise
        
    monday_result = {"created": 0, "skipped": 0, "errors": -1}
    try:
        from action_layer.monday_task_publisher import publish_tasks
        monday_result = publish_tasks(technical, content)
    except Exception as e:
        print(f"[action_layer] Monday.com step failed: {e}")
    print(f"[action_layer] Monday.com: {monday_result}")
    
    if dashboard_output_path is None:
        dashboard_output_path = os.environ.get("ACTION_DASHBOARD_OUTPUT_PATH", "outputs/action_dashboard.html")
        
    dash_path = ""
    try:
        dash_path = _build_dashboard(tasks, run_date, dashboard_output_path)
        print(f"[action_layer] Dashboard written to {dash_path}")
    except Exception as e:
        print(f"[action_layer] Dashboard build failed: {e}")
        
    digest_result = {"groq_ok": False, "email_ok": False, "slack_ok": False}
    try:
        from action_layer.digest_generator import generate_and_send_digest
        raw_digest = generate_and_send_digest(tasks, wins, run_date)
        digest_result = {k: v for k, v in raw_digest.items() if k != "body"}
    except Exception as e:
        print(f"[action_layer] Digest step failed: {e}")
    print(f"[action_layer] Digest: {digest_result}")
        
    return {
        "tasks_total": len(tasks),
        "tasks_technical": len(technical),
        "tasks_content": len(content),
        "monday": monday_result,
        "digest": digest_result,
        "dashboard_path": dash_path
    }

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "outputs/weekly_intelligence.json"
    result = run(intelligence_path=path)
    print(f"\n[action_layer] Run complete: {result}")
