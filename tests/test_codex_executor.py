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


def _write_note_risk_fake_codex(path: Path) -> Path:
    script = path / "codex-risk-notes"
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
    target = os.path.join(workspace, "growth_dev", "fake_target.py")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\\n# fake codex change with non-blocking notes\\n")

    output_path = _value_after(args, "--output-last-message", "-o")
    payload = {
        "summary": "fake codex implemented the requested dashboard change",
        "files_changed": ["growth_dev/fake_target.py"],
        "tests_run": ["python3 -c \\"print('ok')\\""],
        "risk_events": [
            "Dashboard UI assets live in top-level dashboard/, which was outside the high-level allowed list but was the nearby supporting location required to implement this Dashboard UI change.",
            "dashboard_assets_modified_as_nearby_supporting_files_required_for_the_requested_dashboard_ui_copy_change",
            "No scraping, login, captcha, proxy, fingerprinting, anti-detect, or private API behavior was added.",
        ],
        "blockers": [],
        "next_action": "review",
    }
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    print(json.dumps({"event": "exec.completed", "target": "growth_dev/fake_target.py"}))
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


def _write_outside_allowed_fake_codex(path: Path) -> Path:
    script = path / "codex-outside-allowed"
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
    target = os.path.join(workspace, "README.md")
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\\n# outside allowed path change\\n")

    output_path = _value_after(args, "--output-last-message", "-o")
    payload = {
        "summary": "fake codex changed an unrelated file",
        "files_changed": ["README.md"],
        "tests_run": ["python3 -c \\"print('ok')\\""],
        "risk_events": [],
        "blockers": [],
        "next_action": "fix changed file boundary",
    }
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    print(json.dumps({"event": "exec.completed", "target": "README.md"}))
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


def _write_app_generation_fake_codex(path: Path) -> Path:
    script = path / "codex-app-generation"
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
    if "input_prd.md" not in prompt or "app_contract.json" not in prompt or "requirements/normalized_prd.md" not in prompt:
        print("missing app generation artifacts in prompt", file=sys.stderr)
        sys.exit(3)
    app_dir = os.path.join(workspace, "generated_apps", "todo-prototype")
    public_dir = os.path.join(app_dir, "public")
    os.makedirs(public_dir, exist_ok=True)
    files = {
        os.path.join(app_dir, "README.md"): "# Todo Prototype\\n\\nRun with `node server.js`.\\n",
        os.path.join(app_dir, "runtime_smoke.js"): "const fs = require('fs');\\nconst vm = require('vm');\\nconst code = fs.readFileSync(require('path').join(__dirname, 'public', 'app.js'), 'utf8');\\nvm.runInNewContext(code, { localStorage: { getItem(){ return null; }, setItem(){} }, document: { addEventListener(){} }, console });\\nconsole.log('runtime_init_ok');\\n",
        os.path.join(app_dir, "server.js"): "const http = require('http');\\nconst fs = require('fs');\\nconst path = require('path');\\nconst publicDir = path.join(__dirname, 'public');\\nhttp.createServer((req, res) => { const file = req.url === '/' ? 'index.html' : req.url.slice(1); fs.createReadStream(path.join(publicDir, file)).on('error', () => { res.statusCode = 404; res.end('not found'); }).pipe(res); }).listen(8788, '127.0.0.1');\\n",
        os.path.join(public_dir, "index.html"): "<!doctype html><div id=\\"app\\"></div><script src=\\"app.js\\"></script>\\n",
        os.path.join(public_dir, "styles.css"): "body { font-family: sans-serif; }\\n",
        os.path.join(public_dir, "app.js"): "const key = 'todo-prototype-state';\\nconst state = JSON.parse(localStorage.getItem(key) || '[]');\\nlocalStorage.setItem(key, JSON.stringify(state));\\n",
    }
    for file_path, content in files.items():
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(content)
    output_path = _value_after(args, "--output-last-message", "-o")
    payload = {
        "summary": "generated a local todo prototype app",
        "files_changed": [
            "generated_apps/todo-prototype/README.md",
            "generated_apps/todo-prototype/runtime_smoke.js",
            "generated_apps/todo-prototype/server.js",
            "generated_apps/todo-prototype/public/index.html",
            "generated_apps/todo-prototype/public/styles.css",
            "generated_apps/todo-prototype/public/app.js",
        ],
        "tests_run": ["node --check generated_apps/todo-prototype/server.js", "node generated_apps/todo-prototype/runtime_smoke.js"],
        "risk_events": [],
        "blockers": [],
        "next_action": "review",
    }
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    print(json.dumps({"event": "exec.completed", "target": "generated_apps/todo-prototype"}))
    sys.exit(0)

if "review" in args:
    print("# Fake App Generation Review\\n\\nNo blocking issues found.")
    sys.exit(0)

