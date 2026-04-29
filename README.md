# CIM SEO Automation Platform

> Comprehensive SEO monitoring, auditing, and reporting system for the Chartered Institute of Marketing

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Private-red.svg)]()

## 📋 Overview

An enterprise-grade SEO automation platform that orchestrates multiple monitoring and reporting workflows, providing AI-powered insights for stakeholder decision-making. The system integrates with Google Analytics 4, Google Search Console, PageSpeed Insights, Monday.com, and Google Sheets to deliver comprehensive SEO intelligence.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│           master_orchestrator.py                        │
│  (Runs all pipelines, generates unified dashboard)      │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
   ┌────▼────┐                        ┌────▼────┐
   │ API-Based│                        │ Crawl-  │
   │ Pipelines│                        │ Based   │
   │(Parallel)│                        │(Serial) │
   └────┬────┘                        └────┬────┘
        │                                   │
   ┌────┴────────────────────┐        ┌────┴──────────────┐
   │ • GA4 Report            │        │ • Broken Links    │
   │ • GSC Reports (3)       │        │ • Internal Links  │
   │ • Site Speed            │        │ • Content Audit   │
   │ • AI Snippet Check      │        │ • Category Perf   │
   └─────────────────────────┘        └───────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
   ┌────▼────┐                        ┌────▼────┐
   │ Outputs │                        │ Storage │
   │ • PDFs  │                        │ • Sheets│
   │ • CSVs  │                        │ • Monday│
   │ • HTML  │                        │ • Local │
   └─────────┘                        └─────────┘
```

## 🚀 Features

### Analytics & Performance Tracking
- **GA4 Weekly Reports**: Sessions, users, engagement metrics, landing pages, channel analysis
- **GSC Weekly Reports**: Search queries, landing pages, clicks, impressions, CTR, position tracking
- **Keyword Ranking Reports**: Tracked keyword performance over time
- **Landing Page Reports**: Page-level search performance analysis

### Technical SEO Audits
- **Site Speed Monitoring**: Core Web Vitals (LCP, INP, CLS), mobile vs desktop comparison
- **Broken Link Detection**: Async crawler identifying 404s, redirects, and server errors
- **Internal Linking Audit**: Link structure analysis, orphan page detection, anchor text optimization
- **Content Audit**: Performance-based refresh/archive recommendations

### AI & Innovation
- **AI Snippet Verification**: Evaluates pages for AI search readiness and hallucination risk
- **AI-Powered Insights**: Executive summaries generated using Groq's Llama models
- **Content Strategy Analysis**: Performance mapping by content pillar

### Reporting & Integration
- **Multi-Format Output**: PDF, HTML, CSV, Markdown reports
- **Monday.com Integration**: Automated project management updates
- **Google Sheets Database**: Historical data persistence and trend analysis
- **Interactive Dashboards**: HTML dashboards with charts and KPIs

## 📦 Installation

### Prerequisites
- Python 3.8 or higher
- Google Cloud Service Account with API access
- Monday.com API token (optional)
- Groq API key (optional, for AI features)

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/Snymsood/CIM-SEO.git
   cd CIM-SEO
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright browsers** (for AI snippet verification)
   ```bash
   playwright install chromium
   ```

5. **Configure credentials**
   - Place your Google Service Account key as `gsc-key.json`
   - Create a `.env` file (see Configuration section)

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# Google APIs
GSC_PROPERTY=https://www.example.com/
GA4_PROPERTY_ID=123456789

# Monday.com Integration
MONDAY_API_TOKEN=your_monday_token
MONDAY_MASTER_ITEM_ID=your_master_item_id
MONDAY_GSC_ITEM_ID=your_gsc_item_id
MONDAY_GSC_KEYWORD_ITEM_ID=your_keyword_item_id
MONDAY_GSC_LANDING_ITEM_ID=your_landing_item_id
MONDAY_BROKEN_LINK_ITEM_ID=your_broken_link_item_id
MONDAY_INTERNAL_LINK_ITEM_ID=your_internal_link_item_id
MONDAY_CONTENT_AUDIT_ITEM_ID=your_content_audit_item_id
MONDAY_AI_SNIPPET_ITEM_ID=your_ai_snippet_item_id

# AI/LLM Integration
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.3-70b-versatile

# PageSpeed Insights
PAGESPEED_API_KEY=your_pagespeed_api_key

# Google Sheets
GOOGLE_SHEET_ID=your_sheet_id
```

