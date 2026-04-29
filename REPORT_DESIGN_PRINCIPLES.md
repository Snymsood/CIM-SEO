# CIM SEO Report Design Principles

Established during the GSC Weekly Report redesign. Apply these principles to every report script in this project.

---

## 1. Brand Colour Palette

Define all colours as module-level constants. Never use raw hex strings inside functions.

| Constant | Hex | Usage |
|----------|-----|-------|
| C_NAVY   | #212878 | Primary brand, current-period bars, table headers, section borders |
| C_TEAL   | #2A9D8F | Secondary accent, gainers, impressions lines, device bars |
| C_CORAL  | #E76F51 | Negative/losers, declining metrics, warning states |
| C_SLATE  | #6C757D | Previous-period bars, neutral/muted elements |
| C_GREEN  | #059669 | Positive deltas, Top 3 badge, good performance |
| C_RED    | #DC2626 | Negative deltas, critical issues |
| C_AMBER  | #D97706 | Page 2 band, warnings, medium-priority items |
| C_BORDER | #E2E8F0 | All borders, grid lines, dividers |
| C_LIGHT  | #F1F5F9 | Alternate row backgrounds, panel fills |

## 2. Typography & Base CSS

All reports share the same base CSS from `pdf_report_formatter.get_pdf_css()`. Never duplicate it.

- Font: Poppins (Google Fonts), fallback Helvetica Neue, Arial
- Base body font-size: 11px
- Page: A4, 15mm margins on all sides
- Page numbers: auto-generated bottom-right via CSS counter
- Header bar: C_NAVY background, white text, 4px black bottom border, bleeds to page edges via negative margins
- h2 section headers: C_NAVY, 16px, 600 weight, 4px left border + 10px left padding
- Panel (exec summary box): #F8FAFC background, 1px C_BORDER border, 3px C_NAVY top border
- KPI cards: inline-block 22% width, white background, 3px bottom border (C_BORDER default, C_NAVY on hover)
- Delta badges: .pos = green pill, .neg = red pill, .neu = grey pill

Each report script adds its own extra CSS on top via a local `get_extra_css()` function, then combines:
```
get_pdf_css() + get_extra_css()
```

## 3. WeasyPrint CSS Compatibility Rules

WeasyPrint is the PDF renderer. It has significant CSS limitations vs browsers. These rules are mandatory.

**NEVER use:**
- `display: grid` or `grid-template-columns` — not supported, collapses to single column
- `display: flex` or `flexbox` — partial support, unreliable for layout
- CSS transitions or animations
- `position: sticky` or `position: fixed`
- CSS variables (`--my-var`)
- `calc()` in most contexts

**ALWAYS use instead:**
- `display: inline-block` with explicit `width: %` for side-by-side columns
- `float: left` / `float: right` with a `.nl-clear { clear: both }` after
- `display: block` for stacked elements
- `table-layout: fixed` on all tables
- `page-break-before: always` on `.page-section` divs to force new pages
- `page-break-inside: avoid` on chart wrappers and table rows

**Two-column layout pattern (WeasyPrint safe):**
```html
<div class="nl-wrap">  <!-- overflow:hidden -->  <div class="nl-col">...</div>  <!-- float:left; width:48% -->  <div class="nl-col-right">...</div>  <!-- float:right; width:48% -->  <div class="nl-clear"></div>  <!-- clear:both --></div>
```

## 4. Page Layout & Pagination

Every report follows this structure:

- **Page 1**: Header bar + Executive Summary panel + KPI cards. No charts.
- **Page 2+**: Charts, two per page (each half-page height).
- **Final pages**: Data tables, one section per page.

**Page section pattern:**
```html
<div class="page-section">  <!-- page-break-before: always -->  <div class="col-header">Section Title</div>  <!-- chart or table content --></div>
```

**Rules:**
- `.page-section` carries `page-break-before: always` — this is the ONLY place page breaks are forced
- Never put `page-break-before` on individual chart images
- Never put `page-break-before` on table rows
- The first page section after the header does NOT need a break (it is the natural start)
- Group two half-page charts inside one `.page-section` so they fill the page together
- Full-page charts (scatter plot) get their own `.page-section` alone

