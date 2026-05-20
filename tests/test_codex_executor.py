from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _init_repo(root: Path) -> None:
    (root / "growth_dev").mkdir()
    (root / "growth_dev" / "fake_target.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Test Rules\n\nKeep changes narrow.\n", encoding="utf-8")
    _run(["git", "init", "-q"], root)
    _run(["git", "add", "."], root)
    _run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "init"], root)


def _write_fake_codex(path: Path) -> Path:
    script = path / "codex"
    script.write_text(
        """#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys


def _value_after(args, *flags):
    for index, value in enumerate(args):
        if value in flags and index + 1 < len(args):
            return args[index + 1]
    return ""


args = sys.argv[1:]
workspace = _value_after(args, "--cd", "-C") or os.getcwd()
if "exec" in args:
    prompt = sys.stdin.read()
    target = "growth_dev/fake_target.py" if "growth_dev/fake_target.py" in prompt else "README.md"
    target_path = os.path.join(workspace, target)
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    with open(target_path, "a", encoding="utf-8") as handle:
        handle.write("\\n# fake codex change\\n")

    output_path = _value_after(args, "--output-last-message", "-o")
    payload = {
        "summary": "fake codex implemented the requested change",
        "files_changed": [target],
        "tests_run": ["python3 -c \\"print('ok')\\""],
        "risk_events": [],
        "blockers": [],
        "next_action": "review",
    }
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    print(json.dumps({"event": "exec.completed", "target": target}))
    sys.exit(0)

if "review" in args:
    print("# Fake Codex Review\\n\\nNo blocking issues found.")
    sys.exit(0)

print("unsupported fake codex invocation", file=sys.stderr)
sys.exit(2)
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


class CodexExecutorTests(unittest.TestCase):
    def test_codex_exec_command_contains_context_controls(self) -> None:
        from growth_dev.team.codex import CodexExecutorConfig, build_codex_exec_command

        command = build_codex_exec_command(
            CodexExecutorConfig(binary="/tmp/codex", model="gpt-5.3-codex", reasoning_effort="high"),
            worktree_dir=Path("/repo/worktree"),
            run_dir=Path("/repo/runs/run-1"),
            output_schema_path=Path("/repo/runs/run-1/codex/codex_response_schema.json"),
            output_last_message_path=Path("/repo/runs/run-1/codex/last_message.json"),
        )

        self.assertEqual(command[0], "/tmp/codex")
        self.assertIn("exec", command)
        self.assertIn("--cd", command)
        self.assertIn("/repo/worktree", command)
        self.assertIn("--add-dir", command)
        self.assertIn("/repo/runs/run-1", command)
        self.assertIn("--json", command)
        self.assertIn("--output-schema", command)
        self.assertIn("-m", command)
        self.assertIn("gpt-5.3-codex", command)
        self.assertIn("reasoning_effort=\"high\"", command)

    def test_prompt_bundle_writes_state_summary_and_schema(self) -> None:
        from growth_dev.team.codex import CodexExecutor, CodexExecutorConfig
        from growth_dev.team.models import DomainSpec
        from growth_dev.team.runtime import default_team_spec
        from growth_dev.team.agents import AgentContext
        from growth_dev.team.models import TeamRunRecord

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "runs" / "run-1"
            run_dir.mkdir(parents=True)
            (run_dir / "prd.md").write_text("# PRD\n\nBuild it.\n", encoding="utf-8")
            (run_dir / "tech_spec.md").write_text("# Technical Spec\n\nUse a worktree.\n", encoding="utf-8")
            (run_dir / "eval.md").write_text("# Eval\n\nRun the tests.\n", encoding="utf-8")
            record = TeamRunRecord(run_id="run-1", domain_id="demo", brief="Implement a tiny change", run_dir=run_dir)
            context = AgentContext(
                run_id="run-1",
                run_dir=run_dir,
                repo_root=root,
                executor="codex",
                brief="Implement a tiny change",
                team=default_team_spec(),
                domain=DomainSpec(domain_id="demo", risk_rules=["manual_login_only"]),
                inputs={"allowed_paths": ["growth_dev/fake_target.py"], "verification_commands": ["python3 -c \"print('ok')\""]},
                record=record,
            )

            bundle = CodexExecutor(CodexExecutorConfig(), repo_root=root, run_dir=run_dir).write_prompt_bundle("coder", context)

            prompt_text = bundle.prompt_path.read_text(encoding="utf-8")
            summary_text = bundle.state_summary_path.read_text(encoding="utf-8")
            schema = json.loads(bundle.output_schema_path.read_text(encoding="utf-8"))

        self.assertIn("Implement a tiny change", prompt_text)
        self.assertIn("growth_dev/fake_target.py", prompt_text)
        self.assertIn("manual_login_only", summary_text)
        self.assertIn("prd.md", summary_text)
        self.assertIn("Build it.", summary_text)
        self.assertEqual(schema["required"], ["summary", "files_changed", "tests_run", "risk_events", "blockers", "next_action"])

    def test_missing_codex_binary_writes_failed_code_record(self) -> None:
        from growth_dev.team.codex import CodexExecutor, CodexExecutorConfig
        from growth_dev.team.models import DomainSpec, TeamRunRecord
        from growth_dev.team.runtime import default_team_spec
        from growth_dev.team.agents import AgentContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "runs" / "run-1"
            run_dir.mkdir(parents=True)
            context = AgentContext(
                run_id="run-1",
                run_dir=run_dir,
                repo_root=root,
                executor="codex",
                brief="Implement a tiny change",
                team=default_team_spec(),
                domain=DomainSpec(domain_id="demo", risk_rules=["manual_login_only"]),
                inputs={"allowed_paths": ["growth_dev/fake_target.py"]},
                record=TeamRunRecord(run_id="run-1", domain_id="demo", brief="Implement a tiny change", run_dir=run_dir),
            )

            result = CodexExecutor(
                CodexExecutorConfig(binary=str(root / "missing-codex")),
                repo_root=root,
                run_dir=run_dir,
            ).run_coder(context)
            code_record = json.loads((run_dir / "code_run_record.json").read_text(encoding="utf-8"))
            prompt_exists = (run_dir / "codex" / "codex_prompt.md").exists()

            self.assertEqual(result.status, "failed")
            self.assertIn("codex_binary_missing", code_record["risk_events"])
            self.assertTrue(prompt_exists)

    def test_team_runtime_codex_executor_records_diff_review_and_verification(self) -> None:
        from growth_dev.team.models import DomainSpec
        from growth_dev.team.runtime import TeamRuntime, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            fake_codex = _write_fake_codex(root)

            runtime = TeamRuntime(
                team=default_team_spec(),
                domain=DomainSpec(domain_id="demo", summary="Demo coding domain", risk_rules=["manual_login_only"]),
                runs_dir=root / "runs",
                repo_root=root,
                executor="codex",
                codex_binary=str(fake_codex),
                codex_model="gpt-5.3-codex",
                codex_reasoning_effort="medium",
            )
            record = runtime.run(
                "Implement a tiny change",
                inputs={
                    "allowed_paths": ["growth_dev/fake_target.py"],
                    "verification_commands": ["python3 -c \"print('ok')\""],
                },
                run_id="run-1",
            )

            run_dir = root / "runs" / "run-1"
            code_record = json.loads((run_dir / "code_run_record.json").read_text(encoding="utf-8"))
            review_report = (run_dir / "review_report.md").read_text(encoding="utf-8")
            test_report = (run_dir / "test_report.md").read_text(encoding="utf-8")
            diff_exists = (run_dir / "codex" / "diff.patch").exists()

            self.assertEqual(record.status, "completed")
            self.assertEqual(code_record["executor"], "codex")
            self.assertIn("growth_dev/fake_target.py", code_record["files_changed"])
            self.assertTrue(diff_exists)
            self.assertIn("Fake Codex Review", review_report)
            self.assertIn("python3 -c", test_report)


if __name__ == "__main__":
    unittest.main()
