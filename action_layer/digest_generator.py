import os
import json
import requests
from openai import OpenAI
from action_layer.task_schema import TaskList, SEOTask
from action_layer.task_prioritizer import top_tasks

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

def _build_prompt(all_tasks: TaskList, wins: list, run_date: str) -> str:
    tops = top_tasks(all_tasks, n=5)
    t_dicts = [{"title": t.title, "action": t.action, "bucket": t.bucket} for t in tops]
    ctx = {
        "run_date": run_date,
        "wins": wins,
        "top_tasks": t_dicts
    }
    return json.dumps(ctx)

def _call_groq(prompt: str) -> str:
    system_prompt = """You are an SEO reporting assistant. Generate a concise weekly brief 
for a marketing stakeholder. Respond with ONLY the following format, 
no preamble, no sign-off, no markdown:

3 WINS THIS WEEK
• [win 1 — one sentence, specific metric if available]
• [win 2]
• [win 3]

3 THINGS BEING FIXED
• [fix 1 — what and which team: Dev or Content]
• [fix 2]
• [fix 3]

THIS WEEK'S NUMBER
[single metric with brief context, ≤20 words]

Total response must be under 200 words. Be specific. No filler phrases."""
    
    if not GROQ_API_KEY:
        return "Digest generation failed — review Monday.com boards for this week's tasks."
        
    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=400,
            temperature=0.3
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq API error: {e}")
        return "Digest generation failed — review Monday.com boards for this week's tasks."

def _send_slack(body: str) -> bool:
    if not SLACK_WEBHOOK_URL:
        return False
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json={"text": body}, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"Slack error: {e}")
        return False

def generate_and_send_digest(all_tasks: TaskList, wins: list, run_date: str) -> dict:
    if not all_tasks and not wins:
        body = "Digest generation failed — review Monday.com boards for this week's tasks."
        groq_ok = False
    else:
        prompt = _build_prompt(all_tasks, wins, run_date)
        body = _call_groq(prompt)
        groq_ok = "Digest generation failed" not in body

    slack_ok = False
    if SLACK_WEBHOOK_URL:
        slack_ok = _send_slack(body)
        
    return {
        "groq_ok": groq_ok,
        "slack_ok": slack_ok,
        "body": body
    }
