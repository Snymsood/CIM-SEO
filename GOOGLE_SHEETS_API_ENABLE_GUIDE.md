# Google Sheets API - Enable Guide

## ✅ Test Results

Good news! The connection test revealed the exact issue:

```
Google Sheets API has not been used in project 128801356573 before or it is disabled.
```

## The Problem

The Google Sheets API is **not enabled** in your Google Cloud project. This is a simple fix!

---

## How to Fix (2 Minutes)

### Option 1: Direct Link (Fastest)

Click this link to enable the API directly:

**https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project=128801356573**

1. Click the link above
2. Click the **"Enable"** button
3. Wait 1-2 minutes for the API to activate
4. Done!

### Option 2: Manual Steps

1. Go to **Google Cloud Console**: https://console.cloud.google.com/

2. Select your project (ID: `128801356573`)

3. In the left sidebar, go to: **APIs & Services** → **Library**

4. Search for: **"Google Sheets API"**

5. Click on **"Google Sheets API"**

6. Click the **"Enable"** button

7. Wait 1-2 minutes for activation

---

## After Enabling the API

### 1. Wait a Few Minutes

Google says: *"If you enabled this API recently, wait a few minutes for the action to propagate to our systems and retry."*

Wait **2-3 minutes** after enabling.

### 2. Test the Connection

Run the test workflow again:

```bash
cd "CIM-SEO"
gh workflow run "Test Google Sheets Connection"
```

Wait 30 seconds, then check:

```bash
cd "CIM-SEO"
gh run list --workflow="Test Google Sheets Connection" --limit 1
```

You should see a ✓ status!

### 3. Verify Sheet Access

Make sure you've also shared the Google Sheet with the service account:

- **Service Account Email**: `cimseo@gsc-weekly-reporting.iam.gserviceaccount.com`
- **Google Sheet**: https://docs.google.com/spreadsheets/d/19ucIx6nVlEx6pnHyKo8ahJ158tJmo4cxAwLARNWIJZw/edit
- **Permission Level**: Editor

---

## What This Enables

Once the API is enabled and the sheet is shared, your monthly dashboard will:

✅ **Automatically log KPIs** to Google Sheets every month  
✅ **Track historical trends** (sessions, clicks, impressions, engagement, etc.)  
✅ **Build a data warehouse** for long-term analysis  
✅ **Create visualizations** from historical data  

---

## Troubleshooting

### "I clicked Enable but it still doesn't work"

Wait 2-3 minutes for the API to propagate, then try again.

### "I don't have permission to enable APIs"

You need to be a **Project Owner** or **Editor** in the Google Cloud project. Contact your Google Cloud admin.

### "The link doesn't work"

1. Go to https://console.cloud.google.com/
2. Select project ID: `128801356573`
3. Navigate to: APIs & Services → Library
4. Search for "Google Sheets API"
5. Click Enable

---

## Summary

**Current Status:**
- ✅ Service account authenticated
- ✅ Google Sheet ID configured
- ✅ Sheet shared with service account (you did this!)
- ❌ Google Sheets API not enabled ← **Fix this now!**

**Quick Fix:**
1. Click: https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project=128801356573
2. Click "Enable"
3. Wait 2-3 minutes
4. Run test: `gh workflow run "Test Google Sheets Connection"`

---

**Once this is done, your Google Sheets integration will be fully operational!** 🎉
