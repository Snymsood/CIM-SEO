# Monthly Dashboard Complete Guide

**Quick Reference for Running the Complete Monthly SEO Dashboard**

---

## 🚀 Quick Start (Complete Dashboard)

### One-Command Setup (Recommended)

```bash
# Run all data collection + dashboard generation
./run_monthly_dashboard.sh
```

### Manual Step-by-Step

```bash
# Step 1: Collect PageSpeed data (10-15 min)
python site_speed_monitoring.py

# Step 2: Collect AI snippet data (5-10 min)
python ai_snippet_verification.py

# Step 3: Collect content audit data (2-3 min)
python content_audit_schedule_report.py

# Step 4: Generate monthly dashboard (10-15 min)
python monthly_master_report.py
```

**Total Time:** ~30-45 minutes  
**Output:** `monthly_dashboard.html` with all 23 charts

---

## 📊 What You Get

### Complete Dashboard (8 Pages)

1. **Executive Overview** - 12 KPI cards + AI insights
2. **Traffic Trends** - Sessions, clicks, channels, devices
3. **Search Performance** - Rankings, queries, CTR analysis
4. **Content Performance** - Landing pages, engagement
5. **Technical Health** - Core Web Vitals, performance, speed ✅ NEW
6. **AI & Innovation** - AI readiness, structured data, content audit ✅ NEW
7. **Channel & Audience** - Device comparison, efficiency
8. **Detailed Data** - Top 25 tables for deep analysis

### All 23 Charts Included

**Traffic & Search (10 charts):**
- Monthly traffic trend
- Channel performance
- Device distribution
- Search funnel
- Top query movers
- Top queries & pages
- CTR by position
- Impressions vs clicks
- GA4 landing pages
- Engagement by channel

**Technical & Innovation (7 charts):** ✅ NEW
- Core Web Vitals pass rates
- Performance score distribution
- Speed vs traffic correlation
- Technical issues summary
- AI readiness score
- Structured data coverage
- Content audit recommendations

**Audience Insights (6 charts):**
- Landing page efficiency
- Device comparison
- Channel efficiency matrix
- Engagement trend
- KPI overview
- (Plus 3 data tables)

---

## 📋 Prerequisites

### Required Files

1. **Service Account Key**
   ```bash
   # Must exist in project root
   gsc-key.json
   ```

2. **Environment Variables**
   ```bash
   # Create .env file with:
   GA4_PROPERTY_ID=341629008
   GSC_PROPERTY=https://www.cim.org/
   GROQ_API_KEY=your_key_here  # Optional for AI insights
   ```

3. **Configuration Files**
   ```bash
   tracked_speed_pages.csv      # For PageSpeed monitoring
   ai_snippet_targets.csv       # For AI verification
   content_audit_config.csv     # For content audit
   ```

### Python Dependencies

```bash
pip install -r requirements.txt
```

**Key packages:**
- google-analytics-data
- google-api-python-client
- pandas, matplotlib
- playwright (for AI verification)
- openai (for Groq API)

---

## 🔄 Recommended Workflow

### Monthly Schedule (1st of Month)

```bash
# 09:00 - Start data collection
python site_speed_monitoring.py        # 10-15 min
python ai_snippet_verification.py      # 5-10 min  
python content_audit_schedule_report.py # 2-3 min

# 09:30 - Generate dashboard
python monthly_master_report.py        # 10-15 min

# 09:45 - Review and distribute
open monthly_dashboard.html
```

### Automation (GitHub Actions)

```yaml
name: Monthly Dashboard
on:
  schedule:
    - cron: '0 9 1 * *'  # 9 AM on 1st of month
  workflow_dispatch:      # Manual trigger

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Install Playwright
        run: playwright install chromium
      
      - name: Collect PageSpeed data
        run: python site_speed_monitoring.py
      
      - name: Collect AI snippet data
        run: python ai_snippet_verification.py
      
      - name: Collect content audit data
        run: python content_audit_schedule_report.py
      
      - name: Generate monthly dashboard
        run: python monthly_master_report.py
      
      - name: Upload dashboard
        uses: actions/upload-artifact@v3
        with:
          name: monthly-dashboard
          path: |
            monthly_dashboard.html
            charts/*.png
            monthly_data/*.csv
```

