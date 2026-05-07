# Weekly SEO Intelligence Layer

## What It Does

The weekly intelligence layer runs **after** all existing individual report scripts complete. It synthesises findings from every report CSV output into a single prioritised action queue and a stakeholder-ready HTML report.

It does **not** replace any existing reports. All existing pipelines (GSC weekly, GA4 weekly, keyword ranking, landing pages, site speed, broken links, internal linking, content audit, AI snippet) continue to run unchanged.

---

## Files Added

| File | Purpose |
|---|---|
| `weekly_seo_intelligence.py` | Main intelligence script — runs after all reports |
| `seo_intelligence_utils.py` | Reusable deterministic logic (scoring, anomaly detection, trend analysis) |
| `tracked_conversions.csv` | Configurable GA4 conversion event list |
| `seo_intelligence_thresholds.csv` | Configurable anomaly detection thresholds |
| `tests/test_seo_intelligence_utils.py` | 54 unit tests for deterministic logic |
| `docs/weekly-seo-intelligence.md` | This document |

## Files Modified

| File | Change |
|---|---|
| `ga4_weekly_report.py` | Added `fetch_conversion_data()`, `build_conversion_summary()`, and conversion CSV outputs |
| `google_sheets_db.py` | Added `read_sheet_as_dataframe()` for historical data read-back |
| `master_orchestrator.py` | Added intelligence layer call after existing reports |
| `.env.example` | Added new environment variables |

## Output Files (generated at runtime)

| File | Contents |
|---|---|
| `weekly_seo_action_queue.csv` | Prioritised action queue with scores |
| `weekly_seo_action_queue.json` | Same data as JSON |
| `weekly_seo_anomalies.csv` | Detected anomalies with severity and confidence |
| `weekly_content_decay_candidates.csv` | Pages losing organic traffic, scored |
| `weekly_seo_intelligence_report.html` | Full stakeholder-ready HTML report |
| `weekly_seo_intelligence_summary.json` | Machine-readable summary of the run |
| `weekly_seo_intelligence_ai_recommendations.md` | AI-generated action plan (or deterministic fallback) |
| `ga4_conversion_summary.csv` | Conversion events: current vs previous counts |
| `ga4_conversion_pages.csv` | Top converting landing pages |
| `ga4_conversion_channels.csv` | Conversions by channel group |
| `ga4_conversions_current.csv` | Raw current-period conversion event data |
| `ga4_conversions_previous.csv` | Raw previous-period conversion event data |

---

## How Conversion Tracking Works

### 1. Configure `tracked_conversions.csv`

Edit this file to add your real GA4 event names:

```csv
conversion_event,display_name,category,priority,business_value_proxy,notes
event_registration_click,Event Registration Click,Event,high,100,Click to registration platform
membership_signup_click,Membership Signup Click,Membership,high,150,Membership signup CTA
form_submit,Form Submission,Lead,high,75,Generic contact form
```

**Important:** `conversion_event` must exactly match the event name in GA4 (case-insensitive). To find your event names, go to GA4 → Reports → Engagement → Events.

### 2. How data is fetched

The system calls the GA4 Data API with `eventName` as a dimension and `eventCount` as a metric. It filters results to only the events listed in `tracked_conversions.csv`.

### 3. What happens if events return zero data

The system distinguishes between:
- **No events configured** — warning shown, conversion section skipped
- **Events configured but zero data** — warning shown suggesting event name verification
- **Events with data** — full conversion reporting enabled

Zero conversions are never silently treated as "no config". The data quality section of the intelligence report always explains what happened.

---

## How Anomaly Detection Works

Anomalies are detected using two methods:

### Method 1: Relative + Absolute Thresholds (always active)

An anomaly is flagged when **both** conditions are met:
- Percentage change exceeds the configured threshold
- Absolute change exceeds the minimum threshold

Example: clicks drop by >25% AND by at least 50 clicks.

### Method 2: Z-Score (active when 8+ weeks of history available)

When Google Sheets historical data has 8+ weeks, the system computes a z-score. A z-score ≤ -2 (or ≥ +2 for spikes) upgrades confidence to "high".

### Configuring thresholds

Edit `seo_intelligence_thresholds.csv` to adjust sensitivity:

