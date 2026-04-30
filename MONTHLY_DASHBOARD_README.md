# Monthly SEO Master Dashboard

**Status:** ✅ Ready for Testing  
**Version:** 1.0  
**Last Updated:** April 30, 2026

---

## Overview

The Monthly SEO Master Dashboard is a comprehensive 8-page HTML report that provides deep insights into SEO performance across Google Analytics 4, Google Search Console, PageSpeed Insights, and content metrics.

**Generated on:** 1st of each month  
**Analyzes:** Previous complete month vs month before  
**Example:** On May 1st, shows April 2026 vs March 2026

---

## Features

### 📊 12 KPI Cards
- Sessions, Users, Engagement Rate, Avg Duration, Bounce Rate, Events/Session
- Clicks, Impressions, CTR, Avg Position, Mobile Speed, CWV Pass Rate
- Month-over-month comparison with percentage changes
- Color-coded indicators (green = improvement, red = decline)

### 📈 23 Charts
- **Page 1:** Executive overview with KPI comparison
- **Page 2:** Traffic trends (sessions, clicks, channels, devices)
- **Page 3:** Search performance (funnel, movers, top queries/pages, CTR analysis)
- **Page 4:** Content performance (landing pages, engagement, efficiency)
- **Page 5:** Technical health (Core Web Vitals, performance, speed)
- **Page 6:** AI & innovation (readiness, structured data, freshness)
- **Page 7:** Channel & audience (device comparison, efficiency, trends)
- **Page 8:** Detailed data tables (top 25 items each)

### 🤖 AI-Powered Insights
- Deterministic bullets (hard facts from data)
- AI-generated insights (cross-channel correlations, opportunities, risks)
- Powered by Groq API with llama-3.3-70b-versatile
- Graceful fallback if AI unavailable

### 📱 Responsive Design
- Self-contained HTML (no external dependencies)
- Base64-embedded charts (~2-3 MB file size)
- Works on all devices (desktop, tablet, mobile)
- MM design system (Playfair Display, JetBrains Mono, Source Serif 4)

### 🔗 Integrations
- **Monday.com:** Posts summary with top 5 insights
- **Google Sheets:** Logs KPIs for historical tracking
- **GitHub Actions:** Automated monthly generation (coming in Phase 6)

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create `.env` file:

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

### 3. Add Service Account Key

Ensure `gsc-key.json` is in project root with permissions for:
- Google Analytics Data API
- Google Search Console API

### 4. Run Dashboard

```bash
python monthly_master_report.py
```

**Runtime:** 10-15 minutes  
**Output:** `monthly_dashboard.html` + data files + charts

---

## Output Files

### Main Dashboard
- **`monthly_dashboard.html`** (~2-3 MB)
  - Self-contained HTML with embedded charts
  - 8 pages with navigation
  - Responsive design for all devices

### Data Files
- **`monthly_data/*.csv`** (10 files)
  - GA4 summary, daily, pages, channels, devices
  - GSC queries, pages, daily, devices
  - All with current vs previous month comparison

### Charts
- **`charts/*.png`** (23 files)
  - 150 DPI, 13 x 4.8 inches
  - PNG format for quality
  - Follows brand design system

### External Outputs
- **Monday.com update** (if configured)
- **Google Sheets row** (if configured)

---

## Dashboard Structure

### Page 1: Executive Overview
**Purpose:** High-level snapshot of monthly performance

**Content:**
- 12 KPI cards in 2 rows × 6 columns grid
- Executive summary with deterministic + AI bullets
- Month-over-month comparison for all metrics

**Key Insights:**
- Overall traffic trends
- Search visibility changes
- Engagement quality
- Technical health status

---

### Page 2: Traffic Trends & Patterns
**Purpose:** Understand traffic sources and patterns

**Charts:**
1. **Monthly Traffic Trend** - Dual-axis line chart
   - GA4 sessions (left axis)
   - GSC clicks (right axis)
   - Daily data points over 30 days

2. **Channel Performance** - Grouped bar chart
   - Sessions by traffic source
   - Current vs previous month
   - Top 10 channels

3. **Device Distribution** - Horizontal bar chart
   - Mobile, desktop, tablet split
   - Percentage of total sessions
   - Current month only

**Key Insights:**
- Traffic growth/decline patterns
- Channel mix changes
- Device preferences

---

### Page 3: Search Performance Deep Dive
**Purpose:** Analyze organic search visibility and rankings

**Charts:**
1. **Search Funnel** - Horizontal funnel chart
   - Impressions → Clicks → Sessions → Engaged Sessions
   - Conversion rate at each stage
   - Identifies drop-off points

