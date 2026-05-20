from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from growth_dev.adapters.base import AdapterResult, MockAdapter, AdapterContext
from growth_dev.models import RunRecord, TaskSpec
from growth_dev.reporting import radar_svg, write_report
from growth_dev.scoring import framework_score
from growth_dev.fixtures import build_candidate_cards, sort_cards_by_comments


class ReportingTests(unittest.TestCase):
    def test_radar_svg_contains_labels(self) -> None:
        svg = radar_svg(
            {
                "stability": 0.8,
                "completeness": 0.7,
                "risk": 0.9,
                "maintainability": 0.6,
                "score": 0.75,
            }
        )
        self.assertIn("<svg", svg)
        self.assertIn("stability", svg)

    def test_write_report_creates_artifacts(self) -> None:
        task = TaskSpec.from_dict(
            {
                "task_id": "xhs-framework-benchmark",
                "title": "XHS browser framework benchmark harness",
                "keyword": "露营",
                "top_n": 2,
                "candidate_pool": 10,
                "profile_dir": ".local/browser-profiles/xhs",
                "frameworks": ["mock"],
                "base_url": "http://127.0.0.1:8787",
            }
        )
        adapter = MockAdapter()
        result = adapter.run(AdapterContext(task=task, base_url=task.base_url, profile_dir=task.profile_dir, run_dir=Path("/tmp/growth-dev-report"), framework="mock"))
        run_record = RunRecord(run_id="run-1", task=task, adapter_results=[result])
        expected = [card.note for card in sort_cards_by_comments(build_candidate_cards("露营", candidate_pool=10))[:2]]
        score = framework_score(result, expected)
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts = write_report(run_record, [score], Path(temp_dir))
            self.assertTrue(artifacts["report_md"].exists())
            self.assertTrue(artifacts["report_json"].exists())
            self.assertTrue(artifacts["report_svg"].exists())


if __name__ == "__main__":
    unittest.main()
