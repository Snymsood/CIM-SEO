import asyncio
import os
import subprocess
import pandas as pd
from openai import OpenAI
import requests
import json
import html
from datetime import date
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


def generate_html_dashboard(ai_text):
    def load_data(filename):
        try:
            return pd.read_csv(filename)
        except Exception:
            return pd.DataFrame()

    ga4_summary = load_data("ga4_summary_comparison.csv")
    ga4_pages = load_data("ga4_top_landing_pages.csv").head(10)
    gsc_queries = load_data("top_queries.csv").head(10)
    speed = load_data("site_speed_comparison.csv")
    
    metrics = {
        "sessions": {"val": 0, "change": 0},
        "users": {"val": 0, "change": 0},
        "clicks": {"val": 0, "change": 0},
        "impressions": {"val": 0, "change": 0}
    }
    
    if not ga4_summary.empty:
        for _, row in ga4_summary.iterrows():
            if row['metric'] == 'sessions':
                metrics['sessions'] = {'val': row['current'], 'change': row['change']}
            elif row['metric'] == 'activeUsers':
                metrics['users'] = {'val': row['current'], 'change': row['change']}
                
    gsc_comp = load_data("weekly_comparison.csv")
    if not gsc_comp.empty:
        clicks_curr = gsc_comp['clicks_current'].sum()
        clicks_prev = gsc_comp['clicks_previous'].sum()
        imp_curr = gsc_comp['impressions_current'].sum()
        imp_prev = gsc_comp['impressions_previous'].sum()
        
        metrics['clicks'] = {'val': clicks_curr, 'change': clicks_curr - clicks_prev}
        metrics['impressions'] = {'val': imp_curr, 'change': imp_curr - imp_prev}

    def format_change(change):
        if pd.isna(change): return ""
        val = float(change)
        color = "#10B981" if val > 0 else "#EF4444" if val < 0 else "#6B7280"
        arrow = "▲" if val > 0 else "▼" if val < 0 else "−"
        return f'<span style="color: {color}; font-size: 14px; font-weight: 600;">{arrow} {abs(val):.0f}</span>'

    def build_table(df, cols, headers):
        if df.empty: return "<p style='color: #94A3B8;'>No data available</p>"
        html_str = "<table><thead><tr>"
        for h in headers:
            html_str += f"<th>{html.escape(h)}</th>"
        html_str += "</tr></thead><tbody>"
        for _, row in df.iterrows():
            html_str += "<tr>"
            for col in cols:
                val = row.get(col, "")
                if isinstance(val, float):
                    if "rate" in col.lower() or "ctr" in col.lower():
                        val = f"{val:.2%}"
                    else:
                        val = f"{val:.2f}" if "position" in col.lower() else f"{val:.0f}"
                text_val = html.escape(str(val))
                if len(text_val) > 50: text_val = text_val[:47] + "..."
                html_str += f"<td>{text_val}</td>"
            html_str += "</tr>"
        html_str += "</tbody></table>"
        return html_str

    ga4_table = build_table(ga4_pages, ["landingPage", "sessions", "activeUsers", "engagementRate"], ["Page", "Sessions", "Users", "Engagement"])
    gsc_table = build_table(gsc_queries, ["query", "clicks_current", "impressions_current", "position_current"], ["Query", "Clicks", "Impressions", "Position"])
    
    speed_mobile = speed[speed['strategy'] == 'mobile'].head(10) if not speed.empty else pd.DataFrame()
    speed_table = build_table(speed_mobile, ["page", "performance_score", "lcp_field_ms", "cls_field"], ["Page", "Mobile Score", "LCP (ms)", "CLS"])

    dashboard_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CIM SEO Agentic Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{ --bg: #0F172A; --surface: #1E293B; --primary: #3B82F6; --accent: #10B981; --text: #F8FAFC; --text-muted: #94A3B8; --border: #334155; }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Inter', sans-serif; background-color: var(--bg); color: var(--text); line-height: 1.6; padding: 2rem; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 3rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border); }}
        h1 {{ font-family: 'Outfit', sans-serif; font-size: 2.5rem; font-weight: 800; background: linear-gradient(to right, #3B82F6, #10B981); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1.5rem; margin-bottom: 3rem; }}
        .kpi-card {{ background: var(--surface); border-radius: 16px; padding: 1.5rem; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06); border: 1px solid var(--border); transition: transform 0.2s; }}
        .kpi-card:hover {{ transform: translateY(-5px); border-color: var(--primary); }}
        .kpi-title {{ font-size: 0.875rem; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.05em; margin-bottom: 0.5rem; font-weight: 600; }}
        .kpi-value {{ font-family: 'Outfit', sans-serif; font-size: 2.5rem; font-weight: 800; margin-bottom: 0.5rem; }}
        .ai-summary {{ background: linear-gradient(145deg, var(--surface), #1A2235); border-left: 4px solid var(--primary); padding: 2.5rem; border-radius: 12px; margin-bottom: 3rem; border: 1px solid var(--border); }}
        .ai-summary h2 {{ font-family: 'Outfit', sans-serif; margin-bottom: 1.5rem; color: #60A5FA; display: flex; align-items: center; gap: 12px; font-size: 1.75rem; }}
        .ai-text {{ font-size: 1.05rem; white-space: pre-wrap; color: #E2E8F0; line-height: 1.7; }}
        .tables-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 2rem; }}
        .table-container {{ background: var(--surface); border-radius: 16px; padding: 1.5rem; border: 1px solid var(--border); overflow-x: auto; }}
        .table-container h3 {{ font-family: 'Outfit', sans-serif; margin-bottom: 1.5rem; font-size: 1.25rem; border-bottom: 1px solid var(--border); padding-bottom: 0.75rem; color: #E2E8F0; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 0.875rem; }}
        th {{ color: var(--text-muted); font-weight: 600; padding: 12px 16px; border-bottom: 1px solid var(--border); }}
        td {{ padding: 16px; border-bottom: 1px solid rgba(51, 65, 85, 0.5); }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: rgba(255,255,255,0.02); }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>CIM SEO Dashboard</h1>
                <p style="color: var(--text-muted); margin-top: 0.5rem;">Agentic Analytics Hub • Generated on {date.today().isoformat()}</p>
            </div>
        </header>

        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-title">Weekly Sessions</div>
                <div class="kpi-value">{metrics['sessions']['val']:,.0f}</div>
                <div>{format_change(metrics['sessions']['change'])} WoW</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Active Users</div>
                <div class="kpi-value">{metrics['users']['val']:,.0f}</div>
                <div>{format_change(metrics['users']['change'])} WoW</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Search Clicks</div>
                <div class="kpi-value">{metrics['clicks']['val']:,.0f}</div>
                <div>{format_change(metrics['clicks']['change'])} WoW</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Search Impressions</div>
                <div class="kpi-value">{metrics['impressions']['val']:,.0f}</div>
                <div>{format_change(metrics['impressions']['change'])} WoW</div>
            </div>
        </div>

        <div class="ai-summary">
            <h2>✨ AI Executive Summary</h2>
            <div class="ai-text">{html.escape(ai_text)}</div>
        </div>

        <div class="tables-grid">
            <div class="table-container">
                <h3>Top Landing Pages</h3>
                {ga4_table}
            </div>
            <div class="table-container">
                <h3>Top Search Queries</h3>
                {gsc_table}
            </div>
            <div class="table-container">
                <h3>Core Web Vitals</h3>
                {speed_table}
            </div>
        </div>
    </div>
</body>
</html>"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(dashboard_html)
    print("Dashboard generated as index.html")

def main():
    print("--- STARTING MASTER ORCHESTRATOR ---")
    asyncio.run(run_all_scripts())
    
    print("--- GENERATING UNIFIED INSIGHTS ---")
    ai_text = generate_unified_insights()
    print("Insights generated.")
    
    print("--- GENERATING DASHBOARD ---")
    generate_html_dashboard(ai_text)
    
    print("--- POSTING TO MONDAY.COM ---")
    post_unified_summary_to_monday(ai_text)
    
    print("--- MASTER ORCHESTRATOR COMPLETE ---")

if __name__ == "__main__":
    main()
