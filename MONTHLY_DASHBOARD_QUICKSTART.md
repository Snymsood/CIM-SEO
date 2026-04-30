# Monthly Dashboard Quick Start Guide

**Last Updated:** April 30, 2026  
**Status:** Ready for Testing

---

## Overview

The Monthly SEO Master Dashboard is a comprehensive 8-page HTML report that analyzes the previous month's SEO performance across GA4, GSC, PageSpeed, and content metrics.

**Key Features:**
- 📊 12 KPI cards with month-over-month comparison
- 📈 23 charts covering all aspects of SEO performance
- 🤖 AI-powered executive insights
- 📱 Responsive design for mobile viewing
- 🔗 Self-contained HTML (no external dependencies)

---

## Quick Start

### 1. Prerequisites

**Required Files:**
- `gsc-key.json` - Google Service Account credentials
- `.env` file with required environment variables

**Required Python Packages:**
```bash
pip install -r requirements.txt
```

**Key Dependencies:**
- `google-analytics-data>=0.16.0`
- `google-api-python-client>=2.0.0`
- `pandas>=1.3.0`
- `matplotlib>=3.4.0`
- `python-dateutil>=2.8.0`
- `openai>=1.0.0` (for Groq API)

### 2. Environment Variables

Create or update your `.env` file:

```bash
# Required
GA4_PROPERTY_ID=341629008
GSC_PROPERTY=https://www.cim.org/

# Optional (for AI insights)
GROQ_API_KEY=your_groq_api_key_here

# Optional (for distribution)
MONDAY_API_TOKEN=your_monday_token_here
MONDAY_MONTHLY_ITEM_ID=your_item_id_here
GOOGLE_SHEET_ID=your_sheet_id_here
```

### 3. Run the Dashboard

```bash
python monthly_master_report.py
```

**Expected Runtime:** 10-15 minutes

**Output:**
- `monthly_dashboard.html` - Main dashboard file
- `monthly_data/*.csv` - 10 data files
- `charts/*.png` - 23 chart images
- Monday.com update (if configured)
- Google Sheets row (if configured)

---

## What Gets Generated

### Dashboard Structure

**Page 1: Executive Overview**
- 12 KPI cards (sessions, users, clicks, impressions, etc.)
- Executive summary with AI-powered insights
- Month-over-month comparison for all metrics

**Page 2: Traffic Trends & Patterns**
- Monthly traffic trend (sessions + clicks)
- Channel performance comparison
- Device distribution

**Page 3: Search Performance Deep Dive**
- Search visibility funnel
- Top query movers (gainers + losers)
- Top queries and pages
- CTR by position analysis
- Impressions vs clicks opportunities

**Page 4: Content Performance Analysis**
- Top GA4 landing pages
- Engagement rate by channel
- Landing page efficiency (sessions vs clicks)

**Page 5: Technical Health & Speed**
- Core Web Vitals (placeholder)
- Performance distribution (placeholder)
- Speed vs traffic correlation (placeholder)
- Technical issues summary (placeholder)

**Page 6: AI & Innovation Metrics**
- AI readiness score (placeholder)
- Structured data coverage (placeholder)
- Content freshness (placeholder)

**Page 7: Channel & Audience Insights**
- Device comparison (GA4 vs GSC)
- Channel efficiency matrix
- Engagement rate trend

**Page 8: Detailed Data Tables**
- Top 25 landing pages (GA4)
- Top 25 search queries (GSC)
- Top 25 landing pages (GSC)

---

## Understanding the Output

### KPI Cards

Each KPI card shows:
- **Current Value** - Last complete month (e.g., April)
- **Previous Value** - Month before that (e.g., March)
- **Change** - Percentage change (green = good, red = bad)

**Example:**
```
SESSIONS
45,234
prev 42,156
+7.3%  ← Green badge (improvement)
```

### Executive Summary

The executive summary includes:
1. **Deterministic Bullets** (always present)
   - Hard facts from data
   - Sessions, clicks, impressions changes
   - Position changes
   - Top channel and device split

2. **AI Bullets** (if Groq API configured)
   - Cross-channel correlations
   - Strategic opportunities
   - Performance trends
   - Risks and recommendations

### Charts

