"""Tests for site boundaries and nested sitemap collection."""

import unittest

from site_source_portfolio import Site, _normalize_url, collect_sitemaps, read_sites


class SiteSourcePortfolioTests(unittest.TestCase):
    def test_config_keeps_measurement_and_property_ids_distinct(self):
        sites = {site.site_id: site for site in read_sites(__import__("pathlib").Path("site_sources.csv"))}
        self.assertEqual(sites["main"].ga4_property_id, "341629008")
        self.assertEqual(sites["main"].ga4_measurement_id, "G-NP57YVGQ72")
        self.assertEqual(sites["magazine"].ga4_property_id, "376202812")
        self.assertEqual(sites["mrmr2026"].ga4_property_id, "521567844")
        self.assertEqual(sites["cimconnect"].ga4_property_id, "506934026")
        self.assertEqual(sites["magazine"].host, "magazine.cim.org")

    def test_main_apex_alias_and_external_site_boundary(self):
        main = read_sites(__import__("pathlib").Path("site_sources.csv"))[0]
        self.assertEqual(_normalize_url(main, "https://cim.org/membership/#join"),
                         "https://www.cim.org/membership/")
        self.assertEqual(_normalize_url(main, "https://cimconnect.ca/"), "")

    def test_nested_sitemap_deduplicates_and_ignores_external_entries(self):
        site = Site("event", "Event", "https://event.example/", "https://event.example/index.xml",
                    "", "", "", 5)
        documents = {
            "https://event.example/index.xml": b"""<sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
              <sitemap><loc>https://event.example/pages.xml</loc></sitemap>
              <sitemap><loc>https://outside.example/pages.xml</loc></sitemap>
              </sitemapindex>""",
            "https://event.example/pages.xml": b"""<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
              <url><loc>https://event.example/</loc><lastmod>2026-10-19</lastmod></url>
              <url><loc>https://event.example/</loc><lastmod>2026-10-20</lastmod></url>
              <url><loc>https://outside.example/page</loc></url>
              </urlset>""",
        }

        def fetch(url, allowed_hosts):
            self.assertIn("event.example", allowed_hosts)
            return documents[url], url

        urls, sitemap_rows, warnings = collect_sitemaps(site, fetch)
        self.assertEqual(len(sitemap_rows), 2)
        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0]["lastmod"], "2026-10-20")
        self.assertEqual(len(warnings), 2)


if __name__ == "__main__":
    unittest.main()