## 5. Chart Sizing & Rendering

**The core rule: size charts to fill the page, not to look good on screen.**

A4 content height at 15mm margins = ~247mm. At 150dpi, two charts of figsize=(13, 4.8) fill one page exactly.

| Chart type | figsize | Pages it occupies |
|------------|---------|-------------------|
| KPI grid (1x4 bars) | (13, 4.8) | Half page — pair with trend |
| Trend line (dual axis) | (13, 4.8) | Half page — pair with KPI grid |
| Device split (2 stacked bars) | (13, 4.8) | Half page — pair with appearance |
| Search appearance (h-bar) | (13, 4.8) | Half page — pair with device |
| Lollipop movers | (13, 4.8) | Half page — pair query + page movers |
| Scatter plot | (13, 6.5) | Full page — alone |

**Save settings (apply to every chart):**
```python
fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
```

- dpi=150: balances file size vs sharpness in PDF
- bbox_inches="tight": removes excess whitespace from the image itself
- facecolor="white": prevents transparent backgrounds rendering grey in PDF
- Always call `plt.close(fig)` immediately after saving

**Chart image CSS:**
```css
.chart-wrap { width: 100%; margin-bottom: 6px; page-break-inside: avoid; }
.chart-wrap img { width: 100%; display: block; border-radius: 4px; border: 1px solid #E2E8F0; }
```

Setting `width: 100%` on the img makes WeasyPrint scale it to the full content width, which maps the figsize height correctly.

## 6. Matplotlib Axes Styling

Every chart uses the shared `_style_ax()` helper. Apply it to every axes object.

```python
def _style_ax(ax, title="", xlabel="", ylabel=""):
    ax.set_title(title, fontsize=10, fontweight="600", color="#1A1A1A", pad=8, loc="left")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=8, color="#64748B", labelpad=4)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=8, color="#64748B", labelpad=4)
    ax.tick_params(labelsize=8, colors="#64748B", length=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(C_BORDER)
    ax.spines["bottom"].set_color(C_BORDER)
    ax.set_facecolor("#FAFAFA")
```

