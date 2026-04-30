# Quick Start: Monthly Dashboard Implementation

**Goal:** Build a comprehensive monthly analytics dashboard combining GA4, GSC, PageSpeed, and other data sources.

---

## 📋 Prerequisites

- [ ] Python 3.8+ installed
- [ ] All dependencies from `requirements.txt` installed
- [ ] Google Service Account key (`gsc-key.json`) configured
- [ ] Environment variables set (see `.env.example`)
- [ ] Existing weekly reports working correctly

---

## 🚀 Implementation Phases

### Phase 1: Data Collection (Week 1)
**Goal:** Extend existing scripts to support monthly time windows

```bash
# 1. Update seo_utils.py
# Add get_monthly_date_windows() function

# 2. Create monthly_data_collector.py
# Orchestrates all data fetching with 30-day windows

# 3. Test data collection
python monthly_data_collector.py
```

**Expected Output:**
- `monthly_ga4_summary.csv`
- `monthly_gsc_queries.csv`
- `monthly_gsc_pages.csv`
- `monthly_speed.csv`
- `monthly_content_categories.csv`
- `monthly_technical_health.csv`

---

### Phase 2: Chart Generation (Week 2)
**Goal:** Build all 20+ charts for the monthly dashboard

```bash
# 1. Create monthly_chart_builder.py
# Implement all chart functions

# 2. Test chart generation
python monthly_chart_builder.py
```

**Expected Output:**
- `charts/monthly_traffic_trend.png`
- `charts/monthly_channel_performance.png`
- `charts/monthly_device_evolution.png`
- `charts/monthly_search_funnel.png`
- `charts/monthly_keyword_distribution.png`
- ... (20+ charts total)

---

### Phase 3: HTML Dashboard (Week 3)
**Goal:** Build the HTML dashboard with all sections

```bash
# 1. Create monthly_dashboard_generator.py
# Generate 8-page HTML dashboard

# 2. Test HTML generation
python monthly_dashboard_generator.py
```

**Expected Output:**
- `monthly_dashboard.html` (self-contained, ~2-3 MB)

---

### Phase 4: AI Analysis (Week 4)
**Goal:** Add AI-powered insights and recommendations

```bash
# 1. Create monthly_ai_analyst.py
# Build deterministic + AI bullets

# 2. Test AI integration
python monthly_ai_analyst.py
```

**Expected Output:**
- AI-generated insights in HTML dashboard
- Fallback to deterministic bullets if AI fails

---

### Phase 5: Integration (Week 5)
**Goal:** Integrate all components and test end-to-end

```bash
# 1. Create monthly_master_report.py
# Main orchestrator script

# 2. Run full pipeline
python monthly_master_report.py
```

**Expected Output:**
- Complete monthly dashboard
- All charts generated
- Data uploaded to Monday.com
- Historical data appended to Google Sheets

---

### Phase 6: Automation (Week 6)
**Goal:** Set up automated monthly generation

```bash
# 1. Create GitHub Actions workflow
# .github/workflows/monthly-master-report.yml

# 2. Configure secrets in GitHub

# 3. Test automated run
gh workflow run monthly-master-report.yml
```

**Expected Output:**
- Automated monthly generation on first Monday of each month
- Artifacts uploaded to GitHub Actions
- Dashboard posted to Monday.com

---

## 📝 Code Templates

### 1. Monthly Date Windows (seo_utils.py)

```python
def get_monthly_date_windows():
    """
    Returns current month and previous month date ranges.
    
    Returns:
        tuple: (current_start, current_end, previous_start, previous_end)
    """
    from datetime import date, timedelta
    from dateutil.relativedelta import relativedelta
    
    today = date.today()
    
    # Current month: first day to yesterday
    current_start = today.replace(day=1)
    current_end = today - timedelta(days=1)
    
    # Previous month: same date range, one month back
    previous_start = (current_start - relativedelta(months=1))
    previous_end = (current_end - relativedelta(months=1))
    
    return current_start, current_end, previous_start, previous_end
```

### 2. Chart Function Template (monthly_chart_builder.py)

