from __future__ import annotations

import unittest

from growth_dev.adapters.base import MockAdapter, AdapterContext
from growth_dev.fixtures import build_candidate_cards, sort_cards_by_comments
from growth_dev.models import TaskSpec
from growth_dev.scoring import framework_score, validate_note_payload
from pathlib import Path


class ScoringTests(unittest.TestCase):
    def test_validate_note_payload(self) -> None:
        payload = {
            "note_id": "n1",
            "url": "http://example.test",
            "title": "title",
            "body": "body",
            "author": {"display_name": "a", "profile_url": "p"},
            "counts": {"likes": 1, "collects": 2, "comments": 3, "shares": 4},
            "media": [],
            "comments": [],
            "extraction_meta": {},
        }
        self.assertEqual(validate_note_payload(payload), [])
        del payload["author"]
        self.assertIn("author", validate_note_payload(payload))

    def test_framework_score_uses_mock_results(self) -> None:
        task = TaskSpec.from_dict(
            {
                "task_id": "xhs-framework-benchmark",
                "title": "XHS browser framework benchmark harness",
                "keyword": "露营",
                "top_n": 3,
                "candidate_pool": 12,
                "profile_dir": ".local/browser-profiles/xhs",
                "frameworks": ["mock"],
                "base_url": "http://127.0.0.1:8787",
            }
        )
        adapter = MockAdapter()
        result = adapter.run(AdapterContext(task=task, base_url=task.base_url, profile_dir=task.profile_dir, run_dir=Path("/tmp/growth-dev-test"), framework="mock"))
        expected = [card.note for card in sort_cards_by_comments(build_candidate_cards("露营", candidate_pool=12))[:3]]
        score = framework_score(result, expected)
        self.assertEqual(score.status, "success")
        self.assertGreaterEqual(score.completeness, 0.99)


if __name__ == "__main__":
    unittest.main()
