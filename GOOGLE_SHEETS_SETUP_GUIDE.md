# Google Sheets Setup Guide

## Test Results Summary

✅ **Service account key file found**  
✅ **Google Sheet ID configured**: `19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw`  
✅ **Successfully authenticated with Google Sheets API**  
❌ **ERROR: Cannot access spreadsheet** - Service account needs permission

---

## What This Means

The Google Sheets integration is **almost ready**! The authentication is working, but the service account doesn't have permission to access your Google Sheet yet.

---

## How to Fix (3 Simple Steps)

### Step 1: Find Your Service Account Email

Run this command locally:
```bash
cd CIM-SEO
python3 show_service_account_email.py
```

This will display something like:
```
================================================================================
SERVICE ACCOUNT EMAIL
================================================================================

seo-reporting@your-project.iam.gserviceaccount.com

================================================================================
```

**Copy that email address!**

### Step 2: Share Your Google Sheet

1. Open your Google Sheet:  
   https://docs.google.com/spreadsheets/d/19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw/edit

2. Click the **"Share"** button (top right corner)

3. In the "Add people and groups" field, paste the service account email

4. Change the permission dropdown to **"Editor"**

5. **IMPORTANT**: Uncheck "Notify people" (the service account doesn't need an email notification)

6. Click **"Send"** or **"Share"**

### Step 3: Verify the Connection

Run the test workflow again:
```bash
gh workflow run "Test Google Sheets Connection"
```

Wait about 30 seconds, then check the results:
```bash
gh run list --workflow="Test Google Sheets Connection" --limit 1
```

If successful, you should see a ✓ status!

---

## What Happens After Setup

Once the service account has access, the monthly dashboard will automatically:

1. **Log KPIs to Google Sheets** every month
2. **Create a "monthly_kpis" tab** if it doesn't exist
3. **Append a new row** with 12 metrics:
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

4. **Build historical trends** over time for analysis

---

## Troubleshooting

### "I can't find the service account email"

Make sure you're in the CIM-SEO directory and have the `gsc-key.json` file. If you don't have it locally, you can extract it from GitHub secrets:

```bash
# This won't work locally, but you can see it in the workflow logs
gh run view --log | grep "client_email"
```

Alternatively, check your Google Cloud Console:
1. Go to https://console.cloud.google.com/
2. Select your project
3. Go to "IAM & Admin" → "Service Accounts"
4. Find the service account and copy its email

### "The sheet still doesn't work after sharing"

1. Verify the service account email is correct
2. Make sure you granted "Editor" permissions (not just "Viewer")
3. Wait a few minutes for permissions to propagate
4. Run the test workflow again

### "I want to use a different Google Sheet"

Update the GitHub secret:
```bash
gh secret set GOOGLE_SHEET_ID -b"your-new-sheet-id"
```

The sheet ID is the long string in the URL:
```
https://docs.google.com/spreadsheets/d/[THIS-IS-THE-SHEET-ID]/edit
```

---

## Current Configuration

- **Google Sheet ID**: `19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw`
- **Sheet URL**: https://docs.google.com/spreadsheets/d/19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw/edit
- **GitHub Secret**: ✅ Configured
- **Service Account**: ✅ Authenticated
- **Sheet Access**: ⏳ Pending (needs sharing)

---

## Next Steps

1. ✅ Run `python3 show_service_account_email.py` to get the email
2. ⏳ Share your Google Sheet with that email (Editor permissions)
3. ⏳ Run the test workflow to verify: `gh workflow run "Test Google Sheets Connection"`
4. ⏳ Check the test results: `gh run list --workflow="Test Google Sheets Connection" --limit 1`

Once the test passes, your monthly dashboard will automatically log KPIs to Google Sheets! 🎉

---

**Need Help?**
- Check the main documentation: `MONDAY_DASHBOARD_INTEGRATION.md`
- Review the quickstart guide: `MONTHLY_DASHBOARD_QUICKSTART.md`
- View workflow logs: `gh run view --log`