```python
def chart_monthly_traffic_trend(ga4_data, gsc_data):
    """
    Dual-axis line chart: Sessions (GA4) + Clicks (GSC) over 30 days.
    
    Args:
        ga4_data: DataFrame with columns [date, sessions]
        gsc_data: DataFrame with columns [date, clicks]
    
    Returns:
        str: Path to saved chart PNG
    """
    if ga4_data.empty or gsc_data.empty:
        return _placeholder("monthly_traffic_trend.png")
    
    # Merge data on date
    df = pd.merge(ga4_data, gsc_data, on="date", how="outer").fillna(0)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    
    # Create figure
    fig, ax1 = plt.subplots(figsize=(13, 4.8))
    
    # Left axis: Sessions
    ax1.plot(df["date"], df["sessions"], color=C_NAVY, linewidth=2, label="Sessions (GA4)")
    ax1.fill_between(df["date"], df["sessions"], alpha=0.2, color=C_NAVY)
    
    # Right axis: Clicks
    ax2 = ax1.twinx()
    ax2.plot(df["date"], df["clicks"], color=C_TEAL, linewidth=2, label="Clicks (GSC)")
    ax2.fill_between(df["date"], df["clicks"], alpha=0.2, color=C_TEAL)
    
    # Styling
    _style_ax(ax1, title="Monthly Traffic Trend", xlabel="Date", ylabel="Sessions")
    ax2.set_ylabel("Clicks", fontsize=8, color="#64748B", labelpad=4)
    ax2.tick_params(labelsize=8, colors="#64748B", length=0)
    
    # Legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, frameon=False, fontsize=8)
    
    # Grid
    ax1.grid(axis="y", linestyle="--", alpha=0.3, color=C_BORDER, zorder=1)
    
    fig.tight_layout(pad=2.0)
    return _save(fig, "monthly_traffic_trend.png")
```

### 3. HTML Section Template (monthly_dashboard_generator.py)

```python
def _section(title, content):
    """
    Wrap content in a titled section with thick rule.
    
    Args:
        title: Section title
        content: HTML content
    
    Returns:
        str: Formatted HTML section
    """
    return f"""
<div style="padding:40px 0;">
  <div style="font-family:'Playfair Display',Georgia,serif;font-size:11px;font-weight:700;
              text-transform:uppercase;letter-spacing:0.15em;color:#000;margin-bottom:24px;
              display:flex;align-items:center;gap:16px;">
    <span style="display:inline-block;width:8px;height:8px;background:#000;flex-shrink:0;"></span>
    {_html.escape(title)}
  </div>
  <div style="background:#fff;border:2px solid #000;padding:28px 32px;">
    {content}
  </div>
</div>
<hr style="border:none;border-top:4px solid #000;margin:0;">
"""
```

### 4. AI Analysis Template (monthly_ai_analyst.py)

```python
def build_ai_bullets(data, kpis):
    """
    Generate AI-powered insights from monthly data.
    
    Args:
        data: Dict of DataFrames with all monthly data
        kpis: Dict of KPI values (current, previous)
    
    Returns:
        list: AI-generated bullet points
    """
    if not GROQ_API_KEY:
        return []
    
    # Build context from data
    ga4_ctx = data["ga4_summary"].to_csv(index=False)
    gsc_ctx = data["gsc_queries"].head(10).to_csv(index=False)
    speed_ctx = data["speed"].to_csv(index=False)
    
    prompt = f"""
You are writing concise executive bullet points for a monthly cross-channel SEO report.

Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.
Each bullet is one sentence. Maximum 10 bullets total.
Do not invent data. Do not mention AI, models, or automation.
Draw cross-channel correlations and identify strategic opportunities.
Focus on actionable insights and risks.

GA4 summary (30 days):
{ga4_ctx}

GSC top queries (30 days):
{gsc_ctx}

PageSpeed data:
{speed_ctx}

Key metrics:
- Sessions: {kpis["sessions"]["curr"]:,.0f} ({format_pct_change(kpis["sessions"]["curr"], kpis["sessions"]["prev"])})
- Clicks: {kpis["clicks"]["curr"]:,.0f} ({format_pct_change(kpis["clicks"]["curr"], kpis["clicks"]["prev"])})
- Avg Position: {kpis["avg_position"]["curr"]:.1f} (prev: {kpis["avg_position"]["prev"]:.1f})
"""
    
    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You write polished monthly executive SEO briefs as bullet points only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        
        raw = response.choices[0].message.content.strip()
        bullets = []
        for line in raw.splitlines():
            clean = line.strip().lstrip("-*+•·▪▸").replace("**","").replace("__","").replace("*","").strip()
            if clean:
                bullets.append(clean)
        return bullets
        
    except Exception as e:
        print(f"AI bullets failed: {e}")
        return []
```