```csv
metric,pct_threshold,absolute_threshold,direction
clicks,0.25,50,drop
sessions,0.20,100,drop
avg_position,0.0,2.0,worsen
broken_links,0.0,10,spike
```

---

## How Content Decay Detection Works

A page is a decay candidate if:
1. It has at least 50 impressions OR 20 sessions (avoids flagging tiny pages)
2. Clicks OR sessions have declined week-over-week

The decay score (0–100) is a weighted combination of:
- Click decline severity (30%)
- Session decline severity (25%)
- Impression opportunity — high impressions + low CTR (15%)
- Position decline (10%)
- CTR decline (10%)
- Conversion decline (10%)
- Priority page boost (+15 points if page is in `tracked_pages.csv` with priority=high)

Recommendations are assigned based on the dominant signal:
- Position > 20 → "Investigate ranking loss"
- CTR < 1% with 200+ impressions → "Rewrite title/meta"
- Clicks declined > 40% → "Refresh content"
- Conversion declined > 30% → "Improve CTA"

---

## How Priority Scoring Works

Each action in the queue receives a priority score (0–100):

```
priority_score =
    impact_score        × 0.40
  + urgency_score       × 0.25
  + confidence_score    × 0.20
  + business_value_score × 0.15
  - effort_score        × 0.10   (penalty)
```

Where:
- `impact_score`: high=80, medium=50, low=25
- `urgency_score`: high=85, medium=55, low=25
- `confidence_score`: high=90, medium=60, low=30
- `business_value_score`: 0–100 (passed per action)
- `effort_score`: low=20, medium=50, high=80

Actions are sorted by priority score descending and assigned rank 1, 2, 3...

---

## How AI Action Plans Are Generated

The AI action plan uses the existing Groq/Llama 3.3-70b integration.

The prompt:
1. Supplies the top 8 deterministic actions as structured evidence
2. Supplies detected anomalies
3. Supplies KPI summary with current vs previous values
4. Instructs the model to only use supplied data, cite evidence, and avoid generic advice

If `GROQ_API_KEY` is not set or the API call fails, a deterministic fallback is used that formats the action queue as a plain-text plan.

---

## How to Run Locally

```bash
# Run with all features (requires API keys in .env)
python weekly_seo_intelligence.py

# Dry run — skips Monday.com posting, uses local CSVs
python weekly_seo_intelligence.py --dry-run

# Run tests
python -m pytest tests/ -v
```

The script reads from CSVs produced by the existing report scripts. Run the individual reports first, or use the master orchestrator which runs everything in sequence.

---

## How to Enable/Disable

In your `.env` file or GitHub Actions secrets:

```env
ENABLE_WEEKLY_INTELLIGENCE=true    # Set to false to skip entirely
ENABLE_AI_ACTION_PLAN=true         # Set to false to use deterministic fallback only
MONDAY_INTELLIGENCE_ITEM_ID=xxxxx  # Monday.com item for intelligence report
```

The intelligence layer is always non-fatal. If it fails, existing reports are not affected.

---

## Known Limitations

1. **Historical trend analysis requires 8+ weeks of Google Sheets data.** Until then, anomaly detection uses simple WoW comparison only.

2. **Conversion data requires real GA4 event names.** The default `tracked_conversions.csv` contains example event names that may not match your GA4 setup. Verify event names in GA4 → Reports → Engagement → Events.

3. **Content decay uses WoW comparison only** until historical data is available. True decay detection (4-week, 12-week trends) requires the Google Sheets historical data to be populated.

4. **The intelligence report is static HTML.** No interactive filtering or drill-down is available in this version.

5. **No email delivery.** Reports are posted to Monday.com and saved locally. Email delivery is planned for a future phase.

6. **No Slack notifications.** The `SLACK_WEBHOOK_URL` variable is documented but not yet implemented.

---

## Next Planned Improvements

1. Read Google Sheets history back for 12-week trend charts
2. Add email delivery of the intelligence report
3. Add Slack webhook notification on report completion
4. Add anomaly alerting (immediate notification when high-severity anomaly detected)
5. Expand content decay to use 4-week and 12-week trends
6. Add branded vs non-branded conversion split
7. Add competitor keyword gap analysis (requires SEMrush/Ahrefs integration)
