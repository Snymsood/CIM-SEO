# Google Sheets Usage Overview

## Summary

Yes! Google Sheets is used by **5 different scripts** in your SEO reporting system. All scripts write to the **same Google Sheet** to create a centralized data warehouse.

---

## Google Sheet Configuration

**Sheet ID**: `19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw`  
**Sheet Name**: CIM SEO Database  
**URL**: https://docs.google.com/spreadsheets/d/19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw/edit

**Service Account**: `cimseo@gsc-weekly-reporting.iam.gserviceaccount.com`  
**Permission**: Editor (required for writing data)

---

## Scripts Using Google Sheets

### 1. **GSC Weekly Report** (`gsc_weekly_report.py`)

**Workflow**: `.github/workflows/gsc-weekly-report.yml`  
**Schedule**: Every Monday at 9 AM UTC  
**Purpose**: Google Search Console weekly analysis

**Tabs Created/Updated**:
- `GSC_Query_Comparison` - Top search queries with week-over-week comparison
- `GSC_Page_Comparison` - Top landing pages with performance metrics
- `GSC_Device_Split` - Performance breakdown by device type (desktop, mobile, tablet)

**Data Logged**: Clicks, impressions, CTR, position, change percentages

---

### 2. **GA4 Weekly Report** (`ga4_weekly_report.py`)

**Workflow**: `.github/workflows/ga4-weekly-report.yml`  
**Schedule**: Every Monday at 9 AM UTC  
**Purpose**: Google Analytics 4 weekly analysis

**Tabs Created/Updated**:
- `GA4_Summary` - Key metrics summary (sessions, users, engagement, bounce rate)
- `GA4_Top_Pages` - Top performing pages by sessions
- `GA4_Top_Channels` - Traffic breakdown by channel (organic, direct, referral, etc.)
- `GA4_Device_Split` - Sessions and engagement by device category
- `GA4_Country_Split` - Geographic performance breakdown

**Data Logged**: Sessions, users, engagement rate, bounce rate, page views, conversions

---

### 3. **Site Speed Monitoring** (`site_speed_monitoring.py`)

**Workflow**: `.github/workflows/site-speed-monitoring.yml`  
**Schedule**: Every Monday at 9 AM UTC  
**Purpose**: PageSpeed Insights monitoring

**Tabs Created/Updated**:
- `Site_Speed_Snapshot` - Current performance scores for all monitored URLs
- `Site_Speed_Comparison` - Week-over-week performance changes

**Data Logged**: Performance scores, FCP, LCP, TBT, CLS, Speed Index, opportunities

---

### 4. **Monthly Master Report** (`monthly_master_report.py`)

**Workflow**: `.github/workflows/monthly-master-report.yml`  
**Schedule**: 1st of each month at 9 AM UTC  
**Purpose**: Comprehensive monthly SEO dashboard

**Tabs Created/Updated**:
- `monthly_kpis` - Monthly KPI summary with 12 key metrics

**Data Logged**:
- month (YYYY-MM format)
- sessions
- users
- engagement_rate
- avg_duration
- bounce_rate
- events_per_session
- clicks
- impressions
- ctr
- avg_position
- mobile_score
- cwv_pass_rate
- date_added (timestamp)

---

### 5. **Test Script** (`test_google_sheets_connection.py`)

**Workflow**: `.github/workflows/test-google-sheets.yml`  
**Schedule**: Manual trigger only  
**Purpose**: Verify Google Sheets connection and permissions

**Tabs Created/Updated**:
- `_connection_test` (temporary, deleted after test)

**Data Logged**: Test data only (not persistent)

---

## Data Architecture

### Centralized Data Warehouse

All scripts write to the **same Google Sheet**, creating a unified data warehouse:

```
CIM SEO Database (Google Sheet)
├── GSC_Query_Comparison      (Weekly GSC query data)
├── GSC_Page_Comparison       (Weekly GSC page data)
├── GSC_Device_Split          (Weekly GSC device data)
├── GA4_Summary               (Weekly GA4 summary)
├── GA4_Top_Pages             (Weekly GA4 page data)
├── GA4_Top_Channels          (Weekly GA4 channel data)
├── GA4_Device_Split          (Weekly GA4 device data)
├── GA4_Country_Split         (Weekly GA4 country data)
├── Site_Speed_Snapshot       (Weekly speed scores)
├── Site_Speed_Comparison     (Weekly speed changes)
└── monthly_kpis              (Monthly KPI summary)
```

### Data Retention

- Each script **appends** new rows (doesn't overwrite)
- Every row includes a `date_added` column for historical tracking
- Data accumulates over time for trend analysis
- No automatic cleanup (you control retention)

---

## Benefits of Centralized Google Sheets

### 1. **Historical Tracking**
- All data is timestamped and preserved
- Build trend charts over weeks/months/years
- Compare performance across different time periods

### 2. **Easy Analysis**
- Use Google Sheets formulas, pivot tables, charts
- Export to Excel, Data Studio, or other BI tools
- Share with stakeholders without code access

### 3. **Data Integration**
- Combine GSC + GA4 + Speed data in one place
- Cross-reference metrics across different sources
- Build custom dashboards and reports

### 4. **Backup & Recovery**
- Automatic version history in Google Sheets
- Download CSV exports anytime
- Restore previous versions if needed

---

## Workflow Schedule Summary

| Script | Frequency | Day | Time (UTC) | Tabs Updated |
|--------|-----------|-----|------------|--------------|
| GSC Weekly Report | Weekly | Monday | 9:00 AM | 3 tabs |
| GA4 Weekly Report | Weekly | Monday | 9:00 AM | 5 tabs |
| Site Speed Monitoring | Weekly | Monday | 9:00 AM | 2 tabs |
| Monthly Master Report | Monthly | 1st | 9:00 AM | 1 tab |

**Total**: 11 tabs updated automatically with historical data!

---

## How to Access Your Data

### View in Google Sheets
https://docs.google.com/spreadsheets/d/19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw/edit

### Export Data
1. Open the Google Sheet
2. Select a tab (e.g., "monthly_kpis")
3. File → Download → CSV or Excel

### Query with SQL
Use Google Sheets Query function:
```
=QUERY(monthly_kpis!A:M, "SELECT A, B, C WHERE A > date '2026-01-01' ORDER BY A DESC")
```

### Connect to BI Tools
- Google Data Studio (Looker Studio)
- Tableau
- Power BI
- Any tool that supports Google Sheets connector

---

## Troubleshooting

### "Permission denied" errors
- Verify the service account has Editor access
- Check: `cimseo@gsc-weekly-reporting.iam.gserviceaccount.com`

### "API not enabled" errors
- Ensure Google Sheets API is enabled in Google Cloud Console
- Project: `gsc-weekly-reporting`

### Missing tabs
- Tabs are created automatically on first run
- If a script hasn't run yet, the tab won't exist

### Test the connection
```bash
cd CIM-SEO
gh workflow run "Test Google Sheets Connection"
```

---

## Summary

✅ **5 scripts** use Google Sheets  
✅ **11 tabs** with different data types  
✅ **1 centralized database** for all SEO data  
✅ **Automatic historical tracking** with timestamps  
✅ **Weekly + Monthly updates** on schedule  

Your Google Sheets database is the **single source of truth** for all your SEO metrics! 📊
