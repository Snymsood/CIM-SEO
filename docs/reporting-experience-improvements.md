# Reporting Experience Improvements

This repo now treats each report run as a small data product, not just a script
that emits one HTML file. Weekly individual reports and monthly/master reports
all produce operational metadata alongside the user-facing report.

## Run Structure

- Weekly Monday reports remain individual workflows and upload to their own
  Monday item.
- The monthly report remains the combined executive dashboard.
- The manual master orchestrator remains an end-to-end test/run path.
- Mailchimp and Content Strategy are weekly content-focused reports:
  - `mailchimp-weekly-report.yml` creates aggregate campaign and link-click
    outputs without subscriber-level activity.
  - `content-strategy-report.yml` combines GSC, GA4, content audit, internal
    linking, category performance, and Mailchimp link clicks for Web Content
    Manager decisions.

Each run now emits:

- `report_manifest.json` - artifact inventory, source lineage, row counts,
  warning summary, GitHub run metadata.
- `reporting_quality_warnings.csv` - operational issues such as empty source
  outputs, common API row caps, high null coverage, content taxonomy gaps, and
  broken-link remediation volume.
- `reporting_artifact_index.html` - browsable download/index page for the run.
- `normalized/*_normalized.csv` - CSV copies with canonical URL columns added
  where URL-like columns are detected.

## Data Ingestion Improvements

- GSC keyword, landing page, and content audit collection limits were raised
  from 1,000 rows to 25,000 rows.
- The finalizer flags outputs that exactly hit common API caps so truncation is
  visible instead of silent.
- URL normalization strips tracking parameters, normalizes host casing, and
  adds canonical URL columns for joining GSC, GA4, PageSpeed, crawl, and content
  outputs.

## Processing Improvements

- Broken-link results now include `broken_link_unique_issues.csv`, a practical
  remediation queue grouped by unique target URL with source-page counts and
  sample anchors.
- Internal linking can reuse `discovered_internal_links.csv` from the broken
  link crawl when both run in the same workspace, avoiding a duplicate crawl.
- Mailchimp link clicks are normalized by canonical URL and can be joined into
  the Content Strategy scorecard.
- Content Strategy outputs include `content_strategy_scorecard.csv` and
  `content_strategy_opportunities.csv`.
- Monthly and master reports run the finalizer before publishing their dashboard
  artifacts, so the combined report has the same operational evidence as weekly
  reports.

## UI Improvements

- Enhanced HTML reports include a "Run Quality And Downloads" panel with:
  - CSV count
  - HTML count
  - profiled row count
  - warning count
  - links to the manifest, warning CSV, and artifact index
- Table cells containing full HTTP URLs are converted to clickable links.
- The artifact index exposes generated reports, source/processed CSVs, charts,
  JSON summaries, and normalized CSVs in one place.

## Next Best Enhancements

- Add full GSC pagination with `startRow` if any 25,000-row cap warning appears.
- Move weekly report builders toward shared report sections: What changed, Why
  it matters, What to do next, Data coverage.
- Add category-taxonomy diagnostics that list top unmatched URLs when "Other"
  dominates content category reporting.
- Cache crawl/link status between weekly runs so unchanged URLs do not need to
  be rechecked every Monday.
