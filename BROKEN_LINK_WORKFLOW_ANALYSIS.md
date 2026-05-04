# Broken Link Check Workflow & Pipeline Analysis

**Complete Technical Documentation**  
*Generated: May 3, 2026*

---

## Table of Contents

1. [Overview](#overview)
2. [Data Sources](#data-sources)
3. [Processing Pipeline](#processing-pipeline)
4. [Display & Reporting](#display--reporting)
5. [Integration Points](#integration-points)
6. [Workflow Automation](#workflow-automation)
7. [Data Flow Diagram](#data-flow-diagram)
8. [Technical Details](#technical-details)

---

## Overview

The Broken Link Check system is a **crawl-based technical SEO audit tool** that identifies broken links, redirects, and server errors across CIM's web properties. It operates as a standalone pipeline with its own reporting system and does **not currently integrate** with the monthly dashboard.

### Key Characteristics
- **Execution**: Weekly automated runs (Mondays at 2:00 PM UTC)
- **Scope**: 8 CIM domains with configurable priority levels
- **Technology**: Async Python crawler with AI-powered analysis
- **Output**: Self-contained HTML report + CSV data files
- **Delivery**: Monday.com updates with attached reports

---

## Data Sources

### 1. Seed Domain Configuration

**File**: `broken_link_seed_domains.csv`

```csv
seed_url,scope_type,priority
https://www.cim.org/,domain,high
https://convention.cim.org/,domain,high
https://memo.cim.org/,domain,medium
https://mrmr.cim.org/,domain,high
https://mrr.cim.org/,domain,medium
https://magazine.cim.org/en/,domain,medium
https://mines-et-environnement.cim.org/,domain,medium
https://capitalprojects.cim.org/,domain,low
```

**Purpose**: Defines starting points for the crawler

**Columns**:
- `seed_url`: Entry point URL for crawling
- `scope_type`: Always "domain" (future: could support "path" or "page")
- `priority`: Importance level (high/medium/low) - currently informational

### 2. Crawl Constraints

**Configuration** (in `broken_link_check.py`):
```python
MAX_PAGES_PER_DOMAIN = 150      # Max pages to crawl per domain
REQUEST_TIMEOUT = 30            # HTTP request timeout (seconds)
CRAWL_DELAY_SECONDS = 0.5       # Delay between requests
```

**Allowed Hosts**: Extracted from seed URLs
- Only links within these domains are crawled
- External links are ignored

**Blocked Extensions**: 
```python
.pdf, .jpg, .jpeg, .png, .gif, .webp, .svg,
.zip, .xml, .json, .doc, .docx, .xls, .xlsx,
.ppt, .pptx, .mp4, .mp3
```

---

## Processing Pipeline

### Phase 1: Crawling (Synchronous)

**Function**: `crawl_site(seed_df)`

**Process**:
1. **Initialize**:
   - Create queue with seed URLs
   - Track visited pages per domain
   - Set up allowed hosts filter

2. **Breadth-First Crawl**:
   ```python
   while queue:
       current_url = queue.popleft()
       
       # Skip if already visited
       if current_url in visited_pages:
           continue
       
       # Check domain page limit
       if host_page_counts[host] >= MAX_PAGES_PER_DOMAIN:
           continue
       
       # Fetch page
       response = fetch_page(current_url)
       
       # Extract links if HTML
       if is_html_response(response):
           links = extract_links_from_html(current_url, response.text)
           discovered_links.extend(links)
           
           # Add new links to queue
           for link in links:
               if should_crawl_url(link["target_url"]):
                   queue.append(link["target_url"])
       
       # Rate limiting
       time.sleep(CRAWL_DELAY_SECONDS)
   ```

3. **Link Extraction**:
   - Parse HTML with BeautifulSoup
   - Extract `<a href>` tags
   - Capture anchor text (truncated to 200 chars)
   - Normalize URLs (remove fragments, resolve relative paths)
   - Filter to allowed hosts only

**Output**: DataFrame with columns:
- `source_url`: Page where link was found
- `target_url`: Destination URL
- `anchor_text`: Link text

**Typical Results**: 
- ~150 pages crawled per domain
- ~1,200 total pages across 8 domains
- ~5,000-10,000 unique links discovered

---

### Phase 2: Link Validation (Asynchronous)

**Function**: `evaluate_links(links_df)`

**Process**:
1. **Extract Unique Targets**:
   ```python
   unique_targets = links_df["target_url"].dropna().unique()
   ```

2. **Concurrent Checking** (max 15 simultaneous):
   ```python
   async def _check_one_link(session, semaphore, url):
       async with semaphore:
           # Try HEAD request first
           resp = await session.head(url, allow_redirects=True)
           
           # Fallback to GET if HEAD fails (405 or 5xx)
           if resp.status == 405 or resp.status >= 500:
               resp = await session.get(url, allow_redirects=True)
           
           return {
               "status_code": resp.status,
               "final_url": str(resp.url),
               "redirect_count": len(resp.history),
               "error": None
           }
   ```

3. **Issue Classification**:
   ```python
   def classify_status(status_code, error, redirect_count):
       if error:
           return "error"           # Timeout, connection error
       if status_code >= 500:
           return "server_error"    # 5xx errors
       if status_code in (404, 410):
           return "broken"          # Not found, gone
       if 400 <= status_code < 500:
           return "client_error"    # Other 4xx
       if redirect_count > 0:
           return "redirect"        # 3xx with redirects
       if 200 <= status_code < 300:
           return "ok"              # Success
       return "other"
   ```

**Output**: Enhanced DataFrame with additional columns:
- `status_code`: HTTP response code
- `final_url`: URL after redirects
- `redirect_count`: Number of redirect hops
- `error`: Error message (if failed)
- `issue_type`: Classification (broken/redirect/error/ok)

---

### Phase 3: AI Analysis

**Function**: `build_ai_analysis(results_df)`

**Process**:
1. **Filter Issues**:
   ```python
   issue_df = results_df[results_df["issue_type"] != "ok"]
   top_issues = issue_df.head(20)  # Top 20 for AI context
   ```

2. **Generate Prompt**:
   ```python
   prompt = f"""
   You are writing a concise broken-link monitoring summary for SEO stakeholders.
   
   Write:
   1. Executive Summary
   2. Key Technical Risks
   3. Priority Fix Areas
   4. Recommended Actions
   
   Requirements:
   - professional corporate tone
   - under 300 words
   - do not invent data
   - focus on internal link integrity and crawl hygiene
   
   Issue sample:
   {top_issues.to_csv(index=False)}
   """
   ```

3. **API Call**:
   - **Model**: Llama 3.3 70B (via Groq)
   - **Temperature**: 0.2 (deterministic)
   - **Max Tokens**: ~300 words

**Output**: Markdown-formatted executive analysis

**Fallback**: If API fails, returns deterministic summary from `build_executive_read()`

---

### Phase 4: Report Generation

**Function**: `write_html_summary(results_df, ai_analysis)`

**Report Structure**:

1. **Header** (Minimalist Monochrome design):
   - Title: "Broken Link Check"
   - Eyebrow: "CIM SEO — Technical Audit"
   - Meta: Generation date + source count

2. **KPI Grid** (4 cards):
   - Source Pages
   - Broken (404/410)
   - 4xx Other
   - 5xx Errors

3. **Executive Summary**:
   - Deterministic bullets (crawl stats)
   - AI-generated analysis

4. **Issue Tables** (top 50 each):
   - Broken Links (404/410)
   - Other 4xx Links
   - 5xx Server Errors
   - Redirected Internal Links
   - Request Errors

**Design System**: Matches other CIM SEO reports
- Fonts: Playfair Display, JetBrains Mono, Source Serif 4
- Colors: Black/white with minimal gray accents
- Layout: Responsive grid with thick rules

**Output Files**:
- `broken_link_summary.html` (with external image refs)
- `broken_link_summary_final.html` (self-contained with base64 images)

---

### Phase 5: Data Export

**Function**: `main()`

**CSV Outputs**:

1. **`discovered_internal_links.csv`**:
   - All links found during crawl
   - Columns: source_url, target_url, anchor_text

2. **`broken_link_results.csv`**:
   - All links with validation results
   - Columns: source_url, target_url, anchor_text, status_code, final_url, redirect_count, error, issue_type

3. **`broken_link_issues_only.csv`**:
   - Filtered to issues only (excludes "ok")
   - Same columns as results

**Use Cases**:
- Historical tracking
- Bulk analysis in spreadsheets
- Integration with other tools

---

## Display & Reporting

### HTML Report Features

**Self-Contained Design**:
- All CSS inlined
- All images embedded as base64 (if any)
- No external dependencies
- Opens in any browser

**Responsive Layout**:
- Desktop: Full-width tables with horizontal scroll
- Mobile: Stacked layout with readable text

**Interactive Elements**:
- Hover effects on table rows
- Clickable URLs (open in new tab)
- Smooth scrolling

**Accessibility**:
- Semantic HTML5
- ARIA labels where needed
- High contrast (black/white)
- Readable font sizes

### Report Sections Detail

#### 1. Executive Summary
```
The crawler checked internal links across 147 source pages.
23 broken links returned 404 or 410.
5 additional client-error links returned other 4xx responses.
2 links returned 5xx server errors.
87 internal links resolved through redirects.
```

#### 2. Broken Links Table
| Source URL | Broken Target | Anchor Text | Status | Issue Type |
|------------|---------------|-------------|--------|------------|
| https://www.cim.org/about | https://www.cim.org/old-page | Learn More | 404 | broken |

#### 3. Redirected Links Table
| Source URL | Original Target | Final URL | Redirects | Final Status |
|------------|-----------------|-----------|-----------|--------------|
| https://www.cim.org/home | http://www.cim.org/home | https://www.cim.org/ | 2 | 200 |

---

## Integration Points

### Current Integrations

#### 1. Monday.com Upload

**Function**: `upload_to_monday()`

**Process**:
1. Create text update with summary
2. Attach `broken_link_summary_final.html`
3. Post to configured item

**Configuration**:
```bash
MONDAY_API_TOKEN=your_token
MONDAY_ITEM_ID=11404485394  # Broken Link Check item
```

**Update Format**:
```
Broken Link Audit attached as self-contained HTML.

[Attached: broken-link-check.html]
```

#### 2. GitHub Actions Artifacts

**Workflow**: `.github/workflows/broken-link-check.yml`

**Artifacts Uploaded**:
- broken_link_seed_domains.csv
- discovered_internal_links.csv
- broken_link_results.csv
- broken_link_issues_only.csv
- broken_link_summary.html
- broken_link_summary_final.html

**Retention**: 90 days (GitHub default)

### Missing Integrations

#### ❌ Monthly Dashboard

**Current State**: Broken link data is **NOT** included in the monthly dashboard

**Evidence**:
- `monthly_master_report.py` does not import or reference broken link data
- `monthly_dashboard_generator.py` has no broken link section
- No broken link charts in `monthly_chart_builder.py`

**Potential Integration Points**:

1. **Technical Health Section**:
   ```python
   # In monthly_master_report.py
   from broken_link_check import load_latest_results
   
   broken_link_data = load_latest_results()
   kpis["broken_links"] = {
       "curr": broken_link_data["broken_count"],
       "prev": broken_link_data["prev_broken_count"]
   }
   ```

2. **Technical Issues Summary**:
   - Add KPI card: "Broken Links"
   - Add chart: "Link Health Trend"
   - Add table: "Top 10 Broken Links"

#### ❌ Google Sheets Logging

**Current State**: No historical tracking in Google Sheets

**Recommended Schema**:
```
Sheet: broken_link_history
Columns:
- date (YYYY-MM-DD)
- source_pages_crawled
- total_links_checked
- broken_count (404/410)
- client_error_count (4xx)
- server_error_count (5xx)
- redirect_count
- error_count
```

---

## Workflow Automation

### GitHub Actions Workflow

**File**: `.github/workflows/broken-link-check.yml`

**Trigger**:
```yaml
on:
  workflow_dispatch:           # Manual trigger
  schedule:
    - cron: "0 14 * * 1"      # Every Monday at 2:00 PM UTC
```

**Steps**:
1. Checkout repository
2. Set up Python 3.11
3. Install dependencies (`requirements.txt`)
4. Run `broken_link_check.py`
5. Upload artifacts

**Environment Variables**:
```yaml
env:
  GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
  MONDAY_API_TOKEN: ${{ secrets.MONDAY_API_TOKEN }}
  MONDAY_ITEM_ID: "11404485394"
```

**Runtime**: ~5-10 minutes (depends on site size)

### Master Orchestrator

**File**: `master_orchestrator.py`

**Execution Order**:
```python
# Group 2: Crawl-based pipelines (sequential)
await run_script("broken_link_check.py", broken_link_env)
await run_script("internal_linking_audit.py", internal_link_env)
await run_script("content_audit_schedule_report.py", content_audit_env)
```

**Why Sequential**: Avoid overloading cim.org servers with concurrent crawls

**Environment**:
```python
broken_link_env = {
    "MONDAY_ITEM_ID": os.getenv("MONDAY_BROKEN_LINK_ITEM_ID", "")
}
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    BROKEN LINK CHECK PIPELINE                    │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────┐
│  DATA SOURCES        │
├──────────────────────┤
│ • Seed Domains CSV   │
│ • CIM Web Properties │
│ • HTTP Responses     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  PHASE 1: CRAWLING (Synchronous)                                 │
├──────────────────────────────────────────────────────────────────┤
│  Function: crawl_site()                                          │
│  • Load seed domains                                             │
│  • Breadth-first crawl (max 150 pages/domain)                   │
│  • Extract <a href> links from HTML                              │
│  • Normalize URLs, filter to allowed hosts                       │
│  • Rate limit: 0.5s delay between requests                       │
│                                                                   │
│  Output: discovered_internal_links.csv                           │
│  Columns: source_url, target_url, anchor_text                    │
└──────────┬───────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  PHASE 2: VALIDATION (Asynchronous)                              │
├──────────────────────────────────────────────────────────────────┤
│  Function: evaluate_links()                                      │
│  • Extract unique target URLs                                    │
│  • Concurrent HEAD requests (max 15 simultaneous)                │
│  • Fallback to GET on 405/5xx                                    │
│  • Track redirects, status codes, errors                         │
│  • Classify: broken/redirect/error/ok                            │
│                                                                   │
│  Output: broken_link_results.csv                                 │
│  Columns: + status_code, final_url, redirect_count,              │
│            error, issue_type                                     │
└──────────┬───────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  PHASE 3: AI ANALYSIS                                            │
├──────────────────────────────────────────────────────────────────┤
│  Function: build_ai_analysis()                                   │
│  • Filter to issues only (exclude "ok")                          │
│  • Sample top 20 issues for context                              │
│  • Generate prompt with CSV data                                 │
│  • Call Groq API (Llama 3.3 70B, temp=0.2)                       │
│  • Parse markdown response                                       │
│                                                                   │
│  Output: AI-generated executive summary (string)                 │
└──────────┬───────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  PHASE 4: REPORT GENERATION                                      │
├──────────────────────────────────────────────────────────────────┤
│  Function: write_html_summary()                                  │
│  • Build KPI cards (source pages, broken, 4xx, 5xx)             │
│  • Format executive summary (bullets + AI)                       │
│  • Generate issue tables (top 50 each category)                  │
│  • Apply Minimalist Monochrome design system                     │
│  • Embed images as base64 (self-contained)                       │
│                                                                   │
│  Output: broken_link_summary_final.html                          │
└──────────┬───────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  PHASE 5: DISTRIBUTION                                           │
├──────────────────────────────────────────────────────────────────┤
│  Function: upload_to_monday()                                    │
│  • Create Monday.com update with summary                         │
│  • Attach self-contained HTML report                             │
│  • Post to configured item (11404485394)                         │
│                                                                   │
│  GitHub Actions:                                                 │
│  • Upload all CSV + HTML files as artifacts                      │
│  • Retain for 90 days                                            │
└──────────┬───────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────┐
│  OUTPUTS             │
├──────────────────────┤
│ ✓ HTML Report        │
│ ✓ CSV Data Files     │
│ ✓ Monday.com Update  │
│ ✓ GitHub Artifacts   │
│ ✗ Monthly Dashboard  │ ← NOT INTEGRATED
│ ✗ Google Sheets      │ ← NOT INTEGRATED
└──────────────────────┘
```

---

## Technical Details

### Dependencies

**Core Libraries**:
```python
aiohttp          # Async HTTP client
asyncio          # Async runtime
beautifulsoup4   # HTML parsing
pandas           # Data manipulation
requests         # Sync HTTP client
openai           # Groq API client
```

**Utility Modules**:
```python
pdf_report_formatter      # Table formatting
html_report_utils         # MM design system
```

### Performance Characteristics

**Crawl Phase**:
- Speed: ~2 pages/second (with 0.5s delay)
- Duration: ~2-3 minutes for 150 pages/domain
- Total: ~15-20 minutes for 8 domains

**Validation Phase**:
- Concurrency: 15 simultaneous requests
- Speed: ~50-100 links/second
- Duration: ~1-2 minutes for 5,000 links

**Total Runtime**: ~20-25 minutes end-to-end

### Error Handling

**Crawl Errors**:
```python
try:
    response = fetch_page(current_url)
except Exception as e:
    print(f"Failed crawl {current_url}: {e}")
    visited_pages.add(current_url)  # Mark as visited to avoid retry
    continue
```

**Validation Errors**:
```python
try:
    resp = await session.head(url)
except Exception as exc:
    return {
        "status_code": None,
        "error": str(exc),
        "issue_type": "error"
    }
```

**AI Analysis Fallback**:
```python
try:
    response = client.chat.completions.create(...)
    return response.choices[0].message.content
except Exception as e:
    return f"AI analysis failed: {str(e)}"
```

### Rate Limiting

**Crawl Phase**:
- Fixed delay: 0.5 seconds between requests
- Per-domain limit: 150 pages max
- User-Agent: "CIM-SEO-LinkChecker/1.0"

**Validation Phase**:
- Semaphore: Max 15 concurrent requests
- TCP connector: Max 20 connections
- Timeout: 30 seconds per request

### Memory Management

**Crawl Phase**:
- Queue: Deque (efficient for BFS)
- Visited set: O(n) memory for n pages
- Links list: Grows with discoveries

**Validation Phase**:
- Async tasks: All created upfront
- Results: Collected in memory
- Peak memory: ~100-200 MB for typical run

---

## Recommendations

### 1. Monthly Dashboard Integration

**Priority**: High

**Implementation**:
```python
# In monthly_master_report.py

def collect_broken_link_data():
    """Load latest broken link results."""
    try:
        df = pd.read_csv("broken_link_results.csv")
        return {
            "broken_count": (df["issue_type"] == "broken").sum(),
            "redirect_count": (df["issue_type"] == "redirect").sum(),
            "error_count": (df["issue_type"] == "error").sum(),
            "total_links": len(df)
        }
    except FileNotFoundError:
        return None

# Add to Phase 1: Data Collection
data["broken_links"] = collect_broken_link_data()

# Add to Phase 2: KPI Aggregation
kpis["broken_links"] = {
    "curr": data["broken_links"]["broken_count"],
    "prev": 0  # Load from historical data
}

# Add to Phase 3: Chart Generation
chart_paths["technical_issues"] = build_technical_issues_chart(data)
```

### 2. Historical Tracking

**Priority**: Medium

**Implementation**:
```python
# In broken_link_check.py

def log_to_google_sheets(results_df):
    """Append summary to Google Sheets."""
    summary = {
        "date": date.today().isoformat(),
        "source_pages": results_df["source_url"].nunique(),
        "total_links": len(results_df),
        "broken_count": (results_df["issue_type"] == "broken").sum(),
        "redirect_count": (results_df["issue_type"] == "redirect").sum(),
        "error_count": (results_df["issue_type"] == "error").sum()
    }
    
    df = pd.DataFrame([summary])
    append_to_sheet(df, "broken_link_history")
```

### 3. Alerting Thresholds

**Priority**: Low

**Implementation**:
```python
# In broken_link_check.py

ALERT_THRESHOLDS = {
    "broken_count": 50,      # Alert if >50 broken links
    "error_rate": 0.05,      # Alert if >5% error rate
    "redirect_rate": 0.20    # Alert if >20% redirect rate
}

def check_thresholds(results_df):
    """Check if any thresholds exceeded."""
    broken = (results_df["issue_type"] == "broken").sum()
    total = len(results_df)
    error_rate = (results_df["issue_type"] == "error").sum() / total
    
    alerts = []
    if broken > ALERT_THRESHOLDS["broken_count"]:
        alerts.append(f"⚠️ {broken} broken links (threshold: {ALERT_THRESHOLDS['broken_count']})")
    
    return alerts
```

### 4. Incremental Crawling

**Priority**: Low

**Implementation**:
- Store crawl state between runs
- Only re-check changed pages
- Reduce runtime from 20 min to ~5 min

---

## Conclusion

The Broken Link Check pipeline is a **mature, standalone system** with:

✅ **Strengths**:
- Robust async validation
- AI-powered analysis
- Self-contained HTML reports
- Monday.com integration
- Comprehensive CSV exports

❌ **Gaps**:
- No monthly dashboard integration
- No historical tracking
- No alerting system
- No incremental crawling

**Next Steps**:
1. Integrate with monthly dashboard (Technical Health section)
2. Add Google Sheets logging for trend analysis
3. Implement alerting for critical thresholds
4. Consider incremental crawling for efficiency

---

*End of Analysis*
