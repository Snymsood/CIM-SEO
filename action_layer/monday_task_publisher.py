import os
import json
import time
import requests
from typing import Dict

from action_layer.task_schema import SEOTask, TaskList, to_monday_payload
from monday_utils import MONDAY_API_URL

MONDAY_TECHNICAL_BOARD_ID = os.environ.get("MONDAY_TECHNICAL_BOARD_ID")
MONDAY_CONTENT_BOARD_ID = os.environ.get("MONDAY_CONTENT_BOARD_ID")
MONDAY_API_TOKEN = os.environ.get("MONDAY_API_TOKEN")

if not MONDAY_TECHNICAL_BOARD_ID:
    raise EnvironmentError("Missing MONDAY_TECHNICAL_BOARD_ID in env")
if not MONDAY_CONTENT_BOARD_ID:
    raise EnvironmentError("Missing MONDAY_CONTENT_BOARD_ID in env")

def _board_id(bucket: str) -> str:
    return MONDAY_TECHNICAL_BOARD_ID if bucket == "technical" else MONDAY_CONTENT_BOARD_ID

def _make_request(query: str, variables: dict = None) -> dict:
    if not MONDAY_API_TOKEN:
        return {"data": {}}
        
    headers = {
        "Authorization": MONDAY_API_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
        
    resp = requests.post(MONDAY_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday API Error: {data['errors']}")
    return data

def _fetch_existing_task_ids(board_id: str) -> Dict[str, str]:
    query = """
    query ($board_id: [ID!]) {
      boards(ids: $board_id) {
        items_page(limit: 500) {
          items {
            column_values(ids: ["text8", "status", "status4"]) {
              id
              text
            }
          }
        }
      }
    }
    """
    try:
        data = _make_request(query, {"board_id": [board_id]})
    except Exception as e:
        print(f"Failed to fetch board items: {e}")
        return {}
        
    boards = data.get("data", {}).get("boards", [])
    if not boards:
        return {}
        
    items = boards[0].get("items_page", {}).get("items", [])
    result = {}
    for item in items:
        cols = item.get("column_values", [])
        task_id = ""
        task_status = ""
        for col in cols:
            if col["id"] == "text8":
                task_id = col["text"] or ""
            if col["id"] in ("status", "status4") and col["text"] == "Done":
                task_status = "Done"
        if task_id:
            result[task_id] = task_status
    return result

def _create_item(task: SEOTask, board_id: str) -> bool:
    query = """
    mutation ($board_id: ID!, $item_name: String!, $column_values: JSON!) {
      create_item(board_id: $board_id, item_name: $item_name, column_values: $column_values) {
        id
      }
    }
    """
    payload = to_monday_payload(task)
    variables = {
        "board_id": board_id,
        "item_name": payload["name"],
        "column_values": payload["column_values"]
    }
    try:
        _make_request(query, variables)
        print(f"[monday] created: {task.task_id} | {task.title[:50]}")
        return True
    except Exception as e:
        print(f"[monday] error creating {task.task_id}: {e}")
        return False

def publish_tasks(technical_tasks: TaskList, content_tasks: TaskList) -> dict:
    if not technical_tasks and not content_tasks:
        return {"created": 0, "skipped": 0, "errors": 0}
        
    stats = {"created": 0, "skipped": 0, "errors": 0}
    
    for bucket, tasks in [("technical", technical_tasks), ("content", content_tasks)]:
        if not tasks: continue
        board_id = _board_id(bucket)
        existing = _fetch_existing_task_ids(board_id)
        
        for task in tasks:
            tid = task.task_id
            if tid in existing and existing[tid] != "Done":
                print(f"[monday] skipped (already open): {tid}")
                stats["skipped"] += 1
                continue
                
            success = _create_item(task, board_id)
            if success:
                stats["created"] += 1
            else:
                stats["errors"] += 1
            time.sleep(0.3)
            
    return stats
