import asyncio
import os
import subprocess
import pandas as pd
from openai import OpenAI
import requests
import json
import html
from datetime import date

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
    # ------------------------------------------------------------------ #
    # Group 1 — API-based pipelines: run fully concurrently              #
    # ------------------------------------------------------------------ #
    ga4_env = {
        "GA4_PROPERTY_ID": "341629008",
        "MONDAY_ITEM_ID": "11818936551",
    }
    gsc_weekly_env = {
        "GSC_PROPERTY": "https://www.cim.org/",
        "MONDAY_ITEM_ID": os.getenv("MONDAY_GSC_ITEM_ID", ""),
    }
    gsc_keyword_env = {
        "GSC_PROPERTY": "https://www.cim.org/",
        "MONDAY_ITEM_ID": os.getenv("MONDAY_GSC_KEYWORD_ITEM_ID", ""),
    }
    gsc_landing_env = {
        "GSC_PROPERTY": "https://www.cim.org/",
        "MONDAY_ITEM_ID": os.getenv("MONDAY_GSC_LANDING_ITEM_ID", ""),
    }
    speed_env = {
        "MONDAY_ITEM_ID": "11404492774",
    }

    async def run_snippet_pipeline():
        snippet_env = {
            "MONDAY_API_KEY": MONDAY_API_TOKEN or "",
            "MONDAY_AI_SNIPPET_ITEM_ID": os.getenv("MONDAY_AI_SNIPPET_ITEM_ID", ""),
            "GROQ_MODEL": "llama-3.1-8b-instant",
        }
        await run_script("ai_snippet_verification.py", snippet_env)
        await run_script("ai_snippet_pdf_report.py", snippet_env)

    print("--- Starting API-based pipelines (concurrent) ---")
    await asyncio.gather(
        run_script("ga4_weekly_report.py", ga4_env),
        run_script("gsc_weekly_report.py", gsc_weekly_env),
        run_script("gsc_keyword_ranking_report.py", gsc_keyword_env),
        run_script("gsc_landing_pages_report.py", gsc_landing_env),
        run_script("site_speed_monitoring.py", speed_env),
        run_snippet_pipeline(),
    )

    # ------------------------------------------------------------------ #
    # Group 2 — Crawl-based pipelines: run sequentially to avoid         #
    # overloading cim.org with two concurrent crawlers                   #
    # ------------------------------------------------------------------ #
    broken_link_env = {
        "MONDAY_ITEM_ID": os.getenv("MONDAY_BROKEN_LINK_ITEM_ID", ""),
    }
    internal_link_env = {
        "MONDAY_ITEM_ID": os.getenv("MONDAY_INTERNAL_LINK_ITEM_ID", ""),
    }
    content_audit_env = {
        "MONDAY_ITEM_ID": os.getenv("MONDAY_CONTENT_AUDIT_ITEM_ID", ""),
    }

    print("--- Starting crawl-based pipelines (sequential) ---")
    await run_script("broken_link_check.py", broken_link_env)
    await run_script("internal_linking_audit.py", internal_link_env)
    await run_script("content_audit_schedule_report.py", content_audit_env)
    await run_script("content_category_performance.py", {})