2. **Top Movers (Queries)** - Lollipop chart
   - Top 5 gainers (improved ranking)
   - Top 5 losers (declined ranking)
   - Position change magnitude

3. **Top Queries** - Horizontal bar chart
   - Top 10 queries by clicks
   - Current month data

4. **Top Pages** - Horizontal bar chart
   - Top 10 landing pages by clicks
   - Current month data

5. **CTR by Position** - Scatter plot
   - Click-through rate vs average position
   - Bubble size = clicks
   - Color-coded by position band

6. **Impressions vs Clicks** - Scatter plot
   - Identifies high-impression, low-CTR queries
   - Optimization opportunities
   - Color-coded by CTR performance

**Key Insights:**
- Ranking improvements/declines
- CTR optimization opportunities
- High-potential queries
- Content performance in search

---

### Page 4: Content Performance Analysis
**Purpose:** Evaluate content effectiveness across channels

**Charts:**
1. **GA4 Landing Pages** - Horizontal bar chart
   - Top 10 pages by sessions
   - All traffic sources

2. **Engagement by Channel** - Horizontal bar chart
   - Engagement rate by traffic source
   - Quality of traffic indicator
   - Color-coded by performance

3. **Sessions vs Clicks** - Scatter plot
   - GA4 sessions vs GSC clicks
   - Landing page efficiency
   - Identifies conversion gaps

**Key Insights:**
- Top-performing content
- Channel quality differences
- Conversion efficiency
- Content gaps

---

### Page 5: Technical Health & Speed
**Purpose:** Monitor site performance and technical issues

**Charts:**
1. **Core Web Vitals** - Dashboard (placeholder)
   - LCP, INP, CLS metrics
   - Pass/fail rates
   - Trend over time

2. **Performance Distribution** - Histogram (placeholder)
   - Pages by score band
   - Mobile vs desktop

3. **Speed vs Traffic** - Scatter plot (placeholder)
   - Performance score vs sessions
   - Correlation analysis

4. **Technical Issues** - Horizontal bar chart (placeholder)
   - Issue counts by type
   - Priority levels

**Key Insights:**
- Performance bottlenecks
- User experience issues
- Technical debt
- Optimization priorities

*Note: Requires PageSpeed Insights data integration (coming soon)*

---

### Page 6: AI & Innovation Metrics
**Purpose:** Track AI readiness and structured data

**Charts:**
1. **AI Readiness** - Gauge + bar chart (placeholder)
   - Overall readiness score
   - Breakdown by category

2. **Structured Data** - Donut chart (placeholder)
   - Pages with vs without structured data
   - Coverage percentage

3. **Content Freshness** - Stacked bar chart (placeholder)
   - Pages by age band
   - Update frequency

**Key Insights:**
- AI optimization opportunities
- Structured data gaps
- Content maintenance needs
- Innovation readiness

*Note: Requires AI snippet verification data (coming soon)*

---

### Page 7: Channel & Audience Insights
**Purpose:** Understand audience behavior and channel efficiency

**Charts:**
1. **Device Comparison** - Grouped bar chart
   - GA4 sessions vs GSC clicks
   - Mobile, desktop, tablet
   - Cross-platform consistency

2. **Channel Efficiency** - Scatter plot
   - Sessions vs engagement rate
   - Bubble size = active users
   - Quality vs quantity analysis

3. **Engagement Trend** - Line chart
   - Daily engagement rate over month
   - Average line for reference
   - Identifies patterns

**Key Insights:**
- Device preferences
- Channel quality rankings
- Engagement patterns
- Audience behavior trends

---

### Page 8: Detailed Data Tables
**Purpose:** Provide granular data for deep analysis

**Tables:**
1. **Top 25 Landing Pages (GA4)**
   - Landing page, sessions, users, engagement rate

2. **Top 25 Search Queries (GSC)**
   - Query, clicks, impressions, CTR, position

3. **Top 25 Landing Pages (GSC)**
   - Page, clicks, impressions, position

**Key Insights:**
- Long-tail performance
- Detailed metrics for analysis
- Export-ready data

---

## Architecture

### Components