---

## 🎯 Chart Status Indicators

When running the dashboard, you'll see status indicators:

```
[5/8] Generating Technical Health charts...
  ✓ Core Web Vitals              # Data available
  ✓ Performance distribution     # Data available
  ✓ Speed vs traffic            # Data available
  ✓ Technical issues            # Data available

[6/8] Generating AI & Innovation charts...
  ⚠ AI readiness                # No data (placeholder shown)
  ⚠ Structured data             # No data (placeholder shown)
  ⚠ Content freshness           # No data (placeholder shown)
```

**✓ = Real data chart**  
**⚠ = Placeholder (run supporting script first)**

---

## 🔍 Troubleshooting

### Problem: All Technical Charts Show Placeholders

**Cause:** PageSpeed data not collected

**Solution:**
```bash
python site_speed_monitoring.py
python monthly_master_report.py
```

### Problem: All AI Charts Show Placeholders

**Cause:** AI snippet data not collected

**Solution:**
```bash
python ai_snippet_verification.py
python monthly_master_report.py
```

### Problem: Content Freshness Shows Placeholder

**Cause:** Content audit data not collected

**Solution:**
```bash
python content_audit_schedule_report.py
python monthly_master_report.py
```

### Problem: Dashboard Generation Fails

**Check:**
```bash
# 1. Verify credentials
ls -la gsc-key.json

# 2. Check environment variables
cat .env

# 3. Test API access
python -c "from monthly_data_collector import get_ga4_client; get_ga4_client()"

# 4. Check data files
ls -la monthly_data/
```

---

## 📁 Output Files

### Main Dashboard
```
monthly_dashboard.html          # Self-contained HTML (~2-3 MB)
```

### Supporting Data
```
monthly_data/
├── monthly_ga4_summary.csv
├── monthly_ga4_daily.csv
├── monthly_ga4_pages_current.csv
├── monthly_ga4_channels_current.csv
├── monthly_ga4_channels_previous.csv
├── monthly_ga4_devices.csv
├── monthly_gsc_queries.csv
├── monthly_gsc_pages.csv
├── monthly_gsc_daily.csv
├── monthly_gsc_devices.csv
├── monthly_pagespeed.csv       # If PageSpeed run
├── monthly_ai_snippet.csv      # If AI verification run
└── monthly_content_audit.csv   # If content audit run
```

### Charts
```
charts/
├── monthly_*.png               # 23 chart files
└── (150 DPI, ~50KB each)
```

---

## 💡 Pro Tips

### 1. Run Supporting Scripts Weekly

Instead of monthly, run these weekly for better data:

```bash
# Weekly (every Monday)
python site_speed_monitoring.py
python ai_snippet_verification.py
python content_audit_schedule_report.py
```

Then the monthly dashboard will have the most recent data.

### 2. Cache Data for Faster Regeneration

If you need to regenerate the dashboard without re-fetching data:

```bash
# Data already in monthly_data/ directory
# Just regenerate charts and HTML
python monthly_chart_builder.py
python monthly_dashboard_generator.py
```

### 3. Test Individual Components

```bash
# Test data collection only
python monthly_data_collector.py

# Test chart generation only
python monthly_chart_builder.py

# Test AI analysis only
python monthly_ai_analyst.py

# Test HTML generation only
python monthly_dashboard_generator.py
```

### 4. Parallel Data Collection

For faster execution, run supporting scripts in parallel:

```bash
# Run all three simultaneously
python site_speed_monitoring.py &
python ai_snippet_verification.py &
python content_audit_schedule_report.py &
wait

# Then generate dashboard
python monthly_master_report.py
```