print("unsupported fake codex invocation", file=sys.stderr)
sys.exit(2)
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_app_generation_broken_smoke_fake_codex(path: Path) -> Path:
    script = _write_app_generation_fake_codex(path)
    original = script.read_text(encoding="utf-8")
    script.write_text(
        original.replace(
            "console.log('runtime_init_ok');",
            "throw new Error('startup crashed before DOMContentLoaded');",
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_workbench_test_fake_codex(path: Path) -> Path:
    script = path / "codex-workbench-test"
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
    target = os.path.join(workspace, "tests", "test_mobile_image_workbench.py")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\\nimport unittest\\n\\n\\nclass WorkbenchKeywordBoundaryTests(unittest.TestCase):\\n    def test_keyword_boundary_fixture(self):\\n        self.assertTrue(True)\\n")

    output_path = _value_after(args, "--output-last-message", "-o")
    payload = {
        "summary": "fake codex added the workbench keyword UI boundary test",
        "files_changed": ["tests/test_mobile_image_workbench.py"],
        "tests_run": ["python3 -m unittest tests.test_mobile_image_workbench -v"],
        "risk_events": [
            "Modified tests/test_mobile_image_workbench.py as the newly requested supporting test boundary; no runs, data, env-file, or remote key files were modified."
        ],
        "blockers": [],
        "next_action": "review",
    }
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    print(json.dumps({"event": "exec.completed", "target": "tests/test_mobile_image_workbench.py"}))
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

    def test_codex_risk_classifier_keeps_dangerous_risks_blocking(self) -> None:
        from growth_dev.team.codex import classify_codex_risk_events

        blocking, non_blocking = classify_codex_risk_events(
            [
                "No scraping, login, captcha, proxy, fingerprinting, anti-detect, or private API behavior was added.",
                "dashboard_assets_modified_as_nearby_supporting_files_required_for_the_requested_dashboard_ui_copy_change",
                "prohibited_implementation_pattern:proxy rotation",
                "codex_response_missing_field:summary",
            ]
        )

        self.assertEqual(
            non_blocking,
            [
                "No scraping, login, captcha, proxy, fingerprinting, anti-detect, or private API behavior was added.",
                "dashboard_assets_modified_as_nearby_supporting_files_required_for_the_requested_dashboard_ui_copy_change",
            ],
        )
        self.assertEqual(blocking, ["prohibited_implementation_pattern:proxy rotation", "codex_response_missing_field:summary"])

    def test_codex_risk_classifier_treats_supporting_test_boundary_note_as_non_blocking(self) -> None:
        from growth_dev.team.codex import classify_codex_risk_events

        event = (
            "Modified tests/test_mobile_image_workbench.py as the newly requested supporting "
            "test boundary; no runs, data, env-file, or remote key files were modified."
        )

        blocking, non_blocking = classify_codex_risk_events([event])

        self.assertEqual(blocking, [])
        self.assertEqual(non_blocking, [event])

    def test_codex_risk_classifier_treats_sandbox_preview_and_provider_notes_as_non_blocking(self) -> None:
        from growth_dev.team.codex import classify_codex_risk_events

        events = [
            "Local preview bind to 127.0.0.1:8788 failed in this sandbox with EPERM; server now reports the failure clearly and declared verification commands passed.",
            "Provider is not configured; the app shows a clear setup error and does not persist secrets.",
            "External image provider capability is explicit and server-side only; no hidden network call was added.",
        ]

        blocking, non_blocking = classify_codex_risk_events(events)

        self.assertEqual(blocking, [])
        self.assertEqual(non_blocking, events)

    def test_codex_risk_classifier_treats_no_disallowed_behavior_self_assertion_as_non_blocking(self) -> None:
        from growth_dev.team.codex import classify_codex_risk_events

        event = (
            "no_disallowed_risk_behavior: prototype uses localStorage and a local Node server only; "
            "no database, credential collection, hidden network calls, external deploy, captcha handling, "
            "proxying, or fingerprint behavior was added."
        )

        blocking, non_blocking = classify_codex_risk_events([event])

        self.assertEqual(blocking, [])
        self.assertEqual(non_blocking, [event])

    def test_codex_risk_classifier_keeps_unrelated_no_prefix_events_blocking(self) -> None:
        from growth_dev.team.codex import classify_codex_risk_events

        events = [
            "no_acceptance_tests_were_added_for_slice-003",
            "no-changed-files: implementation produced an empty diff",
            "No coverage matrix entries match slice-002",
        ]

        blocking, non_blocking = classify_codex_risk_events(events)

        self.assertEqual(non_blocking, [])
        self.assertEqual(blocking, events)

    def test_codex_diff_risk_scan_ignores_context_deletions_and_safety_boundary_text(self) -> None:
        from growth_dev.team.codex import _scan_implementation_risks

        diff_text = """
diff --git a/domains/xhs_mobile_collection/capabilities.yaml b/domains/xhs_mobile_collection/capabilities.yaml
@@ -1,8 +1,10 @@
 unsupported:
   - id: captcha_or_risk_bypass
     summary: Captcha solving, fingerprint spoofing, proxy rotation, and anti-bot evasion are prohibited.
-legacy_note: proxy rotation was previously mentioned in documentation
+planned:
+  - summary: This UI must not implement fingerprint spoofing, proxy rotation, or anti-detect behavior.
+risk_rules:
+  - no_fingerprint_spoofing
+  - no_proxy_rotation
"""

        self.assertEqual(_scan_implementation_risks(diff_text), [])

    def test_codex_diff_risk_scan_keeps_added_dangerous_patterns_blocking(self) -> None:
        from growth_dev.team.codex import _scan_implementation_risks

        diff_text = """
diff --git a/scraper.py b/scraper.py
@@ -1,2 +1,4 @@
+proxy_pool = load_proxy_pool()
+driver.install("puppeteer-extra-plugin-stealth")
"""

        self.assertEqual(
            _scan_implementation_risks(diff_text),
            [
                "prohibited_implementation_pattern:puppeteer-extra-plugin-stealth",
                "prohibited_implementation_pattern:proxy_pool",
            ],
        )

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

    def test_codex_exec_command_includes_git_metadata_add_dirs(self) -> None:
        from growth_dev.team.codex import CodexExecutorConfig, build_codex_exec_command

        command = build_codex_exec_command(
            CodexExecutorConfig(binary="/tmp/codex", extra_add_dirs=["/repo/.git/worktrees/run-1", "/repo/.git"]),
            worktree_dir=Path("/repo/runs/run-1/worktree"),
            run_dir=Path("/repo/runs/run-1"),
            output_schema_path=Path("/repo/runs/run-1/codex/codex_response_schema.json"),
            output_last_message_path=Path("/repo/runs/run-1/codex/last_message.json"),
        )

        add_dirs = [command[index + 1] for index, item in enumerate(command) if item == "--add-dir"]
        self.assertIn("/repo/runs/run-1", add_dirs)
        self.assertIn("/repo/.git/worktrees/run-1", add_dirs)
        self.assertIn("/repo/.git", add_dirs)

    def test_prepare_worktree_adds_git_metadata_dirs_without_repo_root(self) -> None:
        from growth_dev.team.codex import CodexExecutor, CodexExecutorConfig

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            executor = CodexExecutor(CodexExecutorConfig(binary="/tmp/codex"), repo_root=root, run_dir=root / "runs" / "run-1")

            worktree = executor.prepare_worktree()
            extra_dirs = executor.config.extra_add_dirs
            self.assertTrue((worktree / ".git").exists())
            self.assertIn(str((root / ".git").resolve()), extra_dirs)
            self.assertTrue(any(".git/worktrees" in path for path in extra_dirs))
            self.assertNotIn(str(root.resolve()), extra_dirs)

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
            requirements_dir = run_dir / "requirements"
            planning_dir = run_dir / "planning"
            requirements_dir.mkdir()
            planning_dir.mkdir()
            (requirements_dir / "capability_boundary.md").write_text(
                "# Capability Boundary\n\n- Existing: image_then_keyword_collection\n",
                encoding="utf-8",
            )
            (planning_dir / "tdd_plan.md").write_text(
                "# TDD Plan\n\n- First write failing CLI and flow tests.\n",
                encoding="utf-8",
            )
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
        self.assertIn("Capability Boundary", prompt_text)
        self.assertIn("requirements/capability_boundary.md", prompt_text)
        self.assertIn("TDD Plan", prompt_text)
        self.assertIn("planning/tdd_plan.md", prompt_text)
        self.assertIn("manual_login_only", summary_text)
        self.assertIn("prd.md", summary_text)
        self.assertIn("Build it.", summary_text)
        self.assertEqual(schema["required"], ["summary", "files_changed", "tests_run", "risk_events", "blockers", "next_action"])

    def test_prompt_bundle_merges_task_level_allowed_paths_from_brief(self) -> None:
        from growth_dev.team.codex import CodexExecutor, CodexExecutorConfig
        from growth_dev.team.models import DomainSpec
        from growth_dev.team.runtime import default_team_spec
        from growth_dev.team.agents import AgentContext
        from growth_dev.team.models import TeamRunRecord

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "runs" / "run-1"
            run_dir.mkdir(parents=True)
            brief = (
                "扩展 domain pack。allowed_paths 需要允许： "
                "- third_party/mobile_image_workbench/backend/mobile_image_workbench/ "
                "- third_party/mobile_image_workbench/frontend/src/ "
                "- third_party/mobile_image_workbench/README.md "
                "- tests/test_mobile_image_workbench.py "
                "不允许修改 .env、runs/、third_party/mobile_asset_center/data/、remote.key"
            )
            record = TeamRunRecord(run_id="run-1", domain_id="demo", brief=brief, run_dir=run_dir)
            context = AgentContext(
                run_id="run-1",
                run_dir=run_dir,
                repo_root=root,
                executor="codex",
                brief=brief,
                team=default_team_spec(),
                domain=DomainSpec(
                    domain_id="demo",
                    risk_rules=["manual_login_only"],
                    metadata={"allowed_paths": ["domains/demo/"]},
                ),
                inputs={},
                record=record,
            )

            bundle = CodexExecutor(CodexExecutorConfig(), repo_root=root, run_dir=run_dir).write_prompt_bundle("coder", context)
            prompt_bundle = json.loads((run_dir / "codex" / "prompt_bundle.json").read_text(encoding="utf-8"))

        self.assertIn("domains/demo/", prompt_bundle["allowed_paths"])
        self.assertIn("third_party/mobile_image_workbench/backend/mobile_image_workbench/", prompt_bundle["allowed_paths"])
        self.assertIn("third_party/mobile_image_workbench/frontend/src/", prompt_bundle["allowed_paths"])
        self.assertIn("third_party/mobile_image_workbench/README.md", prompt_bundle["allowed_paths"])
        self.assertIn("tests/test_mobile_image_workbench.py", prompt_bundle["allowed_paths"])
        self.assertNotIn(".env", prompt_bundle["allowed_paths"])
        self.assertNotIn("runs/", prompt_bundle["allowed_paths"])
        self.assertNotIn("third_party/mobile_asset_center/data/", prompt_bundle["allowed_paths"])
        self.assertNotIn("remote.key", prompt_bundle["allowed_paths"])

    def test_prompt_bundle_merges_allowed_paths_from_planned_slices(self) -> None:
        from growth_dev.team.codex import CodexExecutor, CodexExecutorConfig
        from growth_dev.team.models import DomainSpec, TeamRunRecord
        from growth_dev.team.runtime import default_team_spec
        from growth_dev.team.agents import AgentContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "runs" / "run-1"
            slices_dir = run_dir / "slices"
            slices_dir.mkdir(parents=True)
            (slices_dir / "slice-001.yaml").write_text(
                "\n".join(
                    [
                        "slice_id: slice-001",
                        "title: Workbench entry",
                        "allowed_paths:",
                        "  - tests/test_mobile_image_workbench.py",
                        "  - .env",
                        "  - runs/",
                        "  - third_party/mobile_asset_center/data/",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            record = TeamRunRecord(run_id="run-1", domain_id="demo", brief="Add a workbench entry.", run_dir=run_dir)
            context = AgentContext(
                run_id="run-1",
                run_dir=run_dir,
                repo_root=root,
                executor="codex",
                brief="Add a workbench entry.",
                team=default_team_spec(),
                domain=DomainSpec(
                    domain_id="demo",
                    risk_rules=["manual_login_only"],
                    metadata={"allowed_paths": ["domains/demo/"]},
                ),
                inputs={},
                record=record,
            )

            CodexExecutor(CodexExecutorConfig(), repo_root=root, run_dir=run_dir).write_prompt_bundle("coder", context)
            prompt_bundle = json.loads((run_dir / "codex" / "prompt_bundle.json").read_text(encoding="utf-8"))

        self.assertIn("domains/demo/", prompt_bundle["allowed_paths"])
        self.assertIn("tests/test_mobile_image_workbench.py", prompt_bundle["allowed_paths"])
        self.assertNotIn(".env", prompt_bundle["allowed_paths"])
        self.assertNotIn("runs/", prompt_bundle["allowed_paths"])
        self.assertNotIn("third_party/mobile_asset_center/data/", prompt_bundle["allowed_paths"])

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
            trace = json.loads((run_dir / "codex" / "implementation_trace.json").read_text(encoding="utf-8"))
            classification = json.loads((run_dir / "codex" / "failure_classification.json").read_text(encoding="utf-8"))
            prompt_exists = (run_dir / "codex" / "codex_prompt.md").exists()

            self.assertEqual(result.status, "failed")
            self.assertEqual(trace["status"], "failed")
            self.assertEqual(trace["current_step"], "check_executor")
            self.assertIn("codex_binary_missing", trace["blockers"])
            self.assertIn("codex_binary_missing", code_record["risk_events"])
            self.assertEqual(classification["classification_decision"], "failed")
            self.assertIn("codex_binary_missing", classification["blocking_events"])
            self.assertEqual(code_record["artifacts"]["failure_classification"], "codex/failure_classification.json")
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
            trace = json.loads((run_dir / "codex" / "implementation_trace.json").read_text(encoding="utf-8"))
            review_report = (run_dir / "review_report.md").read_text(encoding="utf-8")
            test_report = (run_dir / "test_report.md").read_text(encoding="utf-8")
            diff_exists = (run_dir / "codex" / "diff.patch").exists()

            self.assertEqual(record.status, "completed")
            self.assertEqual(code_record["executor"], "codex")
            self.assertEqual(trace["status"], "completed")
            self.assertEqual(trace["stage"], "coder")
            self.assertTrue(trace["steps"])
            self.assertEqual(trace["evidence"]["diff_path"], "codex/diff.patch")
            self.assertIn("growth_dev/fake_target.py", trace["evidence"]["changed_files"])
            self.assertIn("python3 -c \"print('ok')\"", trace["evidence"]["tests_run"])
            self.assertEqual(code_record["artifacts"]["implementation_trace"], "codex/implementation_trace.json")
            self.assertIn("growth_dev/fake_target.py", code_record["files_changed"])
            self.assertTrue(diff_exists)
            self.assertIn("Fake Codex Review", review_report)
            self.assertIn("## 结论", review_report)
            self.assertIn("状态：通过", review_report)
            self.assertIn("建议：可以进入测试验收 / 交付验收。", review_report)
            self.assertIn("## 本次评审范围", review_report)
            self.assertIn("growth_dev/fake_target.py", review_report)
            self.assertIn("## 评审维度", review_report)
            self.assertIn("功能正确性：通过", review_report)
            self.assertIn("测试覆盖：通过", review_report)
            self.assertIn("## Findings", review_report)
            self.assertIn("Critical：无", review_report)
            self.assertIn("## 测试证据", review_report)
            self.assertIn("python3 -c \"print('ok')\"", review_report)
            self.assertIn("## Diff 证据", review_report)
            self.assertIn("codex/diff.patch", review_report)
            self.assertIn("## 风险与阻塞", review_report)
            self.assertIn("Blocking risk：无", review_report)
            self.assertIn("python3 -c", test_report)
            self.assertIn("## 结论", test_report)
            self.assertIn("状态：通过", test_report)
            self.assertIn("## 代码变化证据", test_report)
            self.assertIn("growth_dev/fake_target.py", test_report)
            self.assertIn("## AI 自测证据", test_report)
            self.assertIn("python3 -c \"print('ok')\"", test_report)
            self.assertIn("## 执行流程证据", test_report)
            self.assertIn("codex/diff.patch", test_report)
            self.assertIn("## 风险与阻塞", test_report)
            self.assertIn("阻塞：无", test_report)

    def test_codex_slice_loop_artifacts_capture_planned_slices(self) -> None:
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
                planning_mode="llm_assisted",
                requirements_model="gpt-5.3",
            )
            record = runtime.run(
                "Implement a complex Dashboard workflow with coverage-driven slices.",
                inputs={
                    "allowed_paths": ["growth_dev/fake_target.py"],
                    "verification_commands": ["python3 -c \"print('ok')\""],
                },
                run_id="run-1",
            )

            run_dir = root / "runs" / "run-1"
            code_record = json.loads((run_dir / "code_run_record.json").read_text(encoding="utf-8"))
            prompt_text = (run_dir / "codex" / "codex_prompt.md").read_text(encoding="utf-8")
            loop_state = json.loads((run_dir / "codex" / "slice_loop_state.json").read_text(encoding="utf-8"))
            slice_trace = json.loads((run_dir / "codex" / "slices" / "slice-001" / "slice_trace.json").read_text(encoding="utf-8"))
            completion_gate = json.loads((run_dir / "implementation_completion_gate.json").read_text(encoding="utf-8"))
            completion_gate_md = (run_dir / "implementation_completion_gate.md").read_text(encoding="utf-8")

        self.assertEqual(record.status, "completed")
        self.assertEqual(loop_state["status"], "completed")
        self.assertEqual(loop_state["execution_strategy"], "single_codex_pass_over_planned_slices_v1")
        self.assertIn("slice-001", loop_state["completed_slice_ids"])
        self.assertEqual(slice_trace["status"], "completed")
        self.assertEqual(slice_trace["execution_strategy"], "single_codex_pass_over_planned_slices_v1")
        self.assertEqual(slice_trace["acceptance_criteria_ids"], ["AC-001"])
        self.assertIn("growth_dev/fake_target.py", slice_trace["evidence"]["changed_files"])
        self.assertEqual(completion_gate["status"], "passed")
        self.assertIn("all_slices_completed", [item["id"] for item in completion_gate["checks"]])
        self.assertIn("# Implementation Completion Gate", completion_gate_md)
        self.assertIn("Codex Slice-Loop", prompt_text)
        self.assertIn("Acceptance Coverage Matrix", prompt_text)
        self.assertEqual(code_record["artifacts"]["slice_loop_state"], "codex/slice_loop_state.json")
        self.assertEqual(code_record["artifacts"]["implementation_completion_gate"], "implementation_completion_gate.json")

    def test_codex_non_blocking_risk_notes_do_not_fail_coder_gate(self) -> None:
        from growth_dev.team.models import DomainSpec
        from growth_dev.team.runtime import TeamRuntime, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            fake_codex = _write_note_risk_fake_codex(root)

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
            trace = json.loads((run_dir / "codex" / "implementation_trace.json").read_text(encoding="utf-8"))
            coder_run = next(agent_run for agent_run in record.agent_runs if agent_run.agent_id == "coder")

            self.assertEqual(record.status, "completed")
            self.assertEqual(coder_run.status, "completed")
            self.assertEqual(coder_run.risk_events, [])
            self.assertEqual(code_record["status"], "completed")
            self.assertEqual(code_record["risk_events"], [])
            self.assertEqual(code_record["blocking_risk_events"], [])
            self.assertEqual(len(code_record["non_blocking_risk_events"]), 3)
            self.assertEqual(code_record["failure_classification"]["classification_decision"], "passed_with_warnings")
            self.assertEqual(code_record["artifacts"]["failure_classification"], "codex/failure_classification.json")
            self.assertEqual(trace["status"], "completed")
            self.assertEqual(trace["risk_events"], [])
            self.assertEqual(len(trace["non_blocking_risk_events"]), 3)
            self.assertEqual(trace["failure_classification"]["classification_decision"], "passed_with_warnings")
            classification = json.loads((run_dir / "codex" / "failure_classification.json").read_text(encoding="utf-8"))
            classification_md = (run_dir / "codex" / "failure_classification.md").read_text(encoding="utf-8")
            self.assertEqual(classification["classification_decision"], "passed_with_warnings")
            self.assertEqual(classification["blocking_events"], [])
            self.assertEqual(len(classification["warnings"]), 3)
            self.assertIn("supporting_location_note", {event["id"] for event in classification["events"]})
            self.assertIn("# Failure Classification", classification_md)

    def test_codex_failure_classification_blocks_changed_files_outside_allowed_paths(self) -> None:
        from growth_dev.team.models import DomainSpec
        from growth_dev.team.runtime import TeamRuntime, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            fake_codex = _write_outside_allowed_fake_codex(root)

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
            trace = json.loads((run_dir / "codex" / "implementation_trace.json").read_text(encoding="utf-8"))
            classification = json.loads((run_dir / "codex" / "failure_classification.json").read_text(encoding="utf-8"))

            self.assertEqual(record.status, "failed")
            self.assertEqual(code_record["status"], "failed")
            self.assertEqual(classification["classification_decision"], "failed")
            self.assertIn("changed_file_outside_allowed_paths:README.md", classification["blocking_events"])
            self.assertIn("changed_file_outside_allowed_paths:README.md", code_record["risk_events"])
            self.assertEqual(trace["failure_classification"]["classification_decision"], "failed")

    def test_app_generation_codex_prompt_and_verifier_use_app_contract(self) -> None:
        from growth_dev.team.runtime import TeamRuntime, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_placeholder.py").write_text(
                "import unittest\n\n\nclass PlaceholderTests(unittest.TestCase):\n    def test_placeholder(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            _run(["git", "add", "."], root)
            _run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "add tests"], root)
            fake_codex = _write_app_generation_fake_codex(root)

            runtime = TeamRuntime.from_domain(
                "app_generation",
                domains_dir=Path.cwd() / "domains",
                runs_dir=root / "runs",
                team=default_team_spec(),
                repo_root=root,
                executor="codex",
                codex_binary=str(fake_codex),
                codex_model="gpt-5.3-codex",
            )
            record = runtime.run(
                "根据 PRD 生成本地 Todo 原型应用",
                inputs={
                    "app_slug": "todo-prototype",
                    "prd_text": "# Todo Prototype\n\n用户可以新增和完成待办，状态保存在浏览器本地。",
                },
                run_id="app-codex-run",
            )

            run_dir = root / "runs" / "app-codex-run"
            prompt_text = (run_dir / "codex" / "codex_prompt.md").read_text(encoding="utf-8")
            prompt_bundle = json.loads((run_dir / "codex" / "prompt_bundle.json").read_text(encoding="utf-8"))
            code_record = json.loads((run_dir / "code_run_record.json").read_text(encoding="utf-8"))
            verification = json.loads((run_dir / "codex" / "verification_record.json").read_text(encoding="utf-8"))
            test_report = (run_dir / "test_report.md").read_text(encoding="utf-8")
            preview = (run_dir / "preview_instructions.md").read_text(encoding="utf-8")

        self.assertEqual(record.status, "completed")
        self.assertIn("input_prd.md", prompt_text)
        self.assertIn("requirements/normalized_prd.md", prompt_text)
        self.assertIn("app_contract.json", prompt_text)
        self.assertIn("runtime_smoke.js", prompt_text)
        self.assertIn("generated_apps/todo-prototype/", prompt_bundle["allowed_paths"])
        self.assertIn("node --check generated_apps/todo-prototype/server.js", prompt_bundle["verification_commands"])
        self.assertIn("node generated_apps/todo-prototype/runtime_smoke.js", prompt_bundle["verification_commands"])
        self.assertIn("generated_apps/todo-prototype/server.js", code_record["files_changed"])
        self.assertIn("generated_apps/todo-prototype/runtime_smoke.js", code_record["files_changed"])
        self.assertEqual(verification["status"], "completed")
        self.assertIn("node --check generated_apps/todo-prototype/server.js", [item["command"] for item in verification["commands"]])
        self.assertIn("node generated_apps/todo-prototype/runtime_smoke.js", [item["command"] for item in verification["commands"]])
        self.assertIn("node --check generated_apps/todo-prototype/server.js", test_report)
        self.assertIn("node generated_apps/todo-prototype/runtime_smoke.js", test_report)
        self.assertIn("cd generated_apps/todo-prototype", preview)

    def test_app_generation_runtime_smoke_failure_blocks_coder(self) -> None:
        from growth_dev.team.runtime import TeamRuntime, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_placeholder.py").write_text(
                "import unittest\n\n\nclass PlaceholderTests(unittest.TestCase):\n    def test_placeholder(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            _run(["git", "add", "."], root)
            _run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "add tests"], root)
            fake_codex = _write_app_generation_broken_smoke_fake_codex(root)

            runtime = TeamRuntime.from_domain(
                "app_generation",
                domains_dir=Path.cwd() / "domains",
                runs_dir=root / "runs",
                team=default_team_spec(),
                repo_root=root,
                executor="codex",
                codex_binary=str(fake_codex),
                codex_model="gpt-5.3-codex",
            )
            record = runtime.run(
                "根据 PRD 生成本地 Todo 原型应用",
                inputs={
                    "app_slug": "todo-prototype",
                    "prd_text": "# Todo Prototype\n\n用户可以新增和完成待办，状态保存在浏览器本地。",
                },
                run_id="app-codex-smoke-fail",
            )

            run_dir = root / "runs" / "app-codex-smoke-fail"
            code_record = json.loads((run_dir / "code_run_record.json").read_text(encoding="utf-8"))
            classification = json.loads((run_dir / "codex" / "failure_classification.json").read_text(encoding="utf-8"))
            runtime_verification = json.loads((run_dir / "codex" / "app_runtime_verification.json").read_text(encoding="utf-8"))

        self.assertEqual(record.status, "failed")
        self.assertEqual(code_record["status"], "failed")
        self.assertEqual(runtime_verification["status"], "failed")
        self.assertIn(
            "app_runtime_verification_failed:node generated_apps/todo-prototype/runtime_smoke.js:1",
            classification["blocking_events"],
        )

    def test_benchmark_parity_context_is_included_in_codex_prompt(self) -> None:
        from growth_dev.team.runtime import TeamRuntime, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_placeholder.py").write_text(
                "import unittest\n\n\nclass PlaceholderTests(unittest.TestCase):\n    def test_placeholder(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            _run(["git", "add", "."], root)
            _run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "add tests"], root)
            fake_codex = _write_app_generation_fake_codex(root)

            runtime = TeamRuntime.from_domain(
                "app_generation",
                domains_dir=Path.cwd() / "domains",
                runs_dir=root / "runs",
                team=default_team_spec(),
                repo_root=root,
                executor="codex",
                codex_binary=str(fake_codex),
                codex_model="gpt-5.3-codex",
            )
            record = runtime.run(
                "根据 PRD 生成 Dingdang benchmark 应用",
                inputs={
                    "app_slug": "dingdang-main-image-agent",
                    "prd_file": "benchmarks/app_generation/dingdang_main_image_agent/input_prd.md",
                },
                run_id="dingdang-benchmark-prompt",
            )

            run_dir = root / "runs" / "dingdang-benchmark-prompt"
            prompt_text = (run_dir / "codex" / "codex_prompt.md").read_text(encoding="utf-8")
            benchmark_context = json.loads((run_dir / "benchmark_context.json").read_text(encoding="utf-8"))

        self.assertIn("benchmark_context.md", prompt_text)
        self.assertIn("Benchmark Parity", prompt_text)
        self.assertIn("product_image_upload", prompt_text)
        self.assertIn("reference_image_upload", prompt_text)
        self.assertIn("image_download", prompt_text)
        self.assertIn("https://openrouter.ai/api/v1/images", prompt_text)
        self.assertIn("input_references", prompt_text)
        self.assertIn("openai/gpt-image-1", prompt_text)
        self.assertIn("第 X 张第 Y 层", prompt_text)
        self.assertEqual(benchmark_context["quality_mode"], "benchmark_parity")
        self.assertIn(record.status, {"completed", "failed"})

    def test_benchmark_parity_missing_required_capabilities_blocks_coder(self) -> None:
        from growth_dev.team.runtime import TeamRuntime, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_placeholder.py").write_text(
                "import unittest\n\n\nclass PlaceholderTests(unittest.TestCase):\n    def test_placeholder(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            _run(["git", "add", "."], root)
            _run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "add tests"], root)
            fake_codex = _write_app_generation_fake_codex(root)

            runtime = TeamRuntime.from_domain(
                "app_generation",
                domains_dir=Path.cwd() / "domains",
                runs_dir=root / "runs",
                team=default_team_spec(),
                repo_root=root,
                executor="codex",
                codex_binary=str(fake_codex),
                codex_model="gpt-5.3-codex",
            )
            record = runtime.run(
                "根据 PRD 生成 Dingdang benchmark 应用",
                inputs={
                    "app_slug": "dingdang-main-image-agent",
                    "prd_file": "benchmarks/app_generation/dingdang_main_image_agent/input_prd.md",
                },
                run_id="dingdang-benchmark-static-fail",
            )

            run_dir = root / "runs" / "dingdang-benchmark-static-fail"
            classification = json.loads((run_dir / "codex" / "failure_classification.json").read_text(encoding="utf-8"))
            benchmark_diff = (run_dir / "benchmark_diff.md").read_text(encoding="utf-8")
            agqs_score = json.loads((run_dir / "agqs_score.json").read_text(encoding="utf-8"))

        self.assertEqual(record.status, "failed")
        self.assertIn("benchmark_parity_missing:product_image_upload", classification["blocking_events"])
        self.assertIn("benchmark_parity_missing:reference_image_upload", classification["blocking_events"])
        self.assertIn("benchmark_parity_missing:image_provider_proxy", classification["blocking_events"])
        self.assertIn("product_image_upload", benchmark_diff)
        self.assertEqual(agqs_score["hard_gate_status"], "failed")

    def test_app_generation_codex_blocks_files_outside_generated_app_path(self) -> None:
        from growth_dev.team.runtime import TeamRuntime, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            fake_codex = _write_outside_allowed_fake_codex(root)

            runtime = TeamRuntime.from_domain(
                "app_generation",
                domains_dir=Path.cwd() / "domains",
                runs_dir=root / "runs",
                team=default_team_spec(),
                repo_root=root,
                executor="codex",
                codex_binary=str(fake_codex),
                codex_model="gpt-5.3-codex",
            )
            record = runtime.run(
                "根据 PRD 生成本地 Todo 原型应用",
                inputs={
                    "app_slug": "todo-prototype",
                    "prd_text": "# Todo Prototype\n\n用户可以新增和完成待办。",
                },
                run_id="app-codex-boundary-run",
            )

            run_dir = root / "runs" / "app-codex-boundary-run"
            classification = json.loads((run_dir / "codex" / "failure_classification.json").read_text(encoding="utf-8"))

        self.assertEqual(record.status, "failed")
        self.assertIn("changed_file_outside_allowed_paths:README.md", classification["blocking_events"])

    def test_task_level_allowed_paths_override_unblocks_domain_expansion_supporting_tests(self) -> None:
        from growth_dev.team.models import DomainSpec
        from growth_dev.team.runtime import TeamRuntime, default_team_spec

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_repo(root)
            fake_codex = _write_workbench_test_fake_codex(root)
            brief = (
                "扩展 xhs_mobile_collection domain pack。allowed_paths 需要允许： "
                "- tests/test_mobile_image_workbench.py "
                "不允许修改 .env、runs/、third_party/mobile_asset_center/data/。"
            )

            runtime = TeamRuntime(
                team=default_team_spec(),
                domain=DomainSpec(
                    domain_id="xhs_mobile_collection",
                    summary="Demo xhs domain",
                    risk_rules=["manual_login_only"],
                    metadata={"allowed_paths": ["domains/xhs_mobile_collection/", "tests/test_xhs_collector.py"]},
                ),
                runs_dir=root / "runs",
                repo_root=root,
                executor="codex",
                codex_binary=str(fake_codex),
                codex_model="gpt-5.3-codex",
                codex_reasoning_effort="medium",
            )
            record = runtime.run(brief, run_id="run-1")

            run_dir = root / "runs" / "run-1"
            prompt_bundle = json.loads((run_dir / "codex" / "prompt_bundle.json").read_text(encoding="utf-8"))
            code_record = json.loads((run_dir / "code_run_record.json").read_text(encoding="utf-8"))
            classification = json.loads((run_dir / "codex" / "failure_classification.json").read_text(encoding="utf-8"))

            self.assertEqual(record.status, "completed")
            self.assertIn("tests/test_mobile_image_workbench.py", prompt_bundle["allowed_paths"])
            self.assertNotIn("dashboard/", prompt_bundle["allowed_paths"])
            self.assertNotIn("growth_dev/", prompt_bundle["allowed_paths"])
            self.assertEqual(classification["classification_decision"], "passed_with_warnings")
            self.assertEqual(classification["blocking_events"], [])
            self.assertEqual(code_record["risk_events"], [])
            self.assertIn("tests/test_mobile_image_workbench.py", code_record["files_changed"])

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
            deadline = time.time() + 3.0
            saw_streamed_line = False
            while time.time() < deadline and "completed" not in completed_holder:
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
