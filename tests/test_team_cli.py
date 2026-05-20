from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_team_models import DOMAIN_YAML, TEAM_YAML


WEB_MONITORING_DOMAIN_YAML = """\
domain_id: web_monitoring
input_schema:
  target_url: string
  keyword: string
output_schema: WebMonitoringResult
risk_rules:
  - no_private_data_collection
  - screenshot_evidence_only
"""


def _write_domain_pack(root: Path, domain_id: str, domain_yaml: str) -> Path:
    domain_dir = root / domain_id
    domain_dir.mkdir(parents=True)
    (domain_dir / "domain.yaml").write_text(domain_yaml, encoding="utf-8")
    (domain_dir / "team.yaml").write_text(TEAM_YAML, encoding="utf-8")
    return domain_dir


class TeamCliTests(unittest.TestCase):
    def test_team_subcommands_are_registered(self) -> None:
        from growth_dev.cli import _build_parser

        parser = _build_parser()
        examples = [
            ["team", "init", "--domain", "xhs_browser_benchmark"],
            ["team", "run", "--brief", "对比 5 个浏览器自动化框架完成小红书采集任务"],
            ["team", "run", "--brief", "接入 Codex", "--executor", "codex", "--model", "gpt-5.3-codex", "--reasoning-effort", "medium"],
            ["team", "status", "--run-id", "team-run-1"],
            ["team", "report", "--run-id", "team-run-1"],
        ]

        for argv in examples:
            with self.subTest(argv=argv):
                args = parser.parse_args(argv)
                self.assertTrue(callable(args.func))

    def test_team_init_cli_generates_eval_and_team_yaml(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            domains_dir = root / "domains"
            _write_domain_pack(domains_dir, "xhs_browser_benchmark", DOMAIN_YAML)
            output_dir = root / "tasks" / "current"

            exit_code = main(
                [
                    "team",
                    "init",
                    "--domain",
                    "xhs_browser_benchmark",
                    "--domains-dir",
                    str(domains_dir),
                    "--output",
                    str(output_dir),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "eval.md").exists())
            self.assertTrue((output_dir / "team.yaml").exists())
            self.assertTrue((output_dir / "domain.yaml").exists())

    def test_team_run_cli_supports_second_domain_pack(self) -> None:
        from growth_dev.cli import main

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            domains_dir = root / "domains"
            runs_dir = root / "runs"
            _write_domain_pack(domains_dir, "web_monitoring", WEB_MONITORING_DOMAIN_YAML)

            exit_code = main(
                [
                    "team",
                    "run",
                    "--domain",
                    "web_monitoring",
                    "--domains-dir",
                    str(domains_dir),
                    "--runs-dir",
                    str(runs_dir),
                    "--brief",
                    "监控目标网页里关键词是否发生变化",
                ]
            )

            self.assertEqual(exit_code, 0)
            run_dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
            self.assertEqual(len(run_dirs), 1)
            record_path = run_dirs[0] / "team_run_record.json"
            self.assertTrue(record_path.exists())
            payload = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["domain_id"], "web_monitoring")
            self.assertEqual(payload["status"], "completed")
            self.assertTrue((run_dirs[0] / "final_report.md").exists())


if __name__ == "__main__":
    unittest.main()