def generate_unified_insights():
    if not GROQ_API_KEY:
        return "GROQ_API_KEY not found. Unified insights skipped."
        
    # Read CSVs safely
    try:
        ga4 = pd.read_csv("ga4_summary_comparison.csv").to_csv(index=False)
    except Exception as e:
        print(f"Warning: GA4 data loading failed: {e}")
        ga4 = "GA4 Data Unavailable"
        
    try:
        gsc = pd.read_csv("weekly_comparison.csv").sort_values(by="clicks_current", ascending=False).head(10).to_csv(index=False)
    except Exception as e:
        print(f"Warning: GSC data loading failed: {e}")
        gsc = "GSC Data Unavailable"
        
    try:
        speed = pd.read_csv("site_speed_comparison.csv")
        speed = speed[speed["strategy"] == "mobile"].head(10).to_csv(index=False)
    except Exception as e:
        print(f"Warning: Site Speed data loading failed: {e}")
        speed = "Site Speed Data Unavailable"

    try:
        content_pillars = pd.read_csv("content_category_performance.csv").to_csv(index=False)
    except Exception as e:
        print(f"Warning: Content Category data loading failed: {e}")
        content_pillars = "Content Pillar Data Unavailable"

    prompt = f"""
You are the Master Agentic SEO Analyst writing a unified executive summary.
Look at the data from GA4, GSC, Core Web Vitals, and Content Category performance.
Draw correlations: e.g., is the Technical Library driving impressions but not sessions? Are Events spiking in engagement?
Write an Executive Summary and Action Items focused on growth.
Format exactly as requested: no markdown asterisks, use simple bullets, and keep it under 350 words.

[GA4 Data]
{ga4}

[GSC Top 10 Queries]
{gsc}

[Site Speed Top 10 Pages (Mobile)]
{speed}

[Content Category / Pillar Performance]
{content_pillars}
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
    content_cat = load_data("content_category_performance.csv").sort_values(by="sessions", ascending=False)
    
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
    
    content_cat_table = build_table(content_cat, 
        ["category", "sessions", "clicks", "engagement_rate", "avg_duration"], 
        ["Category", "Sessions", "Clicks", "Eng Rate", "Avg Dur"])

    dashboard_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CIM SEO Performance Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{ 
            --primary: #212878; 
            --primary-dark: #000000;
            --bg: #F1F5F9; 
            --surface: #FFFFFF; 
            --text: #1A1A1A; 
            --text-muted: #64748B; 
            --border: #E2E8F0; 
            --pos: #059669;
            --neg: #DC2626;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ 
            font-family: 'Poppins', sans-serif; 
            background-color: var(--bg); 
            color: var(--text); 
            line-height: 1.6; 
        }}
        .header-bar {{
            background: var(--primary);
            color: #FFFFFF;
            padding: 2rem 5%;
            margin-bottom: 2rem;
            border-bottom: 4px solid var(--primary-dark);
            box-shadow: 0 4px 10px rgba(0,0,0,0.1);
        }}
        .header-bar h1 {{ 
            font-size: 2.2rem; 
            font-weight: 700; 
            margin-bottom: 0.5rem;
        }}
        .header-bar p {{
            opacity: 0.9;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 0 2rem 4rem 2rem; }}
        
        .kpi-grid {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); 
            gap: 1.5rem; 
            margin-bottom: 3rem; 
        }}
        .kpi-card {{ 
            background: var(--surface); 
            border-radius: 4px; 
            padding: 1.5rem; 
            box-shadow: 0 2px 4px rgba(33, 40, 120, 0.05); 
            border: 1px solid var(--border); 
            border-bottom: 4px solid var(--border);
            transition: all 0.3s ease;
        }}
        .kpi-card:hover {{ transform: translateY(-3px); border-bottom-color: var(--primary); }}
        .kpi-title {{ 
            font-size: 0.8rem; 
            text-transform: uppercase; 
            color: var(--text-muted); 
            letter-spacing: 0.05em; 
            margin-bottom: 0.75rem; 
            font-weight: 600; 
        }}
        .kpi-value {{ 
            font-size: 2.5rem; 
            font-weight: 700; 
            color: var(--primary);
            margin-bottom: 0.5rem; 
        }}
        .kpi-delta {{
            font-size: 0.9rem;
            font-weight: 600;
        }}

        .ai-summary {{ 
            background: var(--surface); 
            border-top: 5px solid var(--primary); 
            padding: 2.5rem; 
            border-radius: 4px; 
            margin-bottom: 3rem; 
            border: 1px solid var(--border); 
            box-shadow: 0 4px 6px rgba(0,0,0,0.02);
        }}
        .ai-summary h2 {{ 
            color: var(--primary); 
            margin-bottom: 1.5rem; 
            font-size: 1.75rem; 
            font-weight: 700;
            border-bottom: 2px solid var(--bg);
            padding-bottom: 1rem;
        }}
        .ai-text {{ 
            font-size: 1.1rem; 
            white-space: pre-wrap; 
            color: #334155; 
            line-height: 1.8; 
        }}
        
        .tables-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(450px, 1fr)); gap: 2rem; }}
        .table-container {{ 
            background: var(--surface); 
            border-radius: 4px; 
            padding: 1.5rem; 
            border: 1px solid var(--border); 
            box-shadow: 0 2px 4px rgba(0,0,0,0.02);
        }}
        .table-container h3 {{ 
            margin-bottom: 1.5rem; 
            font-size: 1.25rem; 
            color: var(--primary);
            font-weight: 600;
            display: flex;
            align-items: center;
        }}
        .table-container h3::before {{
            content: '';
            width: 4px;
            height: 1.25rem;
            background: var(--primary);
            margin-right: 12px;
            display: inline-block;
        }}
        
        table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
        th {{ 
            background: var(--primary); 
            color: #FFFFFF; 
            font-weight: 600; 
            padding: 12px 16px; 
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.5px;
        }}
        td {{ padding: 14px 16px; border-bottom: 1px solid var(--border); color: #334155; }}
        tr:nth-child(even) {{ background: #F8FAFC; }}
        tr:hover {{ background: #F1F5F9; }}
    </style>
</head>
<body>
    <div class="header-bar">
        <div class="container" style="padding: 0;">
            <h1>CIM SEO Performance Hub</h1>
            <p>Agentic Intelligence Dashboard • Generated {date.today().strftime('%B %d, %Y')}</p>
        </div>
    </div>
    <div class="container">

        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-title">Weekly Sessions</div>
                <div class="kpi-value">{metrics['sessions']['val']:,.0f}</div>
                <div class="kpi-delta">{format_change(metrics['sessions']['change'])} WoW</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Active Users</div>
                <div class="kpi-value">{metrics['users']['val']:,.0f}</div>
                <div class="kpi-delta">{format_change(metrics['users']['change'])} WoW</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Search Clicks</div>
                <div class="kpi-value">{metrics['clicks']['val']:,.0f}</div>
                <div class="kpi-delta">{format_change(metrics['clicks']['change'])} WoW</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Search Impressions</div>
                <div class="kpi-value">{metrics['impressions']['val']:,.0f}</div>
                <div class="kpi-delta">{format_change(metrics['impressions']['change'])} WoW</div>
            </div>
        </div>

        <div class="ai-summary">
            <h2>Executive Performance Analysis</h2>
            <div class="ai-text">{html.escape(ai_text)}</div>
        </div>

        <div class="ai-summary" style="border-top-color: #059669; margin-top: -1rem; background: #F8FAFC;">
            <h2 style="color: #059669;">Content Strategic Analysis</h2>
            <p style="margin-bottom: 2rem; color: var(--text-muted);">Mapping CIM's digital ecosystem by pillar (Reach vs. Quality).</p>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-bottom: 2rem;">
                <div class="table-container" style="padding: 1rem; border-top: 3px solid #059669;">
                    <img src="charts/content_ecosystem_map.png" style="width: 100%; border-radius: 8px;">
                </div>
                <div class="table-container" style="padding: 1rem; border-top: 3px solid #059669;">
                    <img src="charts/content_share_of_voice.png" style="width: 100%; border-radius: 8px;">
                </div>
            </div>
            
            {content_cat_table}
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