### 5. Main Orchestrator Template (monthly_master_report.py)

```python
#!/usr/bin/env python3
"""
Monthly Master Report - Main Orchestrator

Generates comprehensive monthly analytics dashboard combining:
- Google Analytics 4 (GA4)
- Google Search Console (GSC)
- PageSpeed Insights
- Content category performance
- Technical health metrics
"""

import asyncio
from pathlib import Path
from datetime import date

# Import all modules
from monthly_data_collector import collect_all_monthly_data
from monthly_chart_builder import build_all_monthly_charts
from monthly_ai_analyst import build_unified_bullets
from monthly_dashboard_generator import generate_html_dashboard
from monday_utils import upload_html_to_monday
from google_sheets_db import append_to_sheet

def main():
    print("=" * 80)
    print("MONTHLY MASTER REPORT - STARTING")
    print("=" * 80)
    
    # Phase 1: Data Collection
    print("\n[1/5] Collecting monthly data...")
    data = collect_all_monthly_data()
    print("✓ Data collection complete")
    
    # Phase 2: Chart Generation
    print("\n[2/5] Generating charts...")
    chart_paths = build_all_monthly_charts(data)
    print(f"✓ Generated {len(chart_paths)} charts")
    
    # Phase 3: AI Analysis
    print("\n[3/5] Building AI insights...")
    bullets = build_unified_bullets(data)
    print(f"✓ Generated {len(bullets)} bullet points")
    
    # Phase 4: HTML Dashboard
    print("\n[4/5] Generating HTML dashboard...")
    html_path = generate_html_dashboard(data, chart_paths, bullets)
    print(f"✓ Dashboard saved to {html_path}")
    
    # Phase 5: Integration
    print("\n[5/5] Uploading to integrations...")
    try:
        upload_html_to_monday(html_path)
        print("✓ Uploaded to Monday.com")
    except Exception as e:
        print(f"⚠ Monday upload failed: {e}")
    
    try:
        append_to_sheet(data["kpis"], "Monthly_KPIs")
        print("✓ Appended to Google Sheets")
    except Exception as e:
        print(f"⚠ Google Sheets append failed: {e}")
    
    print("\n" + "=" * 80)
    print("MONTHLY MASTER REPORT - COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()
```

---

## 🔧 Configuration

### Environment Variables (.env)

```bash
# Google APIs
GSC_PROPERTY=https://www.cim.org/
GA4_PROPERTY_ID=341629008

# Monday.com
MONDAY_API_TOKEN=your_token_here
MONDAY_MONTHLY_ITEM_ID=your_item_id_here

# AI/LLM
GROQ_API_KEY=your_groq_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# PageSpeed Insights
PAGESPEED_API_KEY=your_pagespeed_key_here

# Google Sheets
GOOGLE_SHEET_ID=your_sheet_id_here
```

### GitHub Actions Workflow (.github/workflows/monthly-master-report.yml)

```yaml
name: Monthly Master Report

on:
  workflow_dispatch:
  schedule:
    - cron: "0 9 * * 1"  # Every Monday at 9:00 AM UTC (adjust for first Monday)

jobs:
  monthly-report:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Setup credentials
        run: echo "${{ secrets.GSC_SERVICE_ACCOUNT_KEY }}" > gsc-key.json
      
      - name: Run monthly report
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          MONDAY_API_TOKEN: ${{ secrets.MONDAY_API_TOKEN }}
          MONDAY_MONTHLY_ITEM_ID: ${{ secrets.MONDAY_MONTHLY_ITEM_ID }}
          GOOGLE_SHEET_ID: ${{ secrets.GOOGLE_SHEET_ID }}
          GSC_PROPERTY: "https://www.cim.org/"
          GA4_PROPERTY_ID: "341629008"
        run: python monthly_master_report.py
      
      - uses: actions/upload-artifact@v4
        with:
          name: monthly-report
          path: |
            monthly_dashboard.html
            charts/monthly_*.png
            monthly_*.csv
```

