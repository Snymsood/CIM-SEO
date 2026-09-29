# CIM SEO Reporting Operating Model

## Weekly Monday Reports

Weekly scheduled workflows are individual reports. Each report posts to its own Monday.com item and uploads its own GitHub Actions artifact.

Scheduled Monday flow:

| Time UTC | Workflow | Monday item secret | Purpose |
|---:|---|---|---|
| 13:00 | `gsc-weekly-report.yml` | `MONDAY_GSC_ITEM_ID` | Overall GSC weekly report |
| 13:15 | `keyword-ranking-review.yml` | `MONDAY_GSC_KEYWORD_ITEM_ID` | Tracked keyword movement |
| 13:30 | `critical-landing-pages.yml` | `MONDAY_GSC_LANDING_ITEM_ID` | Tracked landing pages |
| 13:45 | `site-speed-monitoring.yml` | `MONDAY_SITE_SPEED_ITEM_ID` | PageSpeed and CWV monitoring |
| 14:00 | `broken-link-check.yml` | `MONDAY_BROKEN_LINK_ITEM_ID` | Broken link and redirect audit |
| 14:15 | `ga4-weekly-report.yml` | `MONDAY_GA4_WEEKLY_ITEM_ID` | GA4 weekly traffic and conversions |
| 14:30 | `internal-linking-audit.yml` | `MONDAY_INTERNAL_LINK_ITEM_ID` | Internal linking audit |
| 14:45 | `ga4-event-report.yml` | `MONDAY_EVENT_REPORT_ITEM_ID` | Custom GA4 event tracking report |
| 15:00 | `content-audit-schedule.yml` | `MONDAY_CONTENT_AUDIT_ITEM_ID` | Refresh/archive recommendations |
| 15:15 | `content-category-performance.yml` | `MONDAY_CONTENT_CATEGORY_ITEM_ID` | Content category performance |
| 15:30 | `ai-snippet-verification.yml` | `MONDAY_AI_SNIPPET_ITEM_ID` | AI snippet readiness |
| 16:30 | `weekly-seo-intelligence.yml` | `MONDAY_INTELLIGENCE_ITEM_ID` | Weekly action queue from the individual artifacts |

## Monthly Combined Report

`monthly-master-report.yml` is the combined monthly executive report. It downloads the latest successful individual weekly artifacts and builds one monthly dashboard/report, posted to `MONDAY_MONTHLY_ITEM_ID`.

If an input artifact is missing, the monthly workflow may regenerate that local input for the dashboard, but it does not post regenerated individual reports to weekly Monday items.

## Manual Full-System Test

`master-orchestrator.yml` is manual-only. It is used for live full-system testing and uploads Actions artifacts, but it does not run on the weekly schedule and does not publish to GitHub Pages.
