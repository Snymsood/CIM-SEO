# Analysis: GSC Weekly Report Script

**Script**: `gsc_weekly_report.py`  
**Purpose**: Generate weekly Google Search Console performance reports with query and page analysis  
**Date Analyzed**: April 29, 2026

---

## 📊 Current State Assessment

### Strengths ✅
1. **Well-structured code** with clear separation of concerns
2. **Comprehensive reporting** covering queries, pages, winners/losers
3. **Multi-format output** (PDF, HTML, Markdown, CSV)
4. **AI-powered insights** using Groq/Llama
5. **Good visualization** with matplotlib charts
6. **Historical tracking** via Google Sheets integration
7. **Error handling** for AI failures

### Issues & Optimization Opportunities 🔧

#### 1. **Code Duplication** (Critical)
- `calculate_kpis()` is called multiple times with same data
- KPI extraction logic repeated in multiple functions
- Chart generation has repetitive patterns
- Table generation duplicates sorting logic

#### 2. **Performance Issues** (Medium)
- Sequential API calls (could be parallelized)
- Multiple DataFrame sorts on same data
- Redundant DataFrame slicing operations
- Charts created even if not needed

#### 3. **Error Handling** (Medium)
- No retry logic for API failures
- Generic exception catching loses error context
- No validation of environment variables at startup
- Missing file existence checks

#### 4. **Configuration Issues** (Low)
- Hardcoded row limits (250)
- Hardcoded branded query patterns
- Chart colors defined as module-level constants
- No configurable thresholds

#### 5. **Code Quality** (Low)
- Long functions (100+ lines)
- Inconsistent parameter passing
- Magic numbers throughout
- Missing type hints
- Incomplete docstrings

#### 6. **Resource Management** (Low)
- No cleanup of old chart files
- Matplotlib figures not always closed properly
- No disk space checks before file operations

---

## 🎯 Optimization Recommendations

### Priority 1: Critical Improvements

#### A. Eliminate Code Duplication
**Problem**: KPI calculation repeated 3+ times
```python
# Current (repeated everywhere)
kpis = calculate_kpis(query_df)
total_clicks_current = kpis["clicks_current"]
total_clicks_previous = kpis["clicks_previous"]
# ... 6 more lines
```

**Solution**: Create a KPI dataclass
```python
from dataclasses import dataclass

@dataclass
class GSCMetrics:
    clicks_current: float
    clicks_previous: float
    impressions_current: float
    impressions_previous: float
    ctr_current: float
    ctr_previous: float
    position_current: float
    position_previous: float
    
    @property
    def clicks_change(self) -> float:
        return self.clicks_current - self.clicks_previous
    
    @property
    def clicks_change_pct(self) -> float:
        return safe_pct_change(self.clicks_current, self.clicks_previous)
```

#### B. Refactor Data Processing Pipeline
**Problem**: Multiple sorts and slices on same DataFrames
```python
# Current (inefficient)
top_queries = query_df.sort_values(by="clicks_current", ascending=False).head(10)
gainers = query_df.sort_values(by="clicks_change", ascending=False).head(10)
losers = query_df.sort_values(by="clicks_change", ascending=True).head(10)
```

**Solution**: Create a data processor class
```python
class GSCDataProcessor:
    def __init__(self, query_df: pd.DataFrame, page_df: pd.DataFrame):
        self.query_df = query_df
        self.page_df = page_df
        self._cache = {}
    
    @property
    def top_queries(self) -> pd.DataFrame:
        if 'top_queries' not in self._cache:
            self._cache['top_queries'] = self.query_df.nlargest(25, 'clicks_current')
        return self._cache['top_queries'].head(10)
    
    @property
    def query_gainers(self) -> pd.DataFrame:
        if 'query_gainers' not in self._cache:
            self._cache['query_gainers'] = self.query_df.nlargest(25, 'clicks_change')
        return self._cache['query_gainers'].head(10)
```

#### C. Add Configuration Management
**Problem**: Hardcoded values scattered throughout
```python
# Current
row_limit=250
branded_mask = top_queries_df["query"].astype(str).str.contains(
    r"cim connect|vancouver 2026|cim 2026|cim vancouver",
    case=False, na=False,
)
```

**Solution**: Configuration class
```python
from dataclasses import dataclass
from typing import List

@dataclass
class GSCReportConfig:
    row_limit: int = 250
    top_n_queries: int = 25
    top_n_pages: int = 25
    chart_dpi: int = 180
    branded_patterns: List[str] = None
    
    def __post_init__(self):
        if self.branded_patterns is None:
            self.branded_patterns = [
                "cim connect",
                "vancouver 2026",
                "cim 2026",
                "cim vancouver"
            ]
    
    @classmethod
    def from_env(cls):
        return cls(
            row_limit=int(os.getenv("GSC_ROW_LIMIT", "250")),
            top_n_queries=int(os.getenv("GSC_TOP_N_QUERIES", "25")),
            # ... etc
        )
```

### Priority 2: Performance Improvements

