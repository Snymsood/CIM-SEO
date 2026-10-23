import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from weekly_ai_analysis import _validated, analyze
from weekly_personal_action_report import render_html, render_text


def _csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class WeeklyAIAnalysisTests(unittest.TestCase):
    def test_profiles_every_row_and_keeps_metric_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "normalized").mkdir()
            period = "2026-10-12_2026-10-18"
            (root / "source_report_runs.json").write_text(json.dumps([
                {"artifact": "gsc-weekly-report", "period_id": period},
                {"artifact": "ga4-weekly-report", "period_id": period},
            ]))
            _csv(root / "normalized" / "broken_link_results_normalized.csv", [
                {"source_url": "https://www.cim.org/a", "status_code": "200", "target_url": "/b"},
                {"source_url": "https://www.cim.org/c", "status_code": "404", "target_url": "/d"},
                {"source_url": "https://www.cim.org/e", "status_code": "404", "target_url": "/d"},
            ])
            _csv(root / "normalized" / "ga4_pages_comparison_normalized.csv", [
                {"landingPage": "/a", "sessions_current": "12"},
                {"landingPage": "/b", "sessions_current": "8"},
            ])
            _csv(root / "normalized" / "content_strategy_scorecard_normalized.csv", [
                {"page_canonical": "https://www.cim.org/a", "email_unique_clicks": "20"},
                {"page_canonical": "https://www.cim.org/b", "email_unique_clicks": "40"},
            ])
            _csv(root / "weekly_gsc_report.csv", [
                {"query": "mining", "clicks": "3"},
            ])
            _csv(root / "tracked_keywords.csv", [
                {"keyword": "static configuration"},
            ])
            _csv(root / "normalized" / "tracked_pages_normalized.csv", [
                {"page": "https://www.cim.org/static-configuration"},
            ])
            with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
                result = analyze(root, dry_run=True)
            evidence = json.loads((root / "weekly_ai_evidence.json").read_text())
            self.assertEqual(result["coverage"]["rows"], 8)
            self.assertEqual(result["coverage"]["files"], 4)
            self.assertEqual(evidence["unclassified_files"], [])
            self.assertEqual(evidence["categories"]["search"]["files"][0]["id"],
                             "file:source/weekly_gsc_report.csv")
            technical = evidence["categories"]["technical"]["files"][0]
            self.assertEqual(technical["breakdown"]["status_code"], [["404", 2], ["200", 1]])
            self.assertEqual(technical["examples"], [])
            behavior = evidence["categories"]["behavior"]["files"][0]
            self.assertEqual(behavior["metrics"]["sessions_current"]["row_sum"], 20)
            content = evidence["categories"]["content"]["files"][0]
            self.assertEqual(content["metrics"]["email_unique_clicks"]["mean"], 30)

    def test_fabricated_citation_is_dropped_and_email_labels_partial_coverage(self):
        result = _validated({"summary": "A pattern", "findings": [
            {"title": "False", "insight": "Made up", "evidence_ids": ["row:missing:2"],
             "next_step": "Do something", "confidence": "high"},
            {"title": "Supported", "insight": "Observed", "evidence_ids": ["file:ga4.csv"],
             "next_step": "Check GA4", "confidence": "medium"},
        ], "data_gaps": []}, {"file:ga4.csv"}, 4)
        self.assertEqual([item["title"] for item in result["findings"]], ["Supported"])
        report = {"period_start": "2026-10-12", "period_end": "2026-10-18",
                  "source_runs": [], "actions": [], "site_watchlist": [],
                  "ai_analysis": {"status": "partial", "model": "openai/gpt-oss-120b",
                                  "summary": result["summary"], "patterns": result["findings"],
                                  "data_gaps": ["One domain review failed"],
                                  "coverage": {"successful_categories": 5, "total_categories": 6,
                                               "files": 60, "rows": 100000}}}
        self.assertIn("CROSS-REPORT AI READOUT · PARTIAL", render_html(report))
        self.assertIn("Check GA4", render_text(report))
        self.assertNotIn("Made up", render_text(report))

    def test_separate_reviews_feed_synthesis_without_raw_row_dump(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "normalized").mkdir()
            period = "2026-10-12_2026-10-18"
            (root / "source_report_runs.json").write_text(json.dumps([
                {"artifact": "gsc-weekly-report", "period_id": period},
                {"artifact": "ga4-weekly-report", "period_id": period},
            ]))
            _csv(root / "normalized" / "tracked_keywords_comparison_normalized.csv", [
                {"keyword": "mining conference", "clicks_current": "10"},
            ])
            _csv(root / "normalized" / "ga4_pages_comparison_normalized.csv", [
                {"landingPage": "/conference", "sessions_current": "12"},
            ])
            stages = []

            def fake_model(prompt, name, **_kwargs):
                stages.append((name, prompt))
                reference = ("file:tracked_keywords_comparison_normalized.csv" if name == "search"
                             else "file:ga4_pages_comparison_normalized.csv")
                if name == "cross_source":
                    self.assertIn("completed_reviews", prompt)
                    self.assertIn("Search demand and SERP visibility", prompt)
                if name == "verification":
                    self.assertIn("cited_records", prompt)
                return {"summary": "Review the conference path", "findings": [
                    {"title": "Check the event page", "insight": "Evidence needs comparison",
                     "evidence_ids": [reference], "next_step": "Inspect the page and query",
                     "confidence": "medium"}], "data_gaps": []}

            with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
                result = analyze(root, model_call=fake_model)
            self.assertEqual([name for name, _ in stages],
                             ["search", "behavior", "cross_source", "verification"])
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["coverage"]["successful_categories"], 2)
            self.assertEqual(result["verification"]["accepted"], 1)
            self.assertEqual(result["patterns"][0]["evidence_ids"],
                             ["file:ga4_pages_comparison_normalized.csv"])


if __name__ == "__main__":
    unittest.main()
