from __future__ import annotations

import unittest
from pathlib import Path


class GitHubActionsCiTests(unittest.TestCase):
    def test_minimal_ci_workflow_runs_full_unittest_on_pr_and_main_push(self) -> None:
        workflow_path = Path(".github/workflows/ci.yml")

        self.assertTrue(workflow_path.exists(), "Expected .github/workflows/ci.yml to exist.")

        workflow = workflow_path.read_text(encoding="utf-8")
        self.assertIn("pull_request:", workflow)
        self.assertIn("push:", workflow)
        self.assertIn("branches: [main]", workflow)
        self.assertIn("ubuntu-latest", workflow)
        self.assertIn("actions/checkout@", workflow)
        self.assertIn("actions/setup-python@v6", workflow)
        self.assertIn('python-version: "3.14"', workflow)
        self.assertIn("python -m pip install --upgrade pip setuptools wheel", workflow)
        self.assertIn("python -m pip install -e .", workflow)
        self.assertIn("python3 -m unittest discover -s tests -v", workflow)


if __name__ == "__main__":
    unittest.main()
