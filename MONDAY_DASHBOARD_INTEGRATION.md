# Monday.com Dashboard Integration - Status & Guide

## Current Status ✅

The Monthly SEO Master Dashboard is now fully integrated with Monday.com and GitHub Pages!

### What's Working

1. **Automated Monthly Reports**: Runs automatically on the 1st of each month at 9 AM UTC
2. **Monday.com Updates**: Posts executive summary with live links
3. **GitHub Pages Deployment**: Dashboard is live and accessible online
4. **Artifact Storage**: 90-day retention for detailed analysis

---

## How It Works

### 1. Dashboard Generation
Every month (or when manually triggered), the workflow:
- Collects GA4 and GSC data for the previous month
- Generates 23 charts comparing current vs previous month
- Creates AI-powered executive summary (15 bullets)
- Builds comprehensive HTML dashboard
- Aggregates 12 KPIs

### 2. Monday.com Integration

**What Gets Posted:**
```
Monthly SEO Master Report — March 2026

Executive Summary:
• Sessions increased to 18,473 in March 2026 (+35.6% vs February 2026)
• GSC clicks increased to 7,423 (+66.8% month-over-month)
• Search impressions reached 86,771 (+16.5% MoM)
• Average search position improved to 5.5 (from 6.1 previous month)
• Engagement rate: 99.6% (+10.6% MoM)

📊 View Live Dashboard | 📥 Download Dashboard (Artifacts)

Dashboard generated on April 30, 2026
```

**Important Note About File Attachments:**
- Monday.com's API **does not support** direct HTML file uploads to updates
- Instead, we provide **two access methods**:
  1. **Live Dashboard Link**: View the dashboard online (GitHub Pages)
  2. **Artifacts Download Link**: Download the full dashboard package (HTML + CSVs + Charts)

This is **by design** and provides better accessibility than file attachments!

### 3. Access Methods

#### Method 1: Live Dashboard (Recommended)
- **URL**: https://snymsood.github.io/CIM-SEO/monthly_dashboard.html
- **Always Available**: Automatically updated each month
- **No Download Required**: View directly in browser
- **Mobile Friendly**: Responsive design

#### Method 2: GitHub Artifacts
- **Access**: Click the "Download Dashboard (Artifacts)" link in Monday.com
- **Contents**: 
  - `monthly_dashboard.html` - Full dashboard
  - `monthly_data/*.csv` - Raw data files
  - `charts/monthly_*.png` - All 23 charts
- **Retention**: 90 days
- **Use Case**: Offline viewing, archival, detailed analysis

---

## Monday.com Item Configuration

### Required GitHub Secrets
✅ `MONDAY_API_TOKEN` - Your Monday.com API token
✅ `MONDAY_MONTHLY_ITEM_ID` - The item ID for monthly reports
✅ `GOOGLE_SHEET_ID` - For KPI logging (optional)

### Finding Your Monday.com Item ID
1. Open the Monday.com item where you want reports posted
2. Look at the URL: `https://yourworkspace.monday.com/boards/123456/pulses/789012`
3. The item ID is the number after `/pulses/` (e.g., `789012`)
4. Set it in GitHub: `gh secret set MONDAY_MONTHLY_ITEM_ID -b"789012"`

---

## Google Sheets Integration (Optional)

### Purpose
Logs monthly KPIs to Google Sheets for historical tracking and trend analysis.

### Setup Required
1. **Find Service Account Email**:
   ```bash
   python show_service_account_email.py
   ```
   
2. **Share Google Sheet**:
   - Open your Google Sheet: https://docs.google.com/spreadsheets/d/19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw/edit
   - Click "Share" button
   - Add the service account email (from step 1)
   - Grant "Editor" permissions
   - Click "Send"

3. **Verify Configuration**:
   ```bash
   gh secret list | grep GOOGLE_SHEET_ID
   ```

### What Gets Logged
Each month, a new row is added with:
- Month (YYYY-MM format)
- 12 KPIs: sessions, users, engagement_rate, avg_duration, bounce_rate, events_per_session, clicks, impressions, ctr, avg_position, mobile_score, cwv_pass_rate
- Timestamp (date_added)

---

## Troubleshooting

### "No HTML file attached" in Monday.com
**This is expected!** Monday.com's API doesn't support HTML file uploads. Use the live dashboard link instead.

### Dashboard Link Returns 404
1. Check GitHub Pages is enabled: `gh api repos/Snymsood/CIM-SEO/pages`
2. Verify workflow completed successfully: `gh run list --workflow="Monthly SEO Master Dashboard"`
3. Wait 2-3 minutes after workflow completes for Pages to deploy

### Google Sheets Logging Fails
1. Verify service account has Editor access to the sheet
2. Check `GOOGLE_SHEET_ID` secret is set correctly
3. Ensure `gsc-key.json` is valid (workflow writes it from secrets)

### Monday.com Update Not Posted
1. Verify `MONDAY_API_TOKEN` is valid
2. Check `MONDAY_MONTHLY_ITEM_ID` is correct
3. Review workflow logs: `gh run view --log`

---

## Manual Trigger

To generate a report immediately (instead of waiting for the 1st of the month):

```bash
# Via GitHub CLI
gh workflow run "Monthly SEO Master Dashboard"

# Via GitHub UI
# 1. Go to Actions tab
# 2. Select "Monthly SEO Master Dashboard"
# 3. Click "Run workflow"
# 4. Select branch (main)
# 5. Click "Run workflow"
```

---

## Next Steps

### Immediate Actions
1. ✅ Verify Monday.com update has live dashboard link
2. ✅ Click the live dashboard link to view the report
3. ⏳ Share Google Sheet with service account (if using KPI logging)

### Optional Enhancements
- Add more KPIs to the dashboard
- Customize executive summary bullets
- Add email notifications
- Create Slack integration
- Add PageSpeed Insights data

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    GitHub Actions Workflow                   │
│                  (Runs 1st of each month)                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              monthly_master_report.py                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Phase 1: Data Collection (GA4 + GSC)                 │  │
│  │ Phase 2: KPI Aggregation (12 metrics)                │  │
│  │ Phase 3: Chart Generation (23 charts)                │  │
│  │ Phase 4: AI Analysis (15 bullets)                    │  │
│  │ Phase 5: HTML Dashboard Generation                   │  │
│  │ Phase 6: Monday.com Upload                           │  │
│  │ Phase 7: Google Sheets Logging                       │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                ┌─────────────┼─────────────┐
                ▼             ▼             ▼
         ┌──────────┐  ┌──────────┐  ┌──────────┐
         │ Monday   │  │  GitHub  │  │  Google  │
         │  .com    │  │  Pages   │  │  Sheets  │
         └──────────┘  └──────────┘  └──────────┘
              │              │              │
              ▼              ▼              ▼
         Executive      Live Dashboard   KPI History
         Summary        + Artifacts      Tracking
```

---

## Support

For issues or questions:
1. Check workflow logs: `gh run view --log`
2. Review this guide's troubleshooting section
3. Check the main README: `README.md`
4. Review quickstart guide: `MONTHLY_DASHBOARD_QUICKSTART.md`

---

**Last Updated**: April 30, 2026
**Dashboard URL**: https://snymsood.github.io/CIM-SEO/monthly_dashboard.html
**Workflow**: `.github/workflows/monthly-master-report.yml`