### Configuration Files

Update these CSV files with your targets:

- `tracked_keywords.csv`: Keywords to monitor
- `tracked_pages.csv`: Landing pages to track
- `tracked_speed_pages.csv`: URLs for PageSpeed monitoring
- `broken_link_seed_domains.csv`: Starting points for link crawler
- `internal_linking_config.csv`: Rules for internal link audit
- `content_audit_config.csv`: Thresholds for content scoring
- `ai_snippet_targets.csv`: Pages to verify for AI readiness

## 🎯 Usage

### Run All Reports (Master Orchestrator)
```bash
python master_orchestrator.py
```

### Run Individual Reports

**Analytics Reports:**
```bash
python ga4_weekly_report.py
python gsc_weekly_report.py
python gsc_keyword_ranking_report.py
python gsc_landing_pages_report.py
```

**Technical Audits:**
```bash
python site_speed_monitoring.py
python broken_link_check.py
python internal_linking_audit.py
python content_audit_schedule_report.py
```

**AI & Content Strategy:**
```bash
python ai_snippet_verification.py
python content_category_performance.py
```

## 📊 Output Files

Each report generates multiple output formats:

- **PDF Reports**: `*_summary.pdf` - Formatted stakeholder reports
- **HTML Reports**: `*_summary.html` - Interactive web reports
- **CSV Data**: `*.csv` - Raw data for further analysis
- **Markdown**: `*_summary.md` - Text-based summaries
- **Charts**: `charts/*.png` - Visualization assets
- **Screenshots**: `screenshots/*.png` - Page captures (AI verification)

## 🔧 Module Reference

### Core Modules

| Module | Purpose |
|--------|---------|
| `master_orchestrator.py` | Central controller, runs all pipelines |
| `seo_utils.py` | Date windows, URL utilities, calculations |
| `monday_utils.py` | Monday.com API integration |
| `google_sheets_db.py` | Historical data persistence |
| `pdf_report_formatter.py` | Consistent PDF styling |

### Report Scripts

| Script | Description |
|--------|-------------|
| `ga4_weekly_report.py` | Google Analytics 4 performance report |
| `gsc_weekly_report.py` | Search Console weekly summary |
| `gsc_keyword_ranking_report.py` | Keyword position tracking |
| `gsc_landing_pages_report.py` | Landing page performance |
| `site_speed_monitoring.py` | Core Web Vitals tracking |
| `broken_link_check.py` | Link integrity audit |
| `internal_linking_audit.py` | Internal link structure analysis |
| `content_audit_schedule_report.py` | Content refresh recommendations |
| `content_category_performance.py` | Content pillar analysis |
| `ai_snippet_verification.py` | AI readiness assessment |

## 🌿 Branch Management

- **`main`**: Production-ready code
- **`archive/old-versions`**: Historical reference branch

## 🛠️ Technology Stack

- **Language**: Python 3.8+
- **APIs**: Google Analytics Data API, Google Search Console API, PageSpeed Insights API, Monday.com GraphQL API
- **Web Scraping**: BeautifulSoup, Playwright, aiohttp, requests
- **Data Processing**: pandas, numpy
- **Visualization**: matplotlib, seaborn
- **PDF Generation**: WeasyPrint, ReportLab
- **AI/LLM**: OpenAI SDK (Groq endpoint), Llama 3.1/3.3
- **Authentication**: Google Service Account (OAuth2)
- **Storage**: Google Sheets (gspread), Local CSV

## 📝 Development Guidelines

### Code Style
- Follow PEP 8 conventions
- Use type hints where appropriate
- Document functions with docstrings
- Keep functions focused and modular

### Error Handling
- Implement graceful degradation
- Log errors with context
- Provide fallback mechanisms for API failures

### Performance
- Use async/await for I/O operations
- Implement rate limiting for API calls
- Add configurable delays for web crawling

## 🔒 Security Notes

- Never commit `gsc-key.json` or `.env` files
- Use environment variables for all secrets
- Rotate API keys regularly
- Review `.gitignore` before committing

## 📄 License

Private - Proprietary software for CIM internal use only.

## 👥 Contributors

Maintained by the CIM Digital Team

## 📞 Support

For issues or questions, contact the SEO team or create an issue in the repository.

---

**Last Updated**: April 2026