---

## 📊 Data Freshness

### PageSpeed Data
- **Source:** `site_speed_latest_snapshot.csv`
- **Updated by:** `site_speed_monitoring.py`
- **Frequency:** Run before monthly dashboard
- **Retention:** Latest snapshot only

### AI Snippet Data
- **Source:** `reports/ai_snippet_verification.csv`
- **Updated by:** `ai_snippet_verification.py`
- **Frequency:** Run before monthly dashboard
- **Retention:** Latest verification only

### Content Audit Data
- **Source:** `content_audit_candidates.csv`
- **Updated by:** `content_audit_schedule_report.py`
- **Frequency:** Run before monthly dashboard
- **Retention:** Latest audit only

---

## 🎨 Customization

### Modify Chart Appearance

Edit `monthly_chart_builder.py`:

```python
# Change colors
C_NAVY   = "#212878"  # Your brand color
C_TEAL   = "#2A9D8F"  # Your accent color

# Change chart size
figsize=(13, 4.8)     # Width x Height in inches

# Change DPI
dpi=150               # Resolution
```

### Add Custom KPIs

Edit `monthly_master_report.py`:

```python
def aggregate_monthly_kpis(data):
    kpis = {
        # ... existing KPIs ...
        "your_custom_kpi": {"curr": 0, "prev": 0},
    }
    # Calculate your KPI
    return kpis
```

### Modify Dashboard Layout

Edit `monthly_dashboard_generator.py`:

```python
# Add new section
mm_section("Your Section Title",
    mm_report_section(
        _img_tag(chart_paths.get("your_chart"), "Your chart")
    )
)
```

---

## 📈 Success Checklist

Before considering the dashboard complete, verify:

- [ ] All 23 charts generate successfully
- [ ] No placeholder messages in dashboard
- [ ] KPI values match source data
- [ ] AI insights are relevant and accurate
- [ ] Charts display correctly on mobile
- [ ] HTML file size is reasonable (~2-3 MB)
- [ ] Monday.com upload works (if configured)
- [ ] Google Sheets logging works (if configured)
- [ ] Dashboard loads in all browsers
- [ ] Data tables show correct values

---

## 🆘 Getting Help

### Check Documentation
1. `MONTHLY_DASHBOARD_README.md` - Complete reference
2. `MONTHLY_DASHBOARD_QUICKSTART.md` - User guide
3. `MONTHLY_DASHBOARD_INTEGRATION_COMPLETE.md` - Technical details
4. `PHASE_5_COMPLETE.md` - Implementation details

### Debug Mode

```bash
# Run with verbose output
python -u monthly_master_report.py

# Check individual phases
python monthly_data_collector.py
python monthly_chart_builder.py
python monthly_ai_analyst.py
python monthly_dashboard_generator.py
```

### Common Issues

1. **Missing data files** → Run supporting scripts first
2. **API errors** → Check credentials and quotas
3. **Chart errors** → Verify data format and columns
4. **HTML errors** → Check for None values in chart paths

---

## ✅ Final Checklist

**Before First Run:**
- [ ] Install all dependencies
- [ ] Configure environment variables
- [ ] Add service account key
- [ ] Create configuration CSV files
- [ ] Run supporting data collection scripts

**Monthly Workflow:**
- [ ] Run PageSpeed monitoring
- [ ] Run AI snippet verification
- [ ] Run content audit
- [ ] Generate monthly dashboard
- [ ] Review output for accuracy
- [ ] Distribute to stakeholders

**Automation:**
- [ ] Set up GitHub Actions workflow
- [ ] Configure secrets
- [ ] Test manual trigger
- [ ] Enable scheduled runs
- [ ] Monitor for failures

---

**Status:** Complete System Ready for Production ✅  
**Last Updated:** May 1, 2026  
**Version:** 1.0
