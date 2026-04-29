# Contributing to CIM SEO Platform

Thank you for contributing to the CIM SEO Automation Platform! This document provides guidelines for development and contributions.

## 🌿 Branch Strategy

### Main Branches
- **`main`**: Production-ready code. All code here should be tested and stable.
- **`archive/old-versions`**: Historical reference branch for legacy code.

### Feature Branches
When working on new features or fixes, create a branch following this naming convention:

```bash
# Feature branches
git checkout -b feature/description-of-feature

# Bug fix branches
git checkout -b fix/description-of-bug

# Enhancement branches
git checkout -b enhancement/description-of-enhancement

# Documentation branches
git checkout -b docs/description-of-docs
```

### Branch Workflow

1. **Create a feature branch from main**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes and commit regularly**
   ```bash
   git add .
   git commit -m "feat: add new feature description"
   ```

3. **Keep your branch up to date**
   ```bash
   git checkout main
   git pull origin main
   git checkout feature/your-feature-name
   git merge main
   ```

4. **Push your branch and create a pull request**
   ```bash
   git push origin feature/your-feature-name
   ```

## 📝 Commit Message Convention

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types
- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation changes
- **style**: Code style changes (formatting, missing semicolons, etc.)
- **refactor**: Code refactoring
- **perf**: Performance improvements
- **test**: Adding or updating tests
- **chore**: Maintenance tasks

### Examples
```bash
feat(gsc): add support for device-level filtering
fix(speed): resolve timeout issues in PageSpeed API calls
docs(readme): update installation instructions
refactor(utils): simplify date window calculation
perf(crawler): optimize async request batching
```

## 🧪 Testing Guidelines

### Before Committing
1. **Test your changes locally**
   ```bash
   python your_modified_script.py
   ```

2. **Check for syntax errors**
   ```bash
   python -m py_compile your_modified_script.py
   ```

3. **Verify environment variables are documented**
   - Update `.env.example` if you add new variables
   - Update README.md configuration section

### Testing Checklist
- [ ] Script runs without errors
- [ ] Output files are generated correctly
- [ ] PDF reports render properly
- [ ] CSV files have expected columns
- [ ] Error handling works for API failures
- [ ] No sensitive data in output files

## 📋 Code Style Guidelines

### Python Style
Follow [PEP 8](https://pep8.org/) conventions:

```python
# Good
def fetch_page_data(service, start_date, end_date, row_limit=1000):
    """Fetch page-level data from Google Search Console.
    
    Args:
        service: Authenticated GSC service object
        start_date: Start date for data range
        end_date: End date for data range
        row_limit: Maximum rows to fetch (default: 1000)
        
    Returns:
        DataFrame with page-level metrics
    """
    request = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["page"],
        "rowLimit": row_limit,
    }
    # ... implementation
```

### Naming Conventions
- **Functions**: `snake_case` - `fetch_page_data()`, `build_executive_summary()`
- **Variables**: `snake_case` - `current_df`, `top_queries`
- **Constants**: `UPPER_SNAKE_CASE` - `API_KEY`, `MAX_RETRIES`
- **Classes**: `PascalCase` - `ReportGenerator`, `DataProcessor`

### Documentation
- Add docstrings to all functions
- Include type hints where appropriate
- Comment complex logic
- Update README.md for new features

## 🔧 Adding New Reports

When creating a new report script:

1. **Use the standard template structure**
   ```python
   # Imports
   from datetime import date
   import pandas as pd
   from seo_utils import get_weekly_date_windows
   from pdf_report_formatter import get_pdf_css, html_table_from_df
   from monday_utils import upload_pdf_to_monday
   
   # Constants
   REPORT_NAME = "your_report"
   
   # Functions
   def fetch_data():
       """Fetch data from API."""
       pass
   
   def analyze_data(df):
       """Analyze and transform data."""
       pass
   
   def generate_report(df):
       """Generate HTML/PDF report."""
       pass
   
   def main():
       """Main execution flow."""
       data = fetch_data()
       analyzed = analyze_data(data)
       generate_report(analyzed)
   
   if __name__ == "__main__":
       main()
   ```

2. **Follow the output conventions**
   - CSV: `{report_name}_data.csv`
   - HTML: `{report_name}_summary.html`
   - PDF: `{report_name}_summary.pdf`
   - Markdown: `{report_name}_summary.md`

3. **Add configuration support**
   - Create a config CSV if needed
   - Document in README.md
   - Add example to `.env.example`

4. **Integrate with master orchestrator**
   - Add to appropriate execution group (API-based or crawl-based)
   - Set up environment variables
   - Test in isolation first

## 🐛 Debugging Tips

### Common Issues

**API Authentication Errors**
```bash
# Verify service account key exists
ls -la gsc-key.json

# Check environment variables
echo $GSC_PROPERTY
echo $GA4_PROPERTY_ID
```

**Import Errors**
```bash
# Ensure all dependencies are installed
pip install -r requirements.txt

# For Playwright
playwright install chromium
```

**Rate Limiting**
- Add delays between requests: `time.sleep(0.5)`
- Use async with semaphores: `asyncio.Semaphore(10)`
- Implement exponential backoff

### Logging
Add logging to debug issues:
```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"Processing {len(df)} rows")
logger.warning(f"API returned empty response")
logger.error(f"Failed to fetch data: {error}")
```

## 🔒 Security Best Practices

### Never Commit Secrets
- Add to `.gitignore`: `gsc-key.json`, `.env`, `*.pem`
- Use environment variables for all credentials
- Review changes before committing: `git diff`

### API Key Management
- Rotate keys regularly
- Use separate keys for dev/prod
- Limit API key permissions to minimum required

### Data Privacy
- Don't log sensitive user data
- Sanitize URLs in reports
- Review output files before sharing

## 📦 Release Process

### Version Numbering
Follow [Semantic Versioning](https://semver.org/):
- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes

### Creating a Release

1. **Update version references**
   - Update README.md "Last Updated" date
   - Update any version constants

2. **Create a release branch**
   ```bash
   git checkout -b release/v1.2.0
   ```

3. **Test thoroughly**
   - Run all reports
   - Verify outputs
   - Check integrations

4. **Merge to main**
   ```bash
   git checkout main
   git merge release/v1.2.0
   git tag -a v1.2.0 -m "Release version 1.2.0"
   git push origin main --tags
   ```

## 🤝 Pull Request Process

1. **Ensure your PR**
   - Has a clear title and description
   - References any related issues
   - Includes test results
   - Updates documentation if needed

2. **PR Template**
   ```markdown
   ## Description
   Brief description of changes
   
   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Documentation update
   - [ ] Performance improvement
   
   ## Testing
   - [ ] Tested locally
   - [ ] All reports generate successfully
   - [ ] No errors in logs
   
   ## Checklist
   - [ ] Code follows style guidelines
   - [ ] Documentation updated
   - [ ] No sensitive data exposed
   ```

3. **Review Process**
   - Address reviewer feedback
   - Keep PR focused and small
   - Squash commits if needed

## 📞 Getting Help

- Check existing documentation in README.md
- Review similar scripts for patterns
- Ask the team in project channels
- Create an issue for bugs or feature requests

---

Thank you for contributing to the CIM SEO Platform! 🚀
