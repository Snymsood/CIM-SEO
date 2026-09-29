# Mailchimp And Content Strategy Reports

## Mailchimp Weekly Content Report

Workflow: `.github/workflows/mailchimp-weekly-report.yml`

Script: `mailchimp_weekly_report.py`

Purpose:

- Pull aggregate Mailchimp campaign performance.
- Pull aggregate campaign link-click details.
- Classify clicked links by content format.
- Produce a weekly content/email report and CSVs for downstream strategy work.

Outputs:

- `mailchimp_campaigns.csv`
- `mailchimp_campaign_reports.csv`
- `mailchimp_link_clicks.csv`
- `mailchimp_weekly_summary.csv`
- `mailchimp_weekly_summary_final.html`

Secrets:

- `MAILCHIMP_API_KEY`
- `MAILCHIMP_AUDIENCE_ID`
- `MONDAY_MAILCHIMP_ITEM_ID`

The script intentionally avoids subscriber-level activity endpoints. It uses
campaign and link aggregates only.

## Content Strategy Report

Workflow: `.github/workflows/content-strategy-report.yml`

Script: `content_strategy_report.py`

Purpose:

- Give the Web Content Manager a decision-oriented view of content performance.
- Combine search visibility, on-site engagement, email demand, internal-link
  support, and audit risk.
- Recommend refresh, promotion, repurposing, and landing-page improvements.

Inputs:

- GSC weekly/landing page outputs.
- GA4 weekly page outputs.
- Content audit candidates.
- Content category performance.
- Internal linking page summary.
- Mailchimp link clicks when available.

Outputs:

- `content_strategy_scorecard.csv`
- `content_strategy_opportunities.csv`
- `content_strategy_report_final.html`

Secret:

- `MONDAY_CONTENT_STRATEGY_ITEM_ID`

## Rollup Behavior

- Weekly SEO Intelligence loads Content Strategy and Mailchimp outputs when
  present and adds action-queue items for distribution gaps and email-interest
  engagement risks.
- The monthly master workflow downloads both new report artifacts when
  available, so their outputs are part of the monthly artifact context.
