from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from growth_dev.tasks import write_task_package


class TaskPackageTests(unittest.TestCase):
    def test_write_task_package_includes_standard_agent_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            files = write_task_package(Path(temp_dir))
            expected_files = {
                "task.yaml",
                "context.md",
                "prd.md",
                "tech_spec.md",
                "ui_spec.md",
                "eval.md",
                "coding_prompt.md",
                "team.yaml",
            }
            self.assertTrue(expected_files.issubset(files.keys()))
            for name in expected_files:
                self.assertTrue(files[name].exists(), name)

            payload = json.loads(files["task.yaml"].read_text(encoding="utf-8"))
            self.assertEqual(payload["task_id"], "xhs-framework-benchmark")
            self.assertEqual(payload["frameworks"][0], "playwright-mcp")

            eval_text = files["eval.md"].read_text(encoding="utf-8")
            self.assertIn("Schema", eval_text)
            self.assertIn("risk", eval_text.lower())

            team_text = files["team.yaml"].read_text(encoding="utf-8")
            self.assertIn("team_id:", team_text)
            self.assertIn("orchestrator", team_text)
            self.assertIn("before_coding", team_text)


if __name__ == "__main__":
    unittest.main()
