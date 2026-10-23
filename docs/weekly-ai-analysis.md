# Staged AI analysis for the weekly specialist email

## Current data and model

The repository uses the **Groq API**, with `openai/gpt-oss-120b` as the default
model. Groq is the inference provider; GPT-OSS is the model. The repo does not
currently use Google's Gemma or xAI's Grok. `GROQ_MODEL` can override the model,
but the staged analyst expects JSON Schema output and GPT-OSS reasoning
controls. No new provider account is required.

The source Actions run **weekly on Monday** for the previous completed
Monday–Sunday week. The project does not yet retain a daily artifact for every
source. The October 12–18 validated intelligence artifact contained 13 source
runs. Combining its 64 normalized CSVs with eight detailed portfolio CSVs gives
72 files and 109,978 *file rows* in the saved sample. The live workflow also
profiles raw source CSVs with no normalized counterpart. Many files overlap or
repeat crawl edges, so this is not a count of distinct visits, pages, or events.
The analyst processes every row of these files in deterministic profiles;
it does not claim to have received a separate daily feed that the project does
not collect.

## Analysis flow

1. Confirm all source run periods match and that GSC and GA4 sources exist.
   Include detailed four-site portfolio files and, when available, the
   separately scoped 28-day GA4 custom-event exports ending on the same Sunday.
2. Stream every row in each measured normalized or otherwise uncovered source CSV,
   excluding static tracking lists and report configuration. Record row counts, numeric
   distributions, key categorical breakdowns, and high-signal row examples.
   `row_sum` means a sum across that file's rows, **not** an authoritative site
   total. Keep large link and query-edge tables as aggregates rather than
   copying tens of thousands of rows into a prompt.
3. Analyze six domains independently: search visibility; GA4 behavior and
   conversion; technical links and speed; content and email distribution;
   four-site portfolio; AI answer verification. Each prompt has specialist
   interpretation rules and yields up to three cited findings.
4. Give all domain findings in compact form, plus cross-source trends, anomalies,
   and quality warnings, to a separate synthesis call. It proposes up to four
   cross-report patterns with citations, confidence, and a next check.
5. Recheck each proposed pattern against its exact cited file or row record in
   a separate verification call. Unsupported causal links and wrong metric
   scopes are rewritten or dropped. Retain proposed and verified patterns in
   the artifact so a specialist can audit what was filtered.
6. Validate cited evidence IDs against the profiled rows/files. The five
   deterministic personal actions remain separate. The email adds a concise
   “Patterns across the reports” section with analysis coverage and explicit
   data gaps. If AI is unavailable or only some domains succeed, the email
   labels that status instead of presenting a fabricated complete analysis.

The full analyst outputs are `weekly_ai_evidence.json`,
`weekly_ai_analysis.json`, and `weekly_ai_usage.json` in the 90-day weekly
intelligence artifact. The email includes only the synthesis; the category
reviews remain available for detailed follow-up.

## Interpretation rules

The prompts distinguish branded, editorial, membership, and event intent;
query versus page measurements; GSC clicks versus GA4 sessions; newsletter
clicks versus on-site sessions; unique broken targets versus repeated link
edges; PageSpeed lab results versus rolling field Core Web Vitals; and each
mini-site's own scope. The model treats correlation as a hypothesis, identifies
measurement alternatives, and provides a verification step before recommending
content or technical changes. Untrusted page titles, URLs, and CSV cells are
data, not instructions.

## Capacity and model choice

[Groq's public rate-limit table](https://console.groq.com/docs/rate-limits)
currently lists `openai/gpt-oss-120b` at 30 requests/minute, 1,000
requests/day, 8,000 tokens/minute, and 200,000 tokens/day. These are shared at
the organization level and the account's actual limits may differ; check the
Groq Limits page. The model has a [131,072-token context window](https://console.groq.com/docs/model/openai/gpt-oss-120b),
but the per-minute throughput limit is the practical constraint here. Six
domain calls, one synthesis call, and one cited-evidence verification call use bounded packets, are paced, and retry
HTTP 429 using `retry-after`. `weekly_ai_usage.json` records returned token
usage and remaining-limit headers so the next run gives an account-specific
capacity picture. Other report workflows also consume the same Groq budget.

Groq [supports strict JSON Schema output](https://console.groq.com/docs/structured-outputs)
for GPT-OSS-120B and [reasoning effort controls](https://console.groq.com/docs/reasoning).
That is sufficient for this first implementation. Add a second free cloud
model only after reviewing real failed calls and judged output quality; a second
provider would add credentials, quotas, and maintenance without increasing the
quality of the input evidence.

## Important limits

- The model sees exact rollups over every file row and selected examples, not
  all 110,000 raw rows verbatim. Inspect the source CSVs for an exhaustive
  page-level audit.
- Evidence-ID validation blocks citations to nonexistent input records, but it
  cannot prove a model's interpretation is correct. Keep a human review step
  for significant SEO or marketing decisions.
- Day-by-day anomaly detection requires a separate daily ingestion layer or
  day-granularity exports from the sources. The current pipeline operates on
  completed weekly source artifacts.