All charts follow the brand design system:
- **Navy (#212878)** - Primary brand color
- **Teal (#2A9D8F)** - Secondary brand color
- **Coral (#E76F51)** - Decline/warning color
- **Green (#059669)** - Success/improvement color
- **Slate (#6C757D)** - Neutral/previous period

**Chart Types:**
- Bar charts - Comparisons and rankings
- Line charts - Trends over time
- Scatter plots - Correlations and efficiency
- Funnel charts - Conversion stages
- Lollipop charts - Movers (gainers/losers)

---

## Troubleshooting

### Common Issues

**1. "GA4_PROPERTY_ID not set"**
```bash
# Solution: Add to .env file
GA4_PROPERTY_ID=341629008
```

**2. "gsc-key.json not found"**
```bash
# Solution: Ensure service account key is in project root
ls -la gsc-key.json
```

**3. "No data available for this period"**
- Check that GA4 and GSC have data for the previous month
- Verify property IDs are correct
- Check service account permissions

**4. "AI analysis failed"**
- This is non-fatal - dashboard will still generate
- Check GROQ_API_KEY is valid
- Verify Groq API quota/limits

**5. "Monday.com upload failed"**
- This is non-fatal - dashboard is still saved locally
- Check MONDAY_API_TOKEN is valid
- Verify MONDAY_MONTHLY_ITEM_ID exists

### Debug Mode

To see detailed error messages:

```bash
# Run with Python's verbose mode
python -u monthly_master_report.py

# Or check individual components
python monthly_data_collector.py
python monthly_chart_builder.py
python monthly_ai_analyst.py
python monthly_dashboard_generator.py
```

---

## Testing Individual Components

### Test Data Collection

```bash
python monthly_data_collector.py
```

**Expected Output:**
- 10 CSV files in `monthly_data/` directory
- Console output showing progress
- No errors

### Test Chart Generation

```bash
python monthly_chart_builder.py
```

**Expected Output:**
- 23 PNG files in `charts/` directory
- Console output showing each chart
- No errors

### Test AI Analysis

```bash
# Requires data collection to run first
python monthly_data_collector.py
python monthly_ai_analyst.py
```

**Expected Output:**
- Console output with bullet points
- Deterministic bullets always present
- AI bullets if Groq API configured

### Test Dashboard Generation

```bash
# Requires data collection and charts to run first
python monthly_data_collector.py
python monthly_chart_builder.py
python monthly_dashboard_generator.py
```

**Expected Output:**
- `monthly_dashboard.html` file
- File size ~2-3 MB
- Opens in browser successfully

---

## Scheduling

### Manual Run (1st of Month)

```bash
# On May 1st, generates April vs March report
python monthly_master_report.py
```

### Automated Run (GitHub Actions)

Coming in Phase 6 - will run automatically on 1st of each month at 9 AM.

---

## Best Practices

### When to Run

**Recommended:** 1st of the month at 9 AM
- Ensures previous month is complete
- Gives time for data to settle in GA4/GSC
- Aligns with monthly reporting cycle

**Avoid:**
- Last day of month (data may be incomplete)
- First few hours of 1st (data may still be processing)

### Data Freshness

- **GA4:** Usually available within 24-48 hours
- **GSC:** Usually available within 2-3 days
- **Recommendation:** Run on 2nd or 3rd of month for most accurate data

### File Management

**Keep:**
- `monthly_dashboard.html` - Archive by month
- `monthly_data/*.csv` - Keep for historical analysis

**Can Delete:**
- `charts/*.png` - Embedded in HTML, can regenerate

**Archive Structure:**
```
archives/
├── 2026-04/
│   ├── monthly_dashboard.html
│   └── monthly_data/
├── 2026-05/
│   ├── monthly_dashboard.html
│   └── monthly_data/
└── ...
```

---

## Performance Tips

### Speed Up Data Collection

1. **Reduce API calls:**
   - Limit landing pages to top 100 (currently 1000)
   - Reduce query limit (currently 1000)

2. **Parallel processing:**
   - GA4 and GSC could run concurrently
   - Would require code modification

### Reduce File Size

1. **Chart compression:**
   - Reduce DPI from 150 to 100
   - Use JPEG instead of PNG (lossy)

2. **Data tables:**
   - Reduce from top 25 to top 10
   - Remove less important columns

---

## FAQ

**Q: How long does it take to run?**  
A: 10-15 minutes for full pipeline

**Q: Can I run it for a different month?**  
A: Not currently - it always analyzes the previous complete month. Would require code modification.

**Q: What if I don't have Groq API key?**  
A: Dashboard will still generate with deterministic bullets only (no AI insights)

**Q: Can I customize the charts?**  
A: Yes - edit `monthly_chart_builder.py` to modify chart styling, colors, or data

**Q: How do I share the dashboard?**  
A: The HTML file is self-contained - just email or upload to Monday.com

**Q: Can I view on mobile?**  
A: Yes - the dashboard is responsive and works on all devices

**Q: What browsers are supported?**  
A: All modern browsers (Chrome, Firefox, Safari, Edge)

**Q: Can I export to PDF?**  
A: Yes - use browser's "Print to PDF" function

---

## Support

### Getting Help

1. **Check this guide** - Most common issues covered
2. **Check error messages** - Usually indicate the problem
3. **Test individual components** - Isolate the failing part
4. **Check credentials** - Most issues are authentication-related

### Reporting Issues

When reporting issues, include:
- Error message (full text)
- Which phase failed
- Environment variables (redact sensitive values)
- Python version
- Operating system

---

## Next Steps

1. **Test the dashboard** - Run with real data
2. **Review output** - Check all pages render correctly
3. **Share with stakeholders** - Get feedback on content
4. **Iterate** - Adjust based on feedback
5. **Automate** - Set up GitHub Actions (Phase 6)

---

**Document Version:** 1.0  
**Last Updated:** April 30, 2026  
**Status:** Ready for Testing ✅