```
monthly_master_report.py (Orchestrator)
├── monthly_data_collector.py (Phase 1)
│   ├── GA4 API calls
│   ├── GSC API calls
│   └── CSV exports
├── aggregate_monthly_kpis() (Phase 2)
│   ├── KPI extraction
│   └── Weighted averages
├── monthly_chart_builder.py (Phase 3)
│   ├── 23 chart functions
│   └── PNG exports
├── monthly_ai_analyst.py (Phase 4)
│   ├── Deterministic bullets
│   ├── Groq API call
│   └── Unified output
├── monthly_dashboard_generator.py (Phase 5)
│   ├── HTML structure
│   ├── Base64 encoding
│   └── Self-contained output
├── upload_to_monday() (Phase 6)
│   └── Monday.com API
└── log_to_google_sheets() (Phase 7)
    └── Google Sheets API
```

### Data Flow

1. **Collection** → Fetch GA4 + GSC data for current and previous months
2. **Aggregation** → Calculate 12 KPIs with month-over-month comparison
3. **Visualization** → Generate 23 charts following brand design system
4. **Analysis** → Build deterministic + AI-powered executive insights
5. **Generation** → Create 8-page HTML with embedded charts
6. **Distribution** → Upload to Monday.com and log to Google Sheets

---

## Customization

### Modify KPIs

Edit `aggregate_monthly_kpis()` in `monthly_master_report.py`:

```python
kpis = {
    "sessions": {"curr": 0, "prev": 0},
    "your_custom_kpi": {"curr": 0, "prev": 0},  # Add here
    # ...
}
```

### Add Charts

Edit `monthly_chart_builder.py`:

```python
def chart_your_custom_chart(data):
    """Your chart description."""
    # Chart generation logic
    return _save(fig, "monthly_your_chart.png")
```

Then add to `build_all_monthly_charts()`:

```python
chart_paths["your_chart"] = chart_your_custom_chart(data.get("your_data"))
```

### Modify Dashboard Layout

Edit `monthly_dashboard_generator.py`:

```python
# Add new section
{_section("Your Section Title",
    _img_tag(chart_paths.get("your_chart"), "Your chart description")
)}
```

### Customize AI Prompts

Edit `monthly_ai_analyst.py`:

```python
prompt = f"""
Your custom prompt here...
"""
```

---

## Troubleshooting

### Common Issues

**"No data available for this period"**
- Check GA4 and GSC have data for previous month
- Verify property IDs are correct
- Check service account permissions

**"AI analysis failed"**
- Non-fatal - dashboard still generates
- Check GROQ_API_KEY is valid
- Verify API quota/limits

**"Monday.com upload failed"**
- Non-fatal - dashboard saved locally
- Check MONDAY_API_TOKEN is valid
- Verify item ID exists

**Charts show placeholders**
- Some charts require additional data sources
- PageSpeed charts need PageSpeed Insights integration
- AI charts need AI snippet verification data

### Debug Mode

```bash
# Test individual components
python monthly_data_collector.py
python monthly_chart_builder.py
python monthly_ai_analyst.py
python monthly_dashboard_generator.py
```

---

## Performance

### Benchmarks

- **Data Collection:** 5-8 minutes (12 API calls)
- **KPI Aggregation:** <5 seconds
- **Chart Generation:** 2-3 minutes (23 charts)
- **AI Analysis:** 1-2 minutes (Groq API)
- **HTML Generation:** 30 seconds (base64 encoding)
- **Distribution:** 10-20 seconds (Monday + Sheets)

**Total:** 10-15 minutes

### Optimization Tips

1. **Reduce API calls** - Limit data to top 100 items
2. **Parallel processing** - Run GA4 and GSC concurrently
3. **Chart caching** - Skip regeneration if data unchanged
4. **Compression** - Reduce DPI or use JPEG for charts

---

## Roadmap

### Phase 6: Automation (Next)
- [ ] GitHub Actions workflow
- [ ] Scheduled monthly runs
- [ ] Automated Monday.com upload
- [ ] Error notifications

### Future Enhancements
- [ ] PageSpeed Insights integration
- [ ] AI snippet verification integration
- [ ] Content audit integration
- [ ] Multi-month trend analysis
- [ ] Custom date range selection
- [ ] PDF export option
- [ ] Email distribution
- [ ] Slack notifications

---

## Support

### Documentation
- **`PHASE_5_COMPLETE.md`** - Technical documentation
- **`MONTHLY_DASHBOARD_QUICKSTART.md`** - User guide
- **`PHASE_5_SUMMARY.md`** - High-level overview

### Getting Help
1. Check documentation
2. Review error messages
3. Test individual components
4. Verify credentials

---

## License

Internal use only - CIM SEO Intelligence

---

**Version:** 1.0  
**Status:** Ready for Testing ✅  
**Next Milestone:** Phase 6 - Automation & Deployment