---

## ✅ Testing Checklist

### Data Collection
- [ ] Monthly date windows calculated correctly
- [ ] GA4 data fetched for 30 days
- [ ] GSC data fetched for 30 days
- [ ] PageSpeed data fetched for all tracked pages
- [ ] Content category data aggregated correctly
- [ ] All CSVs saved successfully

### Chart Generation
- [ ] All 20+ charts generated
- [ ] No broken/empty charts
- [ ] Proper styling applied
- [ ] File sizes reasonable (<500KB each)
- [ ] Placeholder charts for empty data

### HTML Dashboard
- [ ] All sections render correctly
- [ ] Charts embedded as base64
- [ ] Navigation links work
- [ ] Mobile responsive
- [ ] No broken images
- [ ] File size reasonable (<5MB)

### AI Analysis
- [ ] Deterministic bullets generated
- [ ] AI bullets generated (if API available)
- [ ] Markdown stripped correctly
- [ ] Graceful fallback if AI fails
- [ ] Bullets make sense and are actionable

### Integration
- [ ] HTML uploaded to Monday.com
- [ ] Summary posted to Monday item
- [ ] KPIs appended to Google Sheets
- [ ] Artifacts uploaded to GitHub Actions
- [ ] Error handling works correctly

---

## 🐛 Troubleshooting

### Issue: API rate limit exceeded
**Solution:** Add delays between API calls, use exponential backoff

```python
import time
from functools import wraps

def retry_with_backoff(max_retries=3, base_delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    print(f"Retry {attempt + 1}/{max_retries} after {delay}s: {e}")
                    time.sleep(delay)
        return wrapper
    return decorator
```

### Issue: Charts not rendering in HTML
**Solution:** Verify base64 encoding is correct

```python
import base64

def embed_chart_as_base64(chart_path):
    """Convert chart PNG to base64 data URI."""
    with open(chart_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/png;base64,{data}"
```

### Issue: AI analysis fails
**Solution:** Ensure graceful fallback to deterministic bullets

```python
def build_unified_bullets(data, kpis):
    """Always return at least deterministic bullets."""
    deterministic = build_deterministic_bullets(data, kpis)
    
    try:
        ai = build_ai_bullets(data, kpis)
    except Exception as e:
        print(f"AI analysis failed: {e}")
        ai = []
    
    return deterministic + ai
```

### Issue: Memory error with large datasets
**Solution:** Process data in chunks, clear memory after each section

```python
import gc

def process_large_dataset(df):
    """Process large DataFrame in chunks."""
    chunk_size = 10000
    results = []
    
    for i in range(0, len(df), chunk_size):
        chunk = df.iloc[i:i+chunk_size]
        result = process_chunk(chunk)
        results.append(result)
        
        # Clear memory
        del chunk
        gc.collect()
    
    return pd.concat(results, ignore_index=True)
```

---

## 📚 Additional Resources

- [REPORT_DESIGN_PRINCIPLES.md](REPORT_DESIGN_PRINCIPLES.md) - Complete design guidelines
- [MONTHLY_DASHBOARD_ANALYSIS.md](MONTHLY_DASHBOARD_ANALYSIS.md) - Detailed analysis and proposal
- [MONTHLY_DASHBOARD_WIREFRAME.md](MONTHLY_DASHBOARD_WIREFRAME.md) - Visual layout guide
- [COMPLIANCE_SUMMARY.md](COMPLIANCE_SUMMARY.md) - Compliance analysis
- [README.md](README.md) - Project overview

---

## 🎯 Success Criteria

- [ ] Dashboard generates successfully on schedule
- [ ] All data sources integrated correctly
- [ ] Charts render properly on all devices
- [ ] AI insights are actionable and accurate
- [ ] Stakeholders find dashboard valuable
- [ ] Reduces manual reporting time by 80%+
- [ ] No manual intervention required
- [ ] Error handling prevents failures
- [ ] Performance is acceptable (<15 minutes total)

---

**Document Version:** 1.0  
**Last Updated:** April 30, 2026  
**Author:** Kiro AI Assistant  
**Status:** Ready for Implementation