#### D. Parallelize API Calls
**Problem**: Sequential fetching of query and page data
```python
# Current (sequential)
current_query_df = fetch_dimension_data(service, current_start, current_end, "query")
previous_query_df = fetch_dimension_data(service, previous_start, previous_end, "query")
current_page_df = fetch_dimension_data(service, current_start, current_end, "page")
previous_page_df = fetch_dimension_data(service, previous_start, previous_end, "page")
```

**Solution**: Use ThreadPoolExecutor
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_all_data_parallel(service, current_start, current_end, previous_start, previous_end):
    """Fetch all GSC data in parallel."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fetch_dimension_data, service, current_start, current_end, "query"): "current_query",
            executor.submit(fetch_dimension_data, service, previous_start, previous_end, "query"): "previous_query",
            executor.submit(fetch_dimension_data, service, current_start, current_end, "page"): "current_page",
            executor.submit(fetch_dimension_data, service, previous_start, previous_end, "page"): "previous_page",
        }
        
        results = {}
        for future in as_completed(futures):
            key = futures[future]
            results[key] = future.result()
        
        return results
```

#### E. Optimize Chart Generation
**Problem**: Charts created even if report generation fails
```python
# Current
chart_paths = build_chart_paths(...)  # Always creates charts
write_html_summary(...)  # Might fail
```

**Solution**: Lazy chart generation
```python
class ChartGenerator:
    def __init__(self, query_df, page_df, metrics):
        self.query_df = query_df
        self.page_df = page_df
        self.metrics = metrics
        self._charts = {}
    
    def get_chart(self, chart_name: str) -> Path:
        """Generate chart on-demand."""
        if chart_name not in self._charts:
            self._charts[chart_name] = self._generate_chart(chart_name)
        return self._charts[chart_name]
```

### Priority 3: Code Quality

#### F. Add Comprehensive Error Handling
**Problem**: Generic exception catching
```python
# Current
try:
    upload_pdf_to_monday("weekly_summary.pdf")
except Exception as e:
    print(f"monday upload step failed: {e}")
```

**Solution**: Specific exception handling with logging
```python
import logging
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

def upload_pdf_to_monday_safe(pdf_path: str) -> bool:
    """Upload PDF to Monday.com with proper error handling."""
    try:
        upload_pdf_to_monday(pdf_path)
        logger.info(f"Successfully uploaded {pdf_path} to Monday.com")
        return True
    except requests.exceptions.Timeout:
        logger.error("Monday.com upload timed out")
        return False
    except requests.exceptions.ConnectionError:
        logger.error("Failed to connect to Monday.com API")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error uploading to Monday.com: {e}")
        return False
```

#### G. Add Type Hints and Docstrings
**Problem**: Missing type information
```python
# Current
def fetch_dimension_data(service, start_date, end_date, dimension, row_limit=250):
    request = {
        "startDate": start_date.isoformat(),
        # ...
    }
```

**Solution**: Full type hints
```python
from typing import Optional
from datetime import date
from googleapiclient.discovery import Resource

def fetch_dimension_data(
    service: Resource,
    start_date: date,
    end_date: date,
    dimension: str,
    row_limit: int = 250
) -> pd.DataFrame:
    """Fetch dimension-level data from Google Search Console.
    
    Args:
        service: Authenticated GSC API service object
        start_date: Start date for data range (inclusive)
        end_date: End date for data range (inclusive)
        dimension: GSC dimension to query ('query', 'page', 'device', etc.)
        row_limit: Maximum number of rows to return (default: 250)
    
    Returns:
        DataFrame with columns: [dimension, clicks, impressions, ctr, position]
        Returns empty DataFrame if no data available
    
    Raises:
        HttpError: If API request fails
        ValueError: If dimension is invalid
    """
    if dimension not in ['query', 'page', 'device', 'country', 'date']:
        raise ValueError(f"Invalid dimension: {dimension}")
    
    # ... implementation
```

#### H. Extract Chart Configuration
**Problem**: Chart styling scattered throughout
```python
# Current
fig, ax = plt.subplots(figsize=(10, 5.2))
# ... 
fig.savefig(path, dpi=180, bbox_inches="tight")
```

**Solution**: Chart configuration class
```python
@dataclass
class ChartStyle:
    figsize: tuple = (10, 5.2)
    dpi: int = 180
    title_fontsize: int = 14
    label_fontsize: int = 11
    grid_alpha: float = 0.35
    colors: dict = None
    
    def __post_init__(self):
        if self.colors is None:
            self.colors = {
                'primary': '#0F4C81',
                'secondary': '#2A9D8F',
                'negative': '#E76F51',
                'neutral': '#6C757D',
            }
    
    def apply_to_axes(self, ax):
        """Apply consistent styling to matplotlib axes."""
        ax.grid(axis='y', linestyle='--', alpha=self.grid_alpha)
        ax.tick_params(labelsize=self.label_fontsize)
```

---

## 🏗️ Proposed Refactored Structure

```python
# gsc_weekly_report.py (refactored)

from dataclasses import dataclass
from typing import Dict, Optional, Tuple
import logging

# Configuration
class GSCReportConfig:
    """Configuration for GSC weekly report."""
    pass

# Data Models
@dataclass
class GSCMetrics:
    """Container for GSC performance metrics."""
    pass

# Data Processing
class GSCDataProcessor:
    """Process and analyze GSC data."""
    
    def __init__(self, query_df: pd.DataFrame, page_df: pd.DataFrame):
        pass
    
    def calculate_metrics(self) -> GSCMetrics:
        pass
    
    def get_top_performers(self, n: int = 10) -> Dict[str, pd.DataFrame]:
        pass
    
    def get_winners_losers(self, n: int = 10) -> Dict[str, pd.DataFrame]:
        pass

# API Client
class GSCClient:
    """Google Search Console API client with retry logic."""
    
    def __init__(self, service, config: GSCReportConfig):
        pass
    
    def fetch_data_parallel(self, date_ranges: Dict) -> Dict[str, pd.DataFrame]:
        pass

# Report Generation
class GSCReportGenerator:
    """Generate GSC reports in multiple formats."""
    
    def __init__(self, processor: GSCDataProcessor, config: GSCReportConfig):
        pass
    
    def generate_all(self) -> Dict[str, Path]:
        """Generate all report formats."""
        pass

# Chart Generation
class ChartGenerator:
    """Generate charts for GSC reports."""
    pass

# Main execution
def main():
    # Setup
    config = GSCReportConfig.from_env()
    setup_logging(config.log_level)
    
    # Fetch data
    client = GSCClient(get_service(), config)
    data = client.fetch_data_parallel(get_date_ranges())
    
    # Process
    processor = GSCDataProcessor(data['queries'], data['pages'])
    
    # Generate reports
    generator = GSCReportGenerator(processor, config)
    outputs = generator.generate_all()
    
    # Upload
    upload_reports(outputs)
```

---

## 📈 Expected Performance Improvements

| Optimization | Current | Optimized | Improvement |
|--------------|---------|-----------|-------------|
| API Calls | ~8-12s (sequential) | ~3-4s (parallel) | **60-70% faster** |
| Data Processing | Multiple sorts | Cached results | **40-50% faster** |
| Chart Generation | Always created | On-demand | **Memory efficient** |
| Code Maintainability | 600+ lines | ~400 lines | **33% reduction** |
| Error Recovery | Fails silently | Retry + logging | **More reliable** |

---

## 🔄 Migration Strategy

### Phase 1: Non-Breaking Improvements (Week 1)
1. Add configuration class
2. Add type hints and docstrings
3. Improve error handling and logging
4. Add unit tests for core functions

### Phase 2: Performance Optimizations (Week 2)
1. Implement parallel API calls
2. Add data processor with caching
3. Optimize chart generation
4. Add performance benchmarks

### Phase 3: Structural Refactoring (Week 3)
1. Extract classes (GSCClient, GSCDataProcessor, etc.)
2. Implement lazy chart generation
3. Add comprehensive test coverage
4. Update documentation

---

## 🧪 Testing Recommendations

### Unit Tests Needed
- `test_fetch_dimension_data()` - Mock API responses
- `test_prepare_comparison()` - Various data scenarios
- `test_calculate_kpis()` - Edge cases (empty data, zeros)
- `test_build_executive_read()` - Different metric combinations
- `test_chart_generation()` - Output validation

### Integration Tests Needed
- End-to-end report generation
- API failure scenarios
- File system operations
- Monday.com upload

### Performance Tests Needed
- Benchmark API call parallelization
- Memory usage profiling
- Large dataset handling (1000+ queries)

---

## 📝 Additional Recommendations

### 1. Add Retry Logic for API Calls
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
def fetch_dimension_data_with_retry(...):
    pass
```

### 2. Add Data Validation
```python
def validate_gsc_data(df: pd.DataFrame, dimension: str) -> bool:
    """Validate GSC data structure and content."""
    required_cols = [dimension, 'clicks', 'impressions', 'ctr', 'position']
    if not all(col in df.columns for col in required_cols):
        return False
    
    if df['clicks'].sum() == 0 and df['impressions'].sum() == 0:
        logger.warning("No traffic data in GSC response")
        return False
    
    return True
```

### 3. Add Progress Indicators
```python
from tqdm import tqdm

def main():
    with tqdm(total=6, desc="GSC Report Generation") as pbar:
        pbar.set_description("Fetching data")
        data = fetch_all_data()
        pbar.update(1)
        
        pbar.set_description("Processing queries")
        # ...
        pbar.update(1)
```

### 4. Add Report Metadata
```python
@dataclass
class ReportMetadata:
    generated_at: datetime
    date_range: Tuple[date, date]
    total_queries: int
    total_pages: int
    data_freshness: timedelta
    
    def to_dict(self) -> dict:
        return asdict(self)
```

---

## 🎯 Success Metrics

After optimization, measure:
- ✅ Execution time reduction (target: 50%+)
- ✅ Code coverage (target: 80%+)
- ✅ Lines of code reduction (target: 30%+)
- ✅ Error recovery rate (target: 95%+)
- ✅ Memory usage (target: stable under 500MB)

---

**Next Steps**: Review this analysis and prioritize which optimizations to implement first.
