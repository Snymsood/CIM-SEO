import asyncio
import os
import subprocess
import pandas as pd
from openai import OpenAI
import requests
import json

# Environment variables
MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_MASTER_ITEM_ID = os.getenv("MONDAY_MASTER_ITEM_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

async def run_script(script_name, env_vars=None):
    print(f"Starting {script_name}...")
    env = os.environ.copy()
    if env_vars:
        env.update(env_vars)
    
    process = await asyncio.create_subprocess_exec(
        "python", "-u", script_name,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    
    # stream output
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        print(f"[{script_name}] {line.decode('utf-8').strip()}", flush=True)
        
    await process.wait()
    print(f"Finished {script_name} with code {process.returncode}")
    if process.returncode != 0:
        raise RuntimeError(f"{script_name} failed with exit code {process.returncode}")

async def run_all_scripts():
    tasks = []
    
    # GA4
    ga4_env = {
        "GA4_PROPERTY_ID": "341629008",
        "MONDAY_ITEM_ID": "11818936551"
    }
    tasks.append(run_script("ga4_weekly_report.py", ga4_env))
    
    # GSC
    gsc_env = {
        "GSC_PROPERTY": "https://www.cim.org/",
        "MONDAY_ITEM_ID": os.getenv("MONDAY_GSC_ITEM_ID", "")
    }
    tasks.append(run_script("gsc_weekly_report.py", gsc_env))
    
    # Site Speed
    speed_env = {
        "MONDAY_ITEM_ID": "11404492774"
    }
    tasks.append(run_script("site_speed_monitoring.py", speed_env))
    
    # AI Snippet (runs two scripts sequentially inside one async task)
    async def run_snippet_pipeline():
        snippet_env = {
            "MONDAY_API_KEY": MONDAY_API_TOKEN or "",
            "MONDAY_AI_SNIPPET_ITEM_ID": os.getenv("MONDAY_AI_SNIPPET_ITEM_ID", ""),
            "GROQ_MODEL": "llama-3.1-8b-instant"
        }
        await run_script("ai_snippet_verification.py", snippet_env)
        await run_script("ai_snippet_pdf_report.py", snippet_env)
        
    tasks.append(run_snippet_pipeline())
    
    # Run all 4 pipelines concurrently!
    await asyncio.gather(*tasks)

def generate_unified_insights():
    if not GROQ_API_KEY:
        return "GROQ_API_KEY not found. Unified insights skipped."
        
    # Read CSVs safely
    try:
        ga4 = pd.read_csv("ga4_summary_comparison.csv").to_csv(index=False)
    except:
        ga4 = "GA4 Data Unavailable"
        
    try:
        gsc = pd.read_csv("weekly_comparison.csv").sort_values(by="clicks_current", ascending=False).head(10).to_csv(index=False)
    except:
        gsc = "GSC Data Unavailable"
        
    try:
        speed = pd.read_csv("site_speed_comparison.csv")
        speed = speed[speed["strategy"] == "mobile"].head(10).to_csv(index=False)
    except:
        speed = "Site Speed Data Unavailable"

    prompt = f"""
You are the Master Agentic SEO Analyst writing a unified executive summary.
Look at the data from GA4, GSC, and Core Web Vitals (Site Speed) and draw correlations.
Write an Executive Summary and Action Items.
Format exactly as requested: no markdown asterisks, use simple bullets, and keep it under 300 words.

[GA4 Data]
{ga4}

[GSC Top 10 Queries]
{gsc}

[Site Speed Top 10 Pages (Mobile)]
{speed}
"""

    client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a top-tier SEO Data Scientist connecting the dots between traffic, rankings, and page speed."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()

def post_unified_summary_to_monday(ai_text):
    if not MONDAY_API_TOKEN or not MONDAY_MASTER_ITEM_ID:
        print("Skipping monday master update: MONDAY_API_TOKEN or MONDAY_MASTER_ITEM_ID not configured.")
        return

    update_query = """
    mutation ($item_id: ID!, $body: String!) {
      create_update(item_id: $item_id, body: $body) {
        id
      }
    }
    """
    
    formatted_body = f"<h2>Weekly SEO Master Report</h2><br><br><b>Executive Summary & Action Items:</b><br><br>{ai_text.replace(chr(10), '<br>')}<br><br>📊 <a href='https://snymsood.github.io/CIM-SEO'>Click here to view the live Interactive Dashboard</a>"

    update_variables = {
        "item_id": str(MONDAY_MASTER_ITEM_ID),
        "body": formatted_body,
    }

    update_response = requests.post(
        "https://api.monday.com/v2",
        headers={"Authorization": MONDAY_API_TOKEN, "Content-Type": "application/json"},
        json={"query": update_query, "variables": update_variables},
        timeout=60,
    )
    
    if update_response.status_code != 200:
        print(f"Monday API Error: {update_response.text}")
    else:
        print("Successfully posted Master Unified Summary to Monday.com!")

def main():
    print("--- STARTING MASTER ORCHESTRATOR ---")
    asyncio.run(run_all_scripts())
    
    print("--- GENERATING UNIFIED INSIGHTS ---")
    ai_text = generate_unified_insights()
    print("Insights generated:")
    print(ai_text)
    
    print("--- POSTING TO MONDAY.COM ---")
    post_unified_summary_to_monday(ai_text)
    
    print("--- MASTER ORCHESTRATOR COMPLETE ---")

if __name__ == "__main__":
    main()
