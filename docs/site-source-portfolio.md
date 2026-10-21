# Site Source Portfolio: first four sites

`site_sources.csv` is the site registry. The weekly `site-source-portfolio.yml`
workflow runs `site_source_portfolio.py`, finalizes the report in its own output
directory, and uploads a single artifact. Each row represents a separate site;
the collector never combines GA4 users or events across properties.

## Initial scope

| Site | Reporting URL | Sitemap | GSC inspection property | GA4 |
|---|---|---|---|---|
| Main | `https://www.cim.org/` | `https://www.cim.org/sitemap.xml` | `https://www.cim.org/` | Numeric property `341629008` |
| Magazine | `https://magazine.cim.org/en/` | `https://magazine.cim.org/sitemap.xml` | `sc-domain:cim.org`, with magazine URLs only | Numeric property `376202812` |
| MRMR 2026 | `https://mrmr2026.cim.org/` | `https://mrmr2026.cim.org/sitemap_index.xml` | `sc-domain:cim.org`, with MRMR 2026 URLs only | Numeric property `521567844` |
| CIM CONNECT | `https://cimconnect.ca/` | `https://cimconnect.ca/sitemap_index.xml` | `sc-domain:cimconnect.ca` | Numeric property `506934026` |

The supplied `G-...` values are GA4 **web-stream measurement IDs**. They are
recorded in the registry for identification. The GA4 Data API requires numeric
**property IDs** and the existing service account must have Viewer access to
each property. These IDs are the corrected GA4 Property IDs supplied for all
four sites. Event names are
exported as observed; site-specific conversion definitions will be configured
separately after they are supplied.

The main sitemap publishes apex `cim.org` URLs, which currently redirect to
`www.cim.org`. The collector records the original URL and maps the report URL
to the agreed `www` standard. This mapping applies only to the main site.
The provided `sitemap.txt` contains 456 distinct main-domain URLs and no
mini-site hosts. It is a useful comparison list, not a current source of truth.

## Sources and access

- **Sitemaps:** Public HTTPS XML. Handles URL sets and nested sitemap indexes;
  rejects off-site URLs. No credential or paid API.
- **GSC URL Inspection:** Uses the existing `GSC_SERVICE_ACCOUNT_KEY` and
  read-only access. The main URL-prefix property is used for `www`; the
  existing domain property is used only for selected URLs on the two CIM
  subdomains. CIM CONNECT uses its own domain property, shared with the
  existing service account. Up to five URLs per site are checked weekly.
- **CrUX history:** Uses `PAGESPEED_API_KEY` if the Chrome UX Report API is
  enabled for that key's project. It requests phone, origin-level history.
  Missing field data and API access appear in `site_source_status.csv`.
- **GA4:** Uses the existing service account and a configured numeric property
  ID. Every query filters to the site's `hostName`. Only observed event names
  and counts are exported; the collector does not infer business outcomes.

Unavailable sources are recorded as `not_configured` or a failure state, never
as zero traffic or zero indexed pages. Empty optional source files are omitted;
the status table is the coverage record. Raw source data is kept in CSVs, and
`site_source_portfolio.html` gives a separate status row for each site.

The collector does not depend on an Umbraco API, so a CMS migration does not
change its configuration unless URLs, sitemaps, or analytics properties move.
After migration, a CMS metadata export can be added as another adapter.

## Run locally

```bash
python3 site_source_portfolio.py --sources sitemap --output-dir /tmp/cim-site-portfolio
```

With repository dependencies, `gsc-key.json`, and `PAGESPEED_API_KEY` present,
omit `--sources` to run all configured sources. Keep credentials in GitHub
Secrets; do not commit the key file.
