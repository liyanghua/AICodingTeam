from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import time
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


def _write_provider_asserting_fake_codex(path: Path, expected_key: str) -> Path:
    script = path / "codex-provider"
    script.write_text(
        f"""#!/usr/bin/env python3
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
required_fragments = [
    'model_provider="aicodemirror"',
    'model_providers.aicodemirror.env_key="AICODEMIRROR_KEY"',
    'model_providers.aicodemirror.wire_api="responses"',
    'model_providers.aicodemirror.requires_openai_auth=false',
]
missing = [fragment for fragment in required_fragments if fragment not in args]
if missing:
    print("missing provider config: " + ",".join(missing), file=sys.stderr)
    sys.exit(4)
if os.environ.get("AICODEMIRROR_KEY") != {expected_key!r}:
    print("missing provider key env", file=sys.stderr)
    sys.exit(5)

workspace = _value_after(args, "--cd", "-C") or os.getcwd()
if "exec" in args:
    target = os.path.join(workspace, "growth_dev", "fake_target.py")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\\n# fake provider codex change\\n")
    output_path = _value_after(args, "--output-last-message", "-o")
    payload = {{
        "summary": "fake provider codex implemented the requested change",
        "files_changed": ["growth_dev/fake_target.py"],
        "tests_run": ["python3 -c \\"print('ok')\\""],
        "risk_events": [],
        "blockers": [],
        "next_action": "review",
    }}
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    print(json.dumps({{"event": "exec.completed", "provider_env_present": True}}))
    sys.exit(0)

if "review" in args:
    print("# Fake Provider Codex Review\\n\\nNo blocking issues found.")
    sys.exit(0)

print("unsupported fake codex invocation", file=sys.stderr)
sys.exit(2)
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_slow_fake_codex(path: Path) -> Path:
    script = path / "codex-slow"
    script.write_text(
        """#!/usr/bin/env python3
from __future__ import annotations

import sys
import time

sys.stdin.read()
print("stdout-before-sleep", flush=True)
print("stderr-before-sleep", file=sys.stderr, flush=True)
time.sleep(2.0)
print("stdout-after-sleep", flush=True)
sys.exit(0)
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


class CodexExecutorTests(unittest.TestCase):
    def test_codex_failure_category_distinguishes_provider_cli_review_and_test_errors(self) -> None:
        from growth_dev.team.codex import classify_codex_failure

        self.assertEqual(classify_codex_failure("401 Unauthorized: invalid api key", 1, "coder"), "provider_error")
        self.assertEqual(classify_codex_failure("error: unrecognized option '--bad-flag'", 2, "coder"), "codex_cli_args")
        self.assertEqual(classify_codex_failure("review model failed", 1, "reviewer"), "review_failed")
        self.assertEqual(classify_codex_failure("FAILED tests/test_demo.py", 1, "verifier"), "test_failed")
        self.assertEqual(classify_codex_failure("", 0, "coder"), "")

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

    def test_codex_exec_command_uses_absolute_paths(self) -> None:
        from growth_dev.team.codex import CodexExecutorConfig, build_codex_exec_command

        command = build_codex_exec_command(
            CodexExecutorConfig(binary="/tmp/codex"),
            worktree_dir=Path("runs/demo-codex/worktree"),
            run_dir=Path("runs/demo-codex"),
            output_schema_path=Path("runs/demo-codex/codex/codex_response_schema.json"),
            output_last_message_path=Path("runs/demo-codex/codex/last_message.json"),
        )

        self.assertTrue(Path(command[command.index("--cd") + 1]).is_absolute())
        self.assertTrue(Path(command[command.index("--add-dir") + 1]).is_absolute())
        self.assertTrue(Path(command[command.index("--output-last-message") + 1]).is_absolute())
        self.assertTrue(Path(command[command.index("--output-schema") + 1]).is_absolute())

    def test_load_aicodemirror_provider_from_env_file(self) -> None:
        from growth_dev.team.codex import load_aicodemirror_provider_from_env

        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "aicodemirror_base_url=https://provider.example/api/codex\n"
                "aicodemirror_key=sk-ant-test-secret\n",
                encoding="utf-8",
            )

            provider = load_aicodemirror_provider_from_env(env_path)

        self.assertEqual(provider.name, "aicodemirror")
        self.assertEqual(provider.base_url, "https://provider.example/api/codex")
        self.assertEqual(provider.env_key, "AICODEMIRROR_KEY")
        self.assertEqual(provider.secret_value, "sk-ant-test-secret")
        self.assertEqual(provider.wire_api, "responses")
        self.assertFalse(provider.requires_openai_auth)

    def test_aicodemirror_provider_command_redacts_secret(self) -> None:
        from growth_dev.team.codex import CodexExecutorConfig, CodexProviderConfig, build_codex_exec_command

        config = CodexExecutorConfig(
            binary="/tmp/codex",
            provider=CodexProviderConfig(
                name="aicodemirror",
                base_url="https://provider.example/api/codex",
                env_key="AICODEMIRROR_KEY",
                secret_value="sk-ant-test-secret",
                wire_api="responses",
                requires_openai_auth=False,
            ),
        )

        command = build_codex_exec_command(
            config,
            worktree_dir=Path("/repo/worktree"),
            run_dir=Path("/repo/runs/run-1"),
            output_schema_path=Path("/repo/runs/run-1/codex/codex_response_schema.json"),
            output_last_message_path=Path("/repo/runs/run-1/codex/last_message.json"),
        )
        command_text = "\n".join(command)

        self.assertIn('model_provider="aicodemirror"', command)
        self.assertIn('model_providers.aicodemirror.base_url="https://provider.example/api/codex"', command)
        self.assertIn('model_providers.aicodemirror.env_key="AICODEMIRROR_KEY"', command)
        self.assertIn('model_providers.aicodemirror.requires_openai_auth=false', command)
        self.assertNotIn("sk-ant-test-secret", command_text)

    def test_codex_review_command_does_not_pass_prompt_with_uncommitted(self) -> None:
        from growth_dev.team.codex import CodexExecutorConfig, build_codex_review_command

        command = build_codex_review_command(
            CodexExecutorConfig(binary="/tmp/codex"),
            worktree_dir=Path("/repo/worktree"),
            run_dir=Path("/repo/runs/run-1"),
            title="run-1 code review",
        )

        self.assertIn("review", command)
        self.assertIn("--uncommitted", command)
        self.assertNotIn("-", command)

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

    def test_team_runtime_aicodemirror_provider_uses_env_key_without_recording_secret(self) -> None:
        from growth_dev.team.models import DomainSpec
        from growth_dev.team.runtime import TeamRuntime, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            secret = "sk-ant-test-secret"
            env_path = root / ".env"
            env_path.write_text(
                "aicodemirror_base_url=https://provider.example/api/codex\n"
                f"aicodemirror_key={secret}\n",
                encoding="utf-8",
            )
            fake_codex = _write_provider_asserting_fake_codex(root, secret)

            runtime = TeamRuntime(
                team=default_team_spec(),
                domain=DomainSpec(domain_id="demo", summary="Demo coding domain", risk_rules=["manual_login_only"]),
                runs_dir=root / "runs",
                repo_root=root,
                executor="codex",
                codex_binary=str(fake_codex),
                codex_model="gpt-5.5",
                codex_reasoning_effort="medium",
                codex_provider="aicodemirror",
                codex_env_file=env_path,
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
            command_text = (run_dir / "codex" / "command.json").read_text(encoding="utf-8")
            command_payload = json.loads(command_text)
            code_record_text = (run_dir / "code_run_record.json").read_text(encoding="utf-8")
            code_record = json.loads(code_record_text)

            self.assertEqual(record.status, "completed")
            self.assertIn('model_provider="aicodemirror"', command_payload["command"])
            self.assertNotIn(secret, command_text)
            self.assertNotIn(secret, code_record_text)
            self.assertEqual(code_record["provider"]["name"], "aicodemirror")
            self.assertEqual(code_record["provider"]["env_key"], "AICODEMIRROR_KEY")

    def test_run_process_streams_stdout_and_stderr_before_exit(self) -> None:
        from growth_dev.team.codex import CodexExecutor, CodexExecutorConfig

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_codex = _write_slow_fake_codex(root)
            run_dir = root / "runs" / "run-1"
            run_dir.mkdir(parents=True)
            stdout_path = run_dir / "stdout.log"
            stderr_path = run_dir / "stderr.log"
            executor = CodexExecutor(
                CodexExecutorConfig(binary=str(fake_codex), timeout_seconds=10),
                repo_root=root,
                run_dir=run_dir,
            )
            command = [str(fake_codex)]
            completed_holder: dict[str, subprocess.CompletedProcess[str]] = {}

            import threading

            thread = threading.Thread(
                target=lambda: completed_holder.setdefault(
                    "completed",
                    executor._run_process(command, "prompt", root, stdout_path, stderr_path),  # noqa: SLF001 - stream behavior is the unit under test.
                )
            )
            thread.start()
            deadline = time.time() + 1.0
            saw_streamed_line = False
            while time.time() < deadline:
                if stdout_path.exists() and "stdout-before-sleep" in stdout_path.read_text(encoding="utf-8", errors="replace"):
                    saw_streamed_line = True
                    break
                time.sleep(0.05)
            self.assertTrue(saw_streamed_line)
            self.assertNotIn("completed", completed_holder)
            thread.join(timeout=5.0)

            self.assertIn("completed", completed_holder)
            self.assertEqual(completed_holder["completed"].returncode, 0)
            self.assertIn("stderr-before-sleep", stderr_path.read_text(encoding="utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()