**Rules:**
- Title: left-aligned (`loc="left"`), 10pt, 600 weight, near-black
- Axis labels: 8pt, muted grey (#64748B)
- Tick marks: length=0 (hidden stubs), labels 8pt grey
- Remove top and right spines entirely
- Left and bottom spines: C_BORDER (#E2E8F0), not black
- Axes background: #FAFAFA (off-white, not pure white)
- Figure background: always white (`fig.patch.set_facecolor("white")`)
- Grid: dashed, alpha 0.3, color C_BORDER, zorder=1 (behind data)
- tight_layout pad: 2.0 for most charts

**Value labels on bars:**
```python
ax.text(bar.get_x() + bar.get_width()/2, bar.get_height()*1.03,
        label_str, ha="center", va="bottom", fontsize=9, color="#374151", fontweight="600")
```

**Value labels on horizontal bars:**
```python
ax.text(v + max_v*0.01, bar.get_y() + bar.get_height()/2,
        f"{v:,.0f}", va="center", fontsize=9, color="#374151")
ax.set_xlim(0, max_v * 1.18)  # always leave 18% room for labels
```

## 7. Chart Type Selection

Choose chart types based on what the data communicates, not familiarity.

| Data story | Chart type | Notes |
|------------|------------|-------|
| Current vs previous single metric | Paired bar (prev=grey, curr=brand colour) | One subplot per metric, own Y scale |
| Trend over time | Dual-axis line chart | Clicks left axis (C_NAVY), impressions right (C_TEAL), fill_between for area |
| Part-of-whole (device, channel) | Horizontal stacked bar | 100% scale, white labels inside segments |
| Rankings/top N | Horizontal bar | Sorted ascending so top item is at top, value labels on bars |
| Winners and losers | Lollipop chart | Thin line + dot, C_TEAL for gains, C_CORAL for losses, shaded halves |
| Two-variable relationship | Scatter/bubble | Bubble size = volume metric, colour = performance metric, RdYlGn colormap |
| SERP features / categories | Horizontal bar | Sorted by value, C_NAVY bars |

**Lollipop over bar chart for movers:** Lollipops show direction more clearly, fit more labels, and look cleaner at small sizes.

**Scatter plot design rules:**
- Bubble size: scale to 60-1200 range (`clip(lower=60)` prevents invisible dots)
- Colormap: RdYlGn (vivid, intuitive green=good/red=bad)
- Invert X axis when lower position number = better ranking
- Add reference band shading for performance zones (axvspan)
- Annotate top N items by the primary metric
- Always include a colorbar with a label

## 8. Table Design

**All tables use `table-layout: fixed` to prevent column width explosions.**

**URL / long-text columns:**
- CSS class `url-cell`: `overflow-wrap: break-word; word-break: normal; font-size: 8.5px`
- Truncate in Python before inserting into HTML: `short_url(str, max_len)` from seo_utils
- Max lengths: query text = 40 chars, page URLs = 45 chars, movers table = 60 chars
- Use `word-break: normal` NOT `break-all` — break-all splits mid-character and looks broken

**Numeric cells:**
- Always add `white-space: nowrap` to prevent line breaks inside numbers
- Use `_fmt(val, decimals, pct)` for consistent formatting
- Zero values render as "-" not "0"

**Delta columns:**
- Use `_delta_html(val, lower_is_better=False)` which returns a coloured span
- Green pill (.chg.pos): positive change on a metric where higher is better
- Red pill (.chg.neg): negative change, or positive change where lower is better (e.g. position)
- Grey pill (.chg.neu): zero or near-zero change

**Position band badges:**
```python
def position_band_html(pos):
    if p <= 3:  return Top 3 badge (green)
    if p <= 10: return Page 1 badge (blue)
    if p <= 20: return Page 2 badge (amber)
    return Page 3+ badge (red)
```

**Inline bar columns:**
- Add a proportional bar div inside the clicks/impressions cell
- Width = (value / max_value) * 100%, capped at 80px max-width
- Height: 8px, border-radius: 3px
- Renders the magnitude visually without a separate chart

**Row striping:** `tr:nth-child(even) td { background: #F8FAFC }` — always on

**Movers table:** Single table with losers first, gainers below. Left border colour-coded: C_TEAL for gains, C_CORAL for losses. No separate tables.

**New/Lost block:** Float-based two-column layout (not grid). Left = new items (C_TEAL header), right = lost items (C_CORAL header).

## 9. Executive Summary Section

**One panel, one bullet list. No separate "Executive Read" and "AI Commentary" sections.**

Structure:
1. Deterministic bullets first — hard metric facts computed in Python, always present even if AI fails
2. AI-generated bullets appended to the same list — interpretation, risks, recommendations

```html
<div class="exec-panel">
  <div class="panel-label">Executive Summary</div>
  <ul class="exec-bullets">
    <li>Deterministic bullet 1</li>
    <li>Deterministic bullet 2</li>
    <li>AI bullet 1</li>
    <li>AI bullet 2</li>
  </ul>
</div>
```

**AI prompt rules:**
- Output ONLY bullet points. No headings, no bold, no markdown symbols, no numbered lists.
- Each bullet is one sentence. Maximum 10 bullets total.
- Strip all markdown from AI output before rendering: remove `**`, `__`, `*`, leading `-•*·▪▸`
- If AI fails, the deterministic bullets still render — never show an empty section

**Deterministic bullet rules:**
- Include actual numbers with WoW comparison and % change
- Flag new/lost item counts
- Flag branded concentration if >= 40% of top traffic
- Keep each bullet to one sentence

**Section label style:**
```css
.panel-label { font-size: 9px; text-transform: uppercase; letter-spacing: 0.8px; color: #64748B; font-weight: 700; }
```

## 10. KPI Cards

Four cards in a row using `display: inline-block`, each 22% wide with 2.5% right margin.

Each card shows:
- Label: 9px uppercase, C_SLATE
- Current value: 22px bold, C_NAVY
- Previous value: 10px, #94A3B8 ("Prev: X")
- Delta badge: % change, colour-coded (.pos/.neg/.neu)

Use `build_card(title, current, previous, is_pct=False, decimals=0)` from pdf_report_formatter.

**Colour logic for delta:**
- Starts with "+" → .pos (green)
- Starts with "-" and is not just "-" → .neg (red)
- Otherwise → .neu (grey)

**Note on position metric:** Position is lower-is-better. The delta badge will show red for an increase (worsening) and green for a decrease (improvement). Handle this by passing the raw % change — the sign already reflects the direction correctly since position going from 11 to 10 is a negative change (-9%) which renders as green.

## 11. Data Fetching Architecture

**Parallel fetching with thread-safe service objects.**

The `googleapiclient` service object is NOT thread-safe. Sharing one service across threads causes connection races and timeouts.

**Pattern:**
```python
def _build_thread_service():
    """Each worker thread calls this to get its own independent service."""
    authed_http = google_auth_httplib2.AuthorizedHttp(
        get_credentials(), http=httplib2.Http(timeout=120)
    )
    return build("searchconsole", "v1", http=authed_http, cache_discovery=False)

def fetch_all_data_parallel(...):
    def _run(fn, *args):
        svc = _build_thread_service()  # fresh service per thread
        return fn(svc, *args)

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {executor.submit(_run, fn, *args): key ...}
```

**Rules:**
- httplib2.Http(timeout=120): 120 second timeout prevents silent hangs
- cache_discovery=False: avoids file-system cache contention between threads
- Every API call is wrapped in try/except returning an empty DataFrame on failure
- Log each result with checkmark/cross so failures are visible in CI logs
- After merge, always cast numeric columns with pd.to_numeric(errors="coerce").fillna(0)
  to prevent dtype=object errors when both DataFrames are empty

**Row limits:** Always use 1000 (not 250). The API supports up to 25,000.

## 12. Data Processing Patterns

**Week-over-week comparison:**
```python
def prepare_comparison(current_df, previous_df, key_column):
    # Rename columns to _current / _previous
    # Outer merge (keeps items that appeared in only one period)
    # Cast all numeric columns to float after merge
    # Compute _change columns (current - previous)
    # Add is_new flag: previous==0 and current>0
    # Add is_lost flag: previous>0 and current==0
    # Sort by current metric descending
```

**KPI aggregation:**
- Clicks/impressions: sum()
- CTR: derive from totals (total_clicks / total_impressions), never average the CTR column
- Position: mean() of rows where impressions > 0 only (avoids zero-impression rows skewing average)

**Graceful empty data:**
- Every chart function checks `if df.empty: return placeholder_chart` — never return None for a chart that has its own page
- Charts that are optional (device split, appearance) can return None — the HTML template checks before rendering
- Tables show "No data available" message when empty

**URL shortening:**
```python
short_url(url, max_len)  # from seo_utils — truncates with "..."
```
- Query text: max_len=40
- Page URLs: max_len=45
- Movers table: max_len=60
- Chart labels: max_len=52

## 13. Output Files

Every report script produces the same set of outputs in the same order:

1. **CSV files** — raw and comparison DataFrames, saved before any report generation
2. **Charts** — saved to `charts/` directory, all PNG at dpi=150
3. **HTML** — `{report_name}_summary.html`, base_url=os.getcwd() for WeasyPrint image paths
4. **PDF** — `{report_name}_summary.pdf` via WeasyPrint
5. **Markdown** — `{report_name}_summary.md` for text-based summaries
6. **Google Sheets** — append key DataFrames via `append_to_sheet(df, tab_name)`
7. **Monday.com** — upload PDF via `upload_pdf_to_monday()` in a try/except (never fatal)

**Chart path handling:**
- `build_all_charts()` returns a dict of `{name: Path | None}`
- HTML template uses `chart_paths.get("name")` — returns None if chart was skipped
- `_img(path, alt)` returns empty string if path is None — no broken img tags

**Monday.com upload is always non-fatal:**
```python
try:
    upload_to_monday()
except Exception as e:
    print(f"Monday upload failed: {e}")
```

## 14. Section Headers in HTML

Use `.col-header` for all section titles inside the report body (not h2 tags).

```css
.col-header {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.7px;
    font-weight: 700;
    color: #212878;
    border-left: 3px solid #212878;
    padding-left: 8px;
    margin-top: 20px;
    margin-bottom: 8px;
}
```

The first `.col-header` on a page uses `style="margin-top:0;"` to avoid extra space at the top.

Do NOT use `<h2>` tags inside the report body — they carry too much margin and the border-left style conflicts with the page-section layout.

## 15. Placeholder Charts for Empty Data

When a chart has no data, return a styled placeholder image instead of None.

```python
if df.empty:
    fig, ax = plt.subplots(figsize=(13, 4.8))
    fig.patch.set_facecolor("white")
    ax.text(0.5, 0.5, "No data available for this period.",
            ha="center", va="center", fontsize=12, color="#94A3B8",
            transform=ax.transAxes)
    ax.set_axis_off()
    return _save(fig, "chart_name.png")
```

This prevents blank pages in the PDF. The placeholder renders as a clean white box with a muted message.

Return None only for charts that are truly optional and whose section in the HTML template is conditionally rendered.

## 16. Number Formatting

Use these helpers consistently. Never format numbers inline with f-strings in HTML generation.

| Function | Usage |
|----------|-------|
| `_fmt(val, decimals=0, pct=False)` | Table cells — returns "-" for zero/NaN |
| `_delta_html(val, decimals=0, lower_is_better=False)` | Delta columns — returns coloured span |
| `format_pct_change(current, previous)` | KPI cards — returns "+X.X%" or "-X.X%" |
| `format_num(val, decimals, as_percent)` | General formatting from pdf_report_formatter |
| `format_delta(val, decimals)` | Delta formatting from pdf_report_formatter |

**Rules:**
- Zero values always render as "-" in tables (not "0" or "0.00%")
- Percentages: always 2 decimal places (e.g. "12.84%")
- Large numbers: always comma-separated thousands (e.g. "14,864")
- Position: always 1-2 decimal places (e.g. "10.6")
- Delta signs: always explicit "+" prefix for positive values
- NaN/None: always "-"

**HTML escaping:**
Always wrap user-facing strings in `html.escape()` before inserting into HTML templates.
```python
f"<td>{html.escape(str(value))}</td>"
```

## 17. AI Integration Pattern

**Model:** Groq API with llama-3.3-70b-versatile via OpenAI-compatible SDK

```python
client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[
        {"role": "system", "content": "You write polished weekly executive SEO briefs as bullet points only."},
        {"role": "user",   "content": prompt},
    ],
    temperature=0.2,
)
```

**Prompt rules:**
- temperature=0.2: low randomness for consistent corporate tone
- System prompt: one sentence describing the output format and persona
- User prompt: structured data (CSV snippets) + explicit format instructions
- Always specify: "Output ONLY bullet points. No headings, no bold, no markdown symbols."
- Always specify word/bullet count limits
- Always specify: "Do not invent data"

**Output cleaning:**
```python
for line in raw.splitlines():
    clean = line.strip().lstrip("-*+•·▪▸").strip()
    clean = clean.replace("**","").replace("__","").replace("*","").strip()
    if clean:
        bullets.append(clean)
```

**Fallback:** If GROQ_API_KEY is not set or the call fails, return an empty list (deterministic bullets still render). Never crash the report.

## 18. GitHub Actions Workflow Pattern

Every report has its own workflow file in `.github/workflows/`.

**Standard structure:**
```yaml
name: Report Name
on:
  workflow_dispatch:
  schedule:
    - cron: "0 13 * * 1"  # Monday 13:00 UTC
jobs:
  report-job:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: echo "${{ secrets.GSC_SERVICE_ACCOUNT_KEY }}" > gsc-key.json
      - name: Run report
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          MONDAY_API_TOKEN: ${{ secrets.MONDAY_API_TOKEN }}
          MONDAY_ITEM_ID: ${{ secrets.MONDAY_ITEM_ID }}
          GOOGLE_SHEET_ID: ${{ secrets.GOOGLE_SHEET_ID }}
        run: python report_script.py
      - uses: actions/upload-artifact@v4
        with:
          name: report-name
          path: |
            *.csv
            *.html
            *.pdf
            *.md
            charts/
```

**Rules:**
- Always include `workflow_dispatch` so reports can be triggered manually
- Always upload artifacts including charts/ directory
- Never hardcode secrets — always use GitHub Secrets
- Service account key is written to disk from secret, never committed

## 19. Script Structure Template

Every report script follows this section order:

```
# 1. Imports
# 2. Constants (auth, config, colours, patterns)
# ═══════════════════
# DATA FETCHING
# ═══════════════════
# 3. API client / service builder
# 4. Individual fetch functions (each returns DataFrame or empty DataFrame)
# 5. Parallel fetch orchestrator
# ═══════════════════
# DATA PROCESSING
# ═══════════════════
# 6. Comparison / delta computation
# 7. KPI aggregation
# 8. Helper formatters (_fmt, _delta_html, position_band_html)
# ═══════════════════
# CHART GENERATION
# ═══════════════════
# 9. _style_ax() helper
# 10. _save() helper
# 11. Individual chart functions
# 12. build_all_charts() orchestrator
# ═══════════════════
# AI ANALYSIS
# ═══════════════════
# 13. build_deterministic_bullets()
# 14. build_ai_bullets()
# 15. build_unified_executive_bullets()
# ═══════════════════
# HTML TABLE BUILDERS
# ═══════════════════
# 16. Table builder functions
# ═══════════════════
# CSS
# ═══════════════════
# 17. get_extra_css()
# ═══════════════════
# HTML REPORT BUILDER
# ═══════════════════
# 18. _img() helper
# 19. write_html_summary()
# 20. write_markdown_summary()
# 21. generate_pdf()
# 22. upload_to_monday()
# ═══════════════════
# MAIN
# ═══════════════════
# 23. main()
# 24. if __name__ == "__main__": main()
```

Use `# ══════` section dividers (double-line box drawing) to visually separate major sections.

## 20. Quick Reference Checklist

Before shipping any redesigned report script, verify:

**Data:**
- [ ] Row limit is 1000 (not 250)
- [ ] Parallel fetching with per-thread service objects
- [ ] All numeric columns cast after merge
- [ ] Empty DataFrame handled gracefully at every step

**Charts:**
- [ ] All charts use figsize=(13, 4.8) or (13, 6.5) for full-page
- [ ] dpi=150, bbox_inches="tight", facecolor="white"
- [ ] _style_ax() applied to every axes
- [ ] Value labels on all bars
- [ ] plt.close(fig) called after every save
- [ ] Placeholder chart returned (not None) when data is empty

**Layout:**
- [ ] No display:grid or flexbox in CSS
- [ ] Two-column layouts use float:left/right
- [ ] Page breaks via .page-section (page-break-before:always)
- [ ] Two half-page charts grouped in one .page-section
- [ ] chart-wrap has page-break-inside:avoid (not page-break-before)

**Tables:**
- [ ] table-layout: fixed
- [ ] URL columns use url-cell class (word-break:normal, overflow-wrap:break-word)
- [ ] Numeric cells have white-space:nowrap
- [ ] Delta columns use _delta_html()
- [ ] Position columns use position_band_html()

**Executive Summary:**
- [ ] Single panel, single bullet list
- [ ] Deterministic bullets first, AI bullets appended
- [ ] AI output stripped of all markdown before rendering
- [ ] Falls back gracefully if AI unavailable

**General:**
- [ ] All user strings wrapped in html.escape()
- [ ] Monday upload in try/except (non-fatal)
- [ ] All outputs saved before report generation
- [ ] Script runs standalone (if __name__ == "__main__")

---

*Last updated: April 2026 — based on gsc_weekly_report.py redesign*
