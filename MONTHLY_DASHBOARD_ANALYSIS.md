# Monthly Analytics Dashboard - Analysis & Proposal

**Date:** April 30, 2026  
**Status:** Analysis Complete, Ready for Implementation

---

## 1. COMPLIANCE ANALYSIS: Current Dashboard vs Design Principles

### ✅ COMPLIANT AREAS

#### Brand Palette (§1)
- **Master Orchestrator**: Fully compliant
  - All colors defined as module constants (C_NAVY, C_TEAL, C_CORAL, etc.)
  - Consistent usage across all charts
  - No raw hex strings in functions

#### Chart Styling (§6)
- **Master Orchestrator**: Fully compliant
  - `_style_ax()` helper applied to all charts
  - Proper title alignment (left), font sizes, colors
  - Spines styled correctly (top/right hidden, left/bottom C_BORDER)
  - Background colors correct (#FAFAFA for axes, white for figure)

#### Chart Sizing (§5)
- **Master Orchestrator**: Fully compliant
  - All charts use figsize=(13, 4.8) for half-page
  - dpi=150, bbox_inches="tight", facecolor="white"
  - plt.close(fig) called after every save

#### Placeholder Charts (§15)
- **Master Orchestrator**: Fully compliant
  - `_placeholder()` function returns styled empty charts
  - Never returns None for required charts

#### Number Formatting (§16)
- **Master Orchestrator**: Fully compliant
  - Uses `_fmt_cell()` for table formatting
  - Zero values render as "-"
  - Proper comma separation and decimal places

### ⚠️ PARTIAL COMPLIANCE ISSUES

#### HTML Generation Pattern
- **Master Orchestrator**: Uses custom MM design system instead of standard pattern
  - Does NOT use `pdf_report_formatter.get_pdf_css()` + `get_extra_css()` pattern (§2)
  - Uses inline styles instead of CSS classes
  - Uses CSS Grid (`grid-template-columns`) which violates WeasyPrint rules (§3)
  - **Impact**: HTML-only output works fine, but would break if PDF generation needed

#### Executive Summary (§9)
- **Master Orchestrator**: Partially compliant
  - ✅ Single unified bullet list (deterministic + AI)
  - ✅ AI output stripped of markdown
  - ✅ Graceful fallback if AI fails
  - ⚠️ Uses custom MM styling instead of standard `.exec-panel` pattern

#### Page Layout (§4)
- **Master Orchestrator**: Not applicable
  - Generates single-page HTML dashboard (no pagination)
  - Not designed for PDF output
  - **Note**: This is intentional for the master dashboard

### ❌ NON-COMPLIANT AREAS

#### CSS Compatibility (§3)
- **Master Orchestrator**: Violates WeasyPrint rules
  - Uses `display: grid` extensively (line 723)
  - Would fail if PDF generation attempted
  - **Recommendation**: Keep as-is for HTML-only, or refactor for PDF support

#### Data Fetching Architecture (§11)
- **Master Orchestrator**: Not applicable
  - Orchestrates sub-scripts, doesn't fetch data directly
  - Sub-scripts (ga4_weekly_report.py, gsc_weekly_report.py) handle fetching

#### Output Files (§13)
- **Master Orchestrator**: Simplified output
  - Only generates: index.html, charts/*.png
  - Does NOT generate: PDF, Markdown, CSV exports
  - **Note**: This is intentional - master dashboard is HTML-only

---

## 2. AVAILABLE DATA SOURCES

### Google Analytics 4 (GA4)
**Script:** `ga4_weekly_report.py`

**Metrics Available:**
- `activeUsers` - Active users count
- `sessions` - Total sessions
- `engagedSessions` - Sessions with engagement
- `engagementRate` - Percentage of engaged sessions
- `averageSessionDuration` - Average session duration (seconds)
- `eventCount` - Total events triggered

**Dimensions Available:**
- `landingPage` - Top landing pages
- `sessionDefaultChannelGroup` - Traffic channels (Organic, Direct, Referral, etc.)
- `deviceCategory` - Device split (mobile, desktop, tablet)
- `country` - Geographic distribution
- `pagePath` - Individual page paths

**Current Usage:**
- Weekly comparison (current vs previous week)
- Top 25 landing pages
- Channel performance
- Device split
- Country distribution

### Google Search Console (GSC)
**Scripts:** `gsc_weekly_report.py`, `gsc_keyword_ranking_report.py`, `gsc_landing_pages_report.py`

**Metrics Available:**
- `clicks` - Total clicks from search
- `impressions` - Total search impressions
- `ctr` - Click-through rate
- `position` - Average ranking position

**Dimensions Available:**
- `query` - Search queries
- `page` - Landing pages
- `device` - Device type
- `searchAppearance` - Rich result types (FAQ, How-to, etc.)
- `date` - Daily trends

**Current Usage:**
- Weekly comparison (current vs previous week)
- Top 1000 queries
- Top 1000 pages
- Tracked keywords (from tracked_keywords.csv)
- Device split
- Search appearance features
- New/lost queries and pages

### Site Speed (PageSpeed Insights)
**Script:** `site_speed_monitoring.py`

**Metrics Available:**
- `performance_score` - Overall performance score (0-100)
- `lcp_field_ms` - Largest Contentful Paint (field data)
- `inp_field_ms` - Interaction to Next Paint (field data)
- `cls_field` - Cumulative Layout Shift (field data)
- `lcp_lab_ms` - LCP lab data
- `tbt_lab_ms` - Total Blocking Time lab data
- `cls_lab` - CLS lab data

**Dimensions:**
- `strategy` - Mobile vs Desktop
- `page` - Individual URLs (from tracked_speed_pages.csv)

**Current Usage:**
- Weekly snapshots for tracked pages
- Mobile vs desktop comparison
- Core Web Vitals tracking

### Content Category Performance
**Script:** `content_category_performance.py`

**Combines GA4 + GSC data by content pillar:**
- Magazine
- Events
- Education
- Technical Library
- Membership
- Student/Scholarships
- News/Press
- Awards
- Institute Info
- Homepage
- Other

**Metrics per Category:**
- Sessions (GA4)
- Engagement rate (GA4)
- Average duration (GA4)
- Clicks (GSC)
- Impressions (GSC)
- Average position (GSC)

### Additional Data Sources

#### Broken Links
**Script:** `broken_link_check.py`
- Total broken links found
- 404 errors
- Redirect chains
- Server errors

#### Internal Linking
**Script:** `internal_linking_audit.py`
- Orphan pages
- Link distribution
- Anchor text analysis

#### Content Audit
**Script:** `content_audit_schedule_report.py`
- Pages needing refresh
- Archive candidates
- Performance scoring

#### AI Snippet Verification
**Script:** `ai_snippet_verification.py`
- AI readiness scores
- Hallucination risk assessment
- Structured data presence

---

## 3. MONTHLY DASHBOARD PROPOSAL

### Vision
**A comprehensive monthly analytics dashboard that combines all data sources into a unified executive view, showing trends, correlations, and actionable insights across the entire digital ecosystem.**

### Key Differences: Monthly vs Weekly

| Aspect | Weekly Reports | Monthly Dashboard |
|--------|---------------|-------------------|
| **Time Period** | 7 days vs previous 7 days | 30 days vs previous 30 days |
| **Granularity** | Day-to-day changes | Trend analysis, patterns |
| **Scope** | Single data source | Cross-channel integration |
| **Audience** | Operational teams | Executive stakeholders |
| **Focus** | Tactical actions | Strategic insights |
| **Depth** | Detailed metrics | High-level KPIs + deep dives |

### Proposed Structure

#### Page 1: Executive Overview
**KPI Grid (12 cards, 2 rows):**

**Row 1: Traffic & Engagement**
1. Total Sessions (GA4) - MoM change
2. Active Users (GA4) - MoM change
3. Engagement Rate (GA4) - MoM change
4. Avg Session Duration (GA4) - MoM change
5. Bounce Rate (GA4) - MoM change
6. Events per Session (GA4) - MoM change

**Row 2: Search Performance**
7. Total Clicks (GSC) - MoM change
8. Total Impressions (GSC) - MoM change
9. Average CTR (GSC) - MoM change
10. Average Position (GSC) - MoM change
11. Mobile Speed Score (PSI) - MoM change
12. Core Web Vitals Pass Rate (PSI) - MoM change

**Executive Summary:**
- Unified bullet list (deterministic + AI)
- Cross-channel correlations
- Strategic recommendations
- Risk flags

#### Page 2: Traffic Trends & Patterns
**Charts:**
1. **Monthly Traffic Trend** (dual-axis line)
   - Sessions (GA4) - left axis
   - Clicks (GSC) - right axis
   - Daily granularity over 30 days
   - Highlight weekends, events

2. **Channel Performance Matrix** (grouped bar)
   - Sessions by channel (Organic, Direct, Referral, Social, Email)
   - Current month vs previous month
   - Percentage change labels

3. **Device Distribution Evolution** (stacked area)
   - Mobile, Desktop, Tablet
   - Daily trend over 30 days
   - Show shift in device usage

#### Page 3: Search Performance Deep Dive
**Charts:**
1. **Search Visibility Funnel** (horizontal funnel)
   - Impressions → Clicks → Sessions → Engaged Sessions
   - Conversion rates at each stage
   - MoM comparison

2. **Keyword Position Distribution** (histogram)
   - Count of keywords by position band (1-3, 4-10, 11-20, 21-50, 51+)
   - Current vs previous month
   - Show movement between bands

3. **Top Movers - Queries** (lollipop, top 10 gainers + losers)
   - Position change (not just clicks)
   - Color-coded: teal for gains, coral for losses

4. **Search Appearance Features** (horizontal bar)
   - Impressions by rich result type
   - FAQ, How-to, Video, etc.
   - MoM comparison

#### Page 4: Content Performance Analysis
**Charts:**
1. **Content Ecosystem Map** (bubble scatter)
   - X-axis: Search Impressions (reach)
   - Y-axis: Engagement Rate (quality)
   - Bubble size: Sessions (impact)
   - Color: Content category
   - Quadrants: Champions, Hidden Gems, Broad Reach, Underperformers

2. **Content Pillar Performance** (grouped horizontal bar)
   - Sessions, Clicks, Engagement Rate by category
   - Sorted by sessions descending
   - Top 12 categories

3. **Landing Page Efficiency** (scatter)
   - X-axis: Impressions (GSC)
   - Y-axis: Sessions (GA4)
   - Identify pages with high impressions but low sessions (CTR opportunity)
   - Annotate top performers

#### Page 5: Technical Health & Speed
**Charts:**
1. **Core Web Vitals Dashboard** (3-panel gauge)
   - LCP, INP, CLS
   - Mobile vs Desktop
   - Good/Needs Improvement/Poor thresholds
   - MoM trend arrows

2. **Performance Score Distribution** (histogram)
   - Count of pages by score band (0-49, 50-89, 90-100)
   - Mobile vs Desktop
   - Target: 90% of pages in "Good"

3. **Speed vs Traffic Correlation** (scatter)
   - X-axis: Performance Score
   - Y-axis: Sessions
   - Bubble size: Engagement Rate
   - Identify high-traffic slow pages (priority fixes)

4. **Technical Issues Summary** (horizontal bar)
   - Broken links count
   - Orphan pages count
   - Pages needing refresh
   - Archive candidates

#### Page 6: AI & Innovation Metrics
**Charts:**
1. **AI Readiness Score** (gauge + bar)
   - Overall AI readiness score
   - Breakdown by content category
   - Hallucination risk assessment

2. **Structured Data Coverage** (donut)
   - Pages with structured data vs without
   - By schema type (Article, FAQ, HowTo, etc.)

3. **Content Freshness** (stacked bar)
   - Pages by last update date
   - <30 days, 30-90 days, 90-180 days, 180+ days
   - By content category

#### Page 7: Channel & Audience Insights
**Charts:**
1. **Geographic Performance** (horizontal bar + map)
   - Top 15 countries by sessions
   - MoM change
   - Engagement rate by country

2. **Channel Efficiency Matrix** (scatter)
   - X-axis: Sessions
   - Y-axis: Engagement Rate
   - Bubble size: Average Session Duration
   - Color: Channel
   - Identify high-quality channels

3. **New vs Returning Users** (stacked area)
   - Daily trend over 30 days
   - Percentage split
   - Retention indicator

#### Page 8: Detailed Data Tables
**Tables:**
1. **Top 25 Landing Pages** (GA4 + GSC merged)
   - Page, Sessions, Users, Engagement Rate, Clicks, Impressions, Position
   - MoM change columns
   - Inline bar charts for sessions

2. **Top 25 Search Queries** (GSC)
   - Query, Clicks, Impressions, CTR, Position
   - MoM change columns
   - Position band badges

3. **Content Category Summary** (merged)
   - Category, Sessions, Clicks, Engagement Rate, Avg Position
   - MoM change columns

4. **Technical Health Summary**
   - Issue type, Count, Priority, Status
   - Broken links, Orphans, Slow pages, etc.

---

## 4. IMPLEMENTATION PLAN

### Phase 1: Data Collection & Aggregation (Week 1)
**Goal:** Extend existing scripts to support monthly time windows

**Tasks:**
1. Update `seo_utils.py`:
   - Add `get_monthly_date_windows()` function
   - Returns: current_month_start, current_month_end, previous_month_start, previous_month_end

2. Create `monthly_data_collector.py`:
   - Orchestrates all data fetching with monthly windows
   - Runs in parallel (API-based) and serial (crawl-based)
   - Saves intermediate CSVs for each data source

3. Test data collection:
   - Verify all scripts work with 30-day windows
   - Check API rate limits (GSC has daily quotas)
   - Validate data completeness

**Deliverables:**
- `seo_utils.py` updated with monthly functions
- `monthly_data_collector.py` script
- Test run with sample data

### Phase 2: Chart Generation (Week 2)
**Goal:** Build all 20+ charts for the monthly dashboard

**Tasks:**
1. Create `monthly_chart_builder.py`:
   - Implement all chart functions following REPORT_DESIGN_PRINCIPLES.md
   - Use consistent styling (_style_ax helper)
   - Proper sizing (figsize=(13, 4.8) for half-page, (13, 6.5) for full-page)
   - Save to charts/ directory

2. Chart functions to implement:
   - `chart_monthly_traffic_trend()` - dual-axis line
   - `chart_channel_performance()` - grouped bar
   - `chart_device_evolution()` - stacked area
   - `chart_search_funnel()` - horizontal funnel
   - `chart_keyword_distribution()` - histogram
   - `chart_top_movers_queries()` - lollipop
   - `chart_search_appearance()` - horizontal bar
   - `chart_content_ecosystem()` - bubble scatter
   - `chart_content_pillar_performance()` - grouped horizontal bar
   - `chart_landing_page_efficiency()` - scatter
   - `chart_core_web_vitals()` - 3-panel gauge
   - `chart_performance_distribution()` - histogram
   - `chart_speed_traffic_correlation()` - scatter
   - `chart_technical_issues()` - horizontal bar
   - `chart_ai_readiness()` - gauge + bar
   - `chart_structured_data()` - donut
   - `chart_content_freshness()` - stacked bar
   - `chart_geographic_performance()` - horizontal bar
   - `chart_channel_efficiency()` - scatter
   - `chart_new_vs_returning()` - stacked area

3. Test all charts:
   - Verify styling consistency
   - Check placeholder handling for empty data
   - Validate file sizes (should be <500KB each)

**Deliverables:**
- `monthly_chart_builder.py` with all chart functions
- Sample charts generated from test data
- Chart catalog document

### Phase 3: HTML Dashboard Generation (Week 3)
**Goal:** Build the HTML dashboard with all sections

**Tasks:**
1. Create `monthly_dashboard_generator.py`:
   - Generate 8-page HTML dashboard
   - Use MM design system (matching master_orchestrator.py style)
   - Embed charts as base64 data URIs (self-contained HTML)
   - Responsive design for mobile viewing

2. Implement sections:
   - Executive Overview (KPI grid + summary)
   - Traffic Trends & Patterns
   - Search Performance Deep Dive
   - Content Performance Analysis
   - Technical Health & Speed
   - AI & Innovation Metrics
   - Channel & Audience Insights
   - Detailed Data Tables

3. Add navigation:
   - Table of contents with anchor links
   - Section headers with IDs
   - "Back to top" links

4. Styling:
   - Use Playfair Display for headers
   - JetBrains Mono for data/metrics
   - Source Serif 4 for body text
   - Black/white high-contrast design
   - 2px solid borders throughout

**Deliverables:**
- `monthly_dashboard_generator.py` script
- Sample HTML dashboard
- Mobile responsiveness tested

### Phase 4: AI Analysis Integration (Week 4)
**Goal:** Add AI-powered insights and recommendations

**Tasks:**
1. Create `monthly_ai_analyst.py`:
   - Build deterministic bullets (hard facts)
   - Build AI bullets (insights, correlations, recommendations)
   - Use Groq API with llama-3.3-70b-versatile
   - Temperature: 0.2 for consistency

2. AI prompt engineering:
   - Cross-channel correlation analysis
   - Trend identification (growth, decline, seasonality)
   - Anomaly detection
   - Strategic recommendations
   - Risk flags

3. Implement sections:
   - Executive Summary (page 1)
   - Section-specific insights (each page)
   - Strategic recommendations (final section)

4. Fallback handling:
   - Graceful degradation if AI unavailable
   - Deterministic bullets always present
   - Log AI failures for debugging

**Deliverables:**
- `monthly_ai_analyst.py` script
- Sample AI-generated insights
- Prompt templates documented

### Phase 5: Integration & Testing (Week 5)
**Goal:** Integrate all components and test end-to-end

**Tasks:**
1. Create `monthly_master_report.py`:
   - Main orchestrator script
   - Runs all phases in sequence
   - Error handling and logging
   - Progress indicators

2. Integration testing:
   - Run full pipeline with real data
   - Verify all charts generated
   - Check HTML output quality
   - Test Monday.com upload
   - Validate Google Sheets append

3. Performance optimization:
   - Parallel data fetching where possible
   - Chart generation optimization
   - HTML generation speed

4. Documentation:
   - Usage instructions
   - Configuration guide
   - Troubleshooting section

**Deliverables:**
- `monthly_master_report.py` orchestrator
- Full test run completed
- Documentation updated

### Phase 6: Automation & Deployment (Week 6)
**Goal:** Set up automated monthly generation

**Tasks:**
1. Create GitHub Actions workflow:
   - `.github/workflows/monthly-master-report.yml`
   - Schedule: First Monday of each month at 9:00 AM UTC
   - Manual trigger option (workflow_dispatch)

2. Configure secrets:
   - GSC_SERVICE_ACCOUNT_KEY
   - GROQ_API_KEY
   - MONDAY_API_TOKEN
   - MONDAY_MONTHLY_ITEM_ID
   - GOOGLE_SHEET_ID

3. Artifact upload:
   - index.html (monthly dashboard)
   - charts/*.png
   - *.csv (data exports)
   - monthly_summary.md

4. Monday.com integration:
   - Upload HTML to Monday item
   - Post summary bullets as update
   - Link to live dashboard

5. Google Sheets integration:
   - Append monthly KPIs to historical sheet
   - Create "Monthly_KPIs" tab if not exists

**Deliverables:**
- GitHub Actions workflow configured
- Automated run tested
- Monday.com integration verified
- Google Sheets historical data working

---

## 5. TECHNICAL SPECIFICATIONS

### File Structure
```
CIM-SEO/
├── monthly_master_report.py          # Main orchestrator
├── monthly_data_collector.py         # Data fetching
├── monthly_chart_builder.py          # Chart generation
├── monthly_dashboard_generator.py    # HTML generation
├── monthly_ai_analyst.py             # AI insights
├── seo_utils.py                      # Updated with monthly functions
├── .github/workflows/
│   └── monthly-master-report.yml     # Automation workflow
├── charts/                           # Chart output directory
│   └── monthly_*.png                 # Monthly charts
├── monthly_dashboard.html            # Final HTML output
└── monthly_*.csv                     # Data exports
```

### Data Flow
```
1. monthly_master_report.py (orchestrator)
   ↓
2. monthly_data_collector.py
   ├── Fetch GA4 data (30 days)
   ├── Fetch GSC data (30 days)
   ├── Fetch PageSpeed data
   ├── Fetch content category data
   ├── Fetch broken links data
   ├── Fetch internal linking data
   ├── Fetch content audit data
   └── Fetch AI snippet data
   ↓
3. Save intermediate CSVs
   ├── monthly_ga4_summary.csv
   ├── monthly_gsc_queries.csv
   ├── monthly_gsc_pages.csv
   ├── monthly_speed.csv
   ├── monthly_content_categories.csv
   └── monthly_technical_health.csv
   ↓
4. monthly_chart_builder.py
   ├── Load all CSVs
   ├── Generate 20+ charts
   └── Save to charts/monthly_*.png
   ↓
5. monthly_ai_analyst.py
   ├── Load all CSVs
   ├── Build deterministic bullets
   ├── Call Groq API for AI insights
   └── Return unified bullet list
   ↓
6. monthly_dashboard_generator.py
   ├── Load all CSVs
   ├── Load all chart paths
   ├── Load AI bullets
   ├── Generate 8-page HTML dashboard
   ├── Embed charts as base64
   └── Save as monthly_dashboard.html
   ↓
7. Upload & Integrate
   ├── Upload HTML to Monday.com
   ├── Post summary to Monday item
   ├── Append KPIs to Google Sheets
   └── Upload artifacts to GitHub Actions
```

### Performance Considerations

**API Rate Limits:**
- GSC: 1,200 queries/minute, 50,000/day
- GA4: 10 concurrent requests, 50,000/day
- PageSpeed Insights: 25,000/day
- Groq: 30 requests/minute (free tier)

**Optimization Strategies:**
1. Parallel fetching for API-based data sources
2. Sequential fetching for crawl-based sources
3. Caching intermediate results
4. Batch processing where possible
5. Rate limiting with exponential backoff

**Expected Runtime:**
- Data collection: 5-8 minutes
- Chart generation: 2-3 minutes
- HTML generation: 30 seconds
- AI analysis: 1-2 minutes
- Total: ~10-15 minutes

### Error Handling

**Graceful Degradation:**
1. If GA4 fails → Use cached data or show "unavailable"
2. If GSC fails → Use cached data or show "unavailable"
3. If AI fails → Show deterministic bullets only
4. If chart fails → Show placeholder chart
5. If Monday upload fails → Log error, continue

**Logging:**
- Console output with timestamps
- Error logs saved to monthly_report.log
- Success/failure indicators for each step

---

## 6. DESIGN PRINCIPLES COMPLIANCE CHECKLIST

### For Monthly Dashboard Implementation

**Data Fetching:**
- [ ] Use per-thread service objects for parallel GSC fetching
- [ ] Set httplib2.Http(timeout=120) for all API calls
- [ ] Use cache_discovery=False for thread safety
- [ ] Row limit = 1000 (or higher for monthly data)
- [ ] Cast all numeric columns after merge
- [ ] Handle empty DataFrames gracefully

**Charts:**
- [ ] All charts use figsize=(13, 4.8) or (13, 6.5)
- [ ] dpi=150, bbox_inches="tight", facecolor="white"
- [ ] _style_ax() applied to every axes
- [ ] Value labels on all bars
- [ ] plt.close(fig) after every save
- [ ] Placeholder chart returned (not None) when empty

**HTML Generation:**
- [ ] Self-contained HTML with base64-embedded images
- [ ] Use MM design system (Playfair Display, JetBrains Mono, Source Serif 4)
- [ ] Responsive design for mobile
- [ ] All user strings wrapped in html.escape()
- [ ] No broken img tags (check for None paths)

**Executive Summary:**
- [ ] Single unified bullet list
- [ ] Deterministic bullets first, AI bullets appended
- [ ] AI output stripped of all markdown
- [ ] Graceful fallback if AI unavailable

**Tables:**
- [ ] table-layout: fixed
- [ ] URL columns use word-break: normal, overflow-wrap: break-word
- [ ] Numeric cells have white-space: nowrap
- [ ] Delta columns use color-coded spans
- [ ] Position columns use position band badges

**Number Formatting:**
- [ ] Zero values render as "-"
- [ ] Percentages: 2 decimal places
- [ ] Large numbers: comma-separated
- [ ] Position: 1-2 decimal places
- [ ] Delta signs: explicit "+" prefix

**Integration:**
- [ ] Monday.com upload in try/except (non-fatal)
- [ ] Google Sheets append with error handling
- [ ] All outputs saved before upload
- [ ] Artifacts uploaded to GitHub Actions

---

## 7. NEXT STEPS

### Immediate Actions
1. **Review & Approve**: Stakeholder review of proposed structure
2. **Prioritize Features**: Identify must-have vs nice-to-have charts
3. **Set Timeline**: Confirm 6-week implementation schedule
4. **Assign Resources**: Determine who will implement each phase

### Questions to Answer
1. **Frequency**: Confirm monthly generation (first Monday of month)?
2. **Historical Data**: How many months of historical data to show in trends?
3. **Thresholds**: Define "good/bad" thresholds for each KPI?
4. **Alerts**: Should dashboard include automated alerts for anomalies?
5. **Distribution**: Who receives the monthly dashboard? (Monday.com, email, Slack?)

### Success Metrics
- Dashboard generates successfully on schedule
- All data sources integrated correctly
- Charts render properly on all devices
- AI insights are actionable and accurate
- Stakeholders find dashboard valuable
- Reduces manual reporting time by 80%+

---

## 8. APPENDIX: DATA DICTIONARY

### GA4 Metrics
| Metric | Description | Format |
|--------|-------------|--------|
| activeUsers | Number of distinct users who engaged | Integer |
| sessions | Total number of sessions | Integer |
| engagedSessions | Sessions lasting >10s or with conversion | Integer |
| engagementRate | Percentage of engaged sessions | Percentage (0-1) |
| averageSessionDuration | Average session length | Seconds (float) |
| eventCount | Total events triggered | Integer |

### GSC Metrics
| Metric | Description | Format |
|--------|-------------|--------|
| clicks | Total clicks from search results | Integer |
| impressions | Total times URL appeared in search | Integer |
| ctr | Click-through rate | Percentage (0-1) |
| position | Average ranking position | Float (1-100+) |

### PageSpeed Metrics
| Metric | Description | Format | Good Threshold |
|--------|-------------|--------|----------------|
| performance_score | Overall performance score | Integer (0-100) | ≥90 |
| lcp_field_ms | Largest Contentful Paint | Milliseconds | ≤2500 |
| inp_field_ms | Interaction to Next Paint | Milliseconds | ≤200 |
| cls_field | Cumulative Layout Shift | Float | ≤0.1 |

### Content Categories
- Magazine
- Events
- Education
- Technical Library
- Membership
- Student/Scholarships
- News/Press
- Awards
- Institute Info
- Homepage
- Other

---

**Document Version:** 1.0  
**Last Updated:** April 30, 2026  
**Author:** Kiro AI Assistant  
**Status:** Ready for Review
