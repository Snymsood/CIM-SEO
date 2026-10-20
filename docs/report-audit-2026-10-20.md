# Report and GitHub Actions audit — October 20, 2026

## Evidence and period

Reviewed the [October 19 Actions runs](https://github.com/Snymsood/CIM-SEO/actions?query=created%3A2026-10-19) and downloaded logs and artifacts for GSC, GA4, keywords, landing pages, speed, broken links, internal links, content audit, content categories, AI snippets, Mailchimp, content strategy, GA4 events, and weekly intelligence. Compared the same report families with October 12 runs. The October 19 weekly reports cover **October 12–18 versus October 5–11**. The latest master-orchestrator run is from September 29, which explains why the workspace's older master downloads were not current evidence for this audit.

## Cross-report signals from the October 19 runs

| Signal | Oct 12–18 | Oct 5–11 | Change | Readout |
|---|---:|---:|---:|---|
| GA4 sessions | 7,041 | 14,789 | -52.4% | High-severity decline flagged by weekly intelligence. |
| GA4 Direct sessions | 3,936 | 11,231 | -65.0% | About 94% of the headline session loss came from Direct. Summed channel rows do not reconcile exactly to headline sessions, so the channel report also shows that gap. Investigate campaign mix, traffic source tagging, and collection. |
| GA4 Organic Search sessions | 2,366 | 2,747 | -13.9% | Search traffic declined much less than Direct. |
| Exported GSC query clicks | 459 | 576 | -20.3% | Limited query export, not whole-site search totals. |
| Exported GSC query impressions | 27,841 | 32,780 | -15.1% | CTR fell from 1.76% to 1.65%. |
| Tracked `form_submit` events | 525 | 505 | +4.0% | The only configured conversion event with data; event count is not unique people or leads. |
| Matched mobile PageSpeed lab score | 60.3 | 59.5 | +0.9 points | Only 15 mobile pages have scores in both periods. Two current pages hit PSI 429 errors. |
| Unique broken targets | 10 | 10 | unchanged | 34 source-link occurrences in the current run; 113 unique issues of all types. |

The paired GA4 total, GSC export, configured-event, and matched-mobile signals are now shown in **Weekly Trends** in the combined master dashboard and weekly intelligence report, with `weekly_trends.csv` for reuse. Channel and broken-target comparisons were calculated from the archived artifacts and now have dedicated in-report views. The October 12 and October 19 runs provide distinct weeks; history-based baselines will appear as more weeks accumulate.

## Findings by report and workflow

| Area | October 19 finding | Best next value or processing change |
|---|---|---|
| GA4 | Direct sessions fell 65%, while Organic Search fell 14%; engagement rate is nearly 100%. | Add a channel-by-week waterfall and a collection/engagement instrumentation check before treating the session change as solely demand. |
| GSC, keywords, landing pages | Exported-query clicks fell 20%; 8 of 25 tracked keywords improved and 8 declined. | Rank query/page pairs by impression-weighted lost clicks, separate branded demand, and label export coverage. |
| Conversions and GA4 events | `form_submit` accounts for all 525 tracked event counts; seven configured events returned zero. GA4 event report provides HTML but no joinable event CSV. | Verify event names and add a machine-readable event/landing-page extract with unique-user counts. |
| Mailchimp and content strategy | Mailchimp sent 10 campaigns totaling 128,171 emails versus 7 campaigns totaling 66,274 emails the prior week. The October strategy scorecard labelled email-clicked URLs with zero matched GA4 sessions as weak engagement. | Show rates weighted by delivered emails and segment, exclude tiny test sends from executive averages, and distinguish missing GA4 coverage from measured poor engagement. |
| Content categories | “Other” holds 55% of sessions, down from 68% in the October 12 report but still the majority. | Export top unmatched URLs by sessions and extend taxonomy before relying on category comparisons. |
| Speed and technical health | Two PSI mobile requests returned 429, while artifact quality warnings reported zero issues. Broken link check took about 8 minutes and emitted 32,444 result rows. | The local fixes surface failed scans and retry PSI calls. Next, cache stable link-target statuses and report distinct targets separately from page occurrences. |
| Internal links and content audit | 427 pages crawled; 19 flagged pages. One priority target has zero inlinks. The audit selected one refresh page from 328 candidates. | Add first-seen/last-seen status and link source examples for priority fixes; track whether selected refreshes improve later. |
| AI snippet | Seven pages were checked through a page-extraction proxy. | Keep the proxy label prominent and track page-level score movement; do not imply these are live search-engine AI answers. |
| Weekly intelligence | One high-severity anomaly, 10 decay candidates, 12 actions. An action claimed ~0 extra clicks and another inferred poor engagement from 0 matched GA4 sessions. | Require a positive click gap and measured sessions for engagement actions; add data-coverage warnings. These are corrected in the current code. |

## Pipeline defects found and corrected locally

1. **Stale master artifact in content strategy.** The workflow downloaded the old master-orchestrator artifact before current weekly artifacts. It retained the old `ga4_pages_comparison.csv` because the GA4 weekly artifact did not upload that file. This mixed periods in the scorecard and produced the recurring 1,000-row `keyword_page_mapping.csv` warning from the old master run. The workflow now uses current source artifacts, and GA4 uploads its page comparison.
2. **Backup workflows without a repository context.** The source backup failed because `gh` had no checkout or repo argument. The dependent backup reported success while its `gh` commands also failed and its shell comparisons treated empty values as counts. Both jobs now set `GH_REPO` explicitly.
3. **Misleading action queue evidence.** Broken-link occurrences were presented as unique links; zero-potential CTR recommendations were promoted; missing GA4 sessions were described as weak engagement. These now use distinct targets, a positive click opportunity, and a tracking-coverage classification.
4. **Missing scan warning.** The weekly intelligence quality section now reports mobile pages missing scores, so a paired-page average cannot appear to cover all tracked pages.
5. **Manual rerun period drift.** The shared date helper previously ended every seven-day report yesterday, so rerunning Tuesday would change Monday's October 12–18 report into October 13–19. It now holds the last completed Monday–Sunday week until the next Monday.
6. **PSI rate limits.** PageSpeed requests now retry transient 429 and server errors with bounded backoff and lower concurrency. Exhausted requests still remain visible as missing scan coverage.

## Implemented follow-ups

- **GA4:** Channel waterfall with a reconciliation note; high engagement-rate instrumentation warning; event-name verification extract; event and landing-page CSVs with unique-user counts and explicit top-page coverage.
- **Search:** Exported query/page opportunities ranked by impression-allocated lost clicks, branded demand label, and an estimate warning. The current page mapping cannot prove where previous-week clicks landed.
- **Mailchimp and categories:** Executive open/click rates now weight by estimated delivered emails and exclude sends under 100 recipients; segment rates use the same rule. The category report exports the top 100 unmatched pages and recognizes CMP, branches, careers, subscriptions, corporate membership, and other observed sections.
- **Technical and content:** Stable 2xx/3xx link-target statuses are reused for up to eight days; broken targets are counted separately from occurrences and top fixes are shown. Internal priority targets and broken issues retain first/last seen lifecycle data. The content audit retains selected-page follow-up and labels movement as observed rather than caused by a refresh. AI snippet scores show page-level changes and remain labelled as a page-extraction proxy.
- **Operations:** Manifests now carry period IDs, run IDs, source runs, generation state, and Monday delivery state. Dependent workflows reject artifacts with stale or missing provenance. A deduplicated weekly KPI history adds four-week slopes after four distinct weeks and eight-week anomaly checks after nine. Crawl logs are aggregate by default; raw rows remain available in CSVs.

## Validation still needed in live systems

Review the GA4 engagement configuration and the seven zero-count event names with the site tagging owner. The new history-based signals will become meaningful as distinct weeks accumulate. Check the first post-deploy GitHub Actions runs for artifact provenance and Monday delivery statuses; the October 19 artifacts predate the manifest fields.
