"""Unit tests for the benchmark fix-slice (second-pass coder) flow.

Sandbox-safe: avoid `git init`, avoid real codex subprocess. We construct
minimal benchmark artifacts on disk, then drive `_maybe_run_benchmark_fix_slice`
by stubbing `_run_process` to mutate the worktree and emit a structured
`last_message.json`.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any


def _write_app_files(app_dir: Path, capability_text: str = "") -> None:
    (app_dir / "public").mkdir(parents=True, exist_ok=True)
    (app_dir / "server.js").write_text(
        "const http = require('http');\n"
        "// POST /api/images/generate via openai\n"
        "const OPENROUTER_API_BASE_URL = 'https://openrouter.ai/api/v1';\n"
        "async function openrouterImages(){ return fetch(OPENROUTER_API_BASE_URL + '/images', { method: 'POST', body: JSON.stringify({ input_references: [] }) }); }\n"
        + capability_text,
        encoding="utf-8",
    )
    (app_dir / "public" / "index.html").write_text(
        "<input id='product-image-input' type=\"file\" aria-label=\"产品图\">\n"
        "<input id='reference-image-input' type=\"file\" aria-label=\"参考图\">\n"
        "<button class='generate-single'>生成当前图片</button>\n"
        "<button id='batch-generate'>批量生成</button>\n"
        "<button class='download-prompt'>下载 Prompt</button>\n"
        "<button class='download-image'>下载图片</button>\n",
        encoding="utf-8",
    )
    (app_dir / "public" / "app.js").write_text(
        "async function generateImage(){ await fetch('/api/images/generate'); }\n"
        "async function batchGenerate(){ generateImage(); }\n"
        "function downloadPrompt(){} function downloadImage(){}\n"
        "const productImage='', referenceImage='';\n"
        "const stage={current:'stage_workflow'};\n"
        "const taskType={value:'完整 8 张主图'};\n"
        "let selectedConcept=null;\n"
        "const platforms=['天猫','淘宝','抖音','拼多多'];\n"
        "const main_image_plan=new Array(8);\n"
        "const prompt_layer={layer1:'',negative_prompt:''};\n"
        "function regenerate_layer(){}\n",
        encoding="utf-8",
    )
    (app_dir / "README.md").write_text("# generated\n", encoding="utf-8")
    (app_dir / ".env.example").write_text(
        "OPENAI_API_KEY=sk-your-key-here\nOPENROUTER_API_KEY=sk-or-v1-your-key-here\n",
        encoding="utf-8",
    )


def _make_run_dir(tmp: Path) -> tuple[Path, Path, dict[str, Any]]:
    run_dir = tmp / "run"
    run_dir.mkdir()
    worktree = tmp / "worktree"
    (worktree / "generated_apps" / "dingdang-main-image-agent").mkdir(parents=True)
    from growth_dev.team.app_generation import prepare_app_generation_artifacts

    artifacts = prepare_app_generation_artifacts(
        run_id="fix-slice-test",
        run_dir=run_dir,
        inputs={
            "app_slug": "dingdang-main-image-agent",
            "prd_file": "benchmarks/app_generation/dingdang_main_image_agent/input_prd.md",
        },
    )
    return run_dir, worktree, artifacts["app_contract"]


def _make_executor(run_dir: Path, tmp: Path):
    from growth_dev.team.codex import CodexExecutor, CodexExecutorConfig

    config = CodexExecutorConfig(binary=str(tmp / "fake-codex"))
    (tmp / "fake-codex").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tmp / "fake-codex").chmod(0o755)
    return CodexExecutor(config, repo_root=tmp, run_dir=run_dir)


def _make_context(run_dir: Path, tmp: Path):
    from growth_dev.team.agents import AgentContext
    from growth_dev.team.models import DomainSpec, TeamRunRecord
    from growth_dev.team.runtime import default_team_spec

    return AgentContext(
        run_id="fix-slice-test",
        run_dir=run_dir,
        repo_root=tmp,
        executor="codex",
        brief="benchmark fix slice",
        team=default_team_spec(),
        domain=DomainSpec(domain_id="app_generation", risk_rules=[]),
        inputs={"app_slug": "dingdang-main-image-agent"},
        record=TeamRunRecord(
            run_id="fix-slice-test",
            domain_id="app_generation",
            brief="benchmark fix slice",
            run_dir=run_dir,
        ),
    )


class BenchmarkFixSliceTests(unittest.TestCase):
    def test_skips_when_first_evaluation_not_enabled(self) -> None:
        from growth_dev.team.codex import CodexExecutor

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            run_dir, worktree, _ = _make_run_dir(tmp)
            executor = _make_executor(run_dir, tmp)
            bundle = executor.write_prompt_bundle("coder", _make_context(run_dir, tmp))
            ctx = _make_context(run_dir, tmp)
            result = executor._maybe_run_benchmark_fix_slice(
                context=ctx,
                bundle=bundle,
                worktree_dir=worktree,
                previous_record={"exit_code": 0},
                first_evaluation={"enabled": False, "blocking_events": []},
            )
        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "evaluation_not_enabled")

    def test_skips_when_no_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            run_dir, worktree, _ = _make_run_dir(tmp)
            executor = _make_executor(run_dir, tmp)
            bundle = executor.write_prompt_bundle("coder", _make_context(run_dir, tmp))
            ctx = _make_context(run_dir, tmp)
            result = executor._maybe_run_benchmark_fix_slice(
                context=ctx,
                bundle=bundle,
                worktree_dir=worktree,
                previous_record={"exit_code": 0},
                first_evaluation={"enabled": True, "blocking_events": []},
            )
        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "no_missing")

    def test_skips_when_first_round_failed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            run_dir, worktree, _ = _make_run_dir(tmp)
            executor = _make_executor(run_dir, tmp)
            bundle = executor.write_prompt_bundle("coder", _make_context(run_dir, tmp))
            ctx = _make_context(run_dir, tmp)
            result = executor._maybe_run_benchmark_fix_slice(
                context=ctx,
                bundle=bundle,
                worktree_dir=worktree,
                previous_record={"exit_code": 1},
                first_evaluation={
                    "enabled": True,
                    "blocking_events": ["benchmark_parity_missing:image_provider_proxy"],
                },
            )
        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "first_round_failed")

    def test_skips_when_disabled_by_env(self) -> None:
        import os

        os.environ["BENCHMARK_FIX_SLICE_DISABLE"] = "1"
        try:
            with tempfile.TemporaryDirectory() as raw:
                tmp = Path(raw)
                run_dir, worktree, _ = _make_run_dir(tmp)
                executor = _make_executor(run_dir, tmp)
                bundle = executor.write_prompt_bundle("coder", _make_context(run_dir, tmp))
                ctx = _make_context(run_dir, tmp)
                result = executor._maybe_run_benchmark_fix_slice(
                    context=ctx,
                    bundle=bundle,
                    worktree_dir=worktree,
                    previous_record={"exit_code": 0},
                    first_evaluation={
                        "enabled": True,
                        "blocking_events": ["benchmark_parity_missing:image_provider_proxy"],
                    },
                )
        finally:
            os.environ.pop("BENCHMARK_FIX_SLICE_DISABLE", None)
        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "disabled_env")

    def test_remediates_when_second_round_fills_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            run_dir, worktree, contract = _make_run_dir(tmp)
            app_dir = worktree / contract["generated_app_dir"]
            _write_app_files(app_dir, capability_text="// initial missing provider_setup_error wording\n")

            executor = _make_executor(run_dir, tmp)
            bundle = executor.write_prompt_bundle("coder", _make_context(run_dir, tmp))
            ctx = _make_context(run_dir, tmp)

            def fake_run_process(command, prompt_text, cwd, stdout_path, stderr_path):
                (app_dir / "server.js").write_text(
                    "const http = require('http');\n"
                    "// POST /api/images/generate via openai\n"
                    "const OPENROUTER_API_BASE_URL = 'https://openrouter.ai/api/v1';\n"
                    "async function openrouterImages(){ return fetch(OPENROUTER_API_BASE_URL + '/images', { method: 'POST', body: JSON.stringify({ input_references: [] }) }); }\n"
                    "function setupError(){ throw new Error('PROVIDER_NOT_CONFIGURED: provider is not configured'); }\n",
                    encoding="utf-8",
                )
                last_message = run_dir / "codex" / "last_message_fix.json"
                last_message.write_text(
                    json.dumps(
                        {
                            "summary": "fix slice added provider_not_configured error path",
                            "files_changed": [str((app_dir / "server.js").relative_to(worktree))],
                            "tests_run": [],
                            "risk_events": [],
                            "blockers": [],
                            "next_action": "review",
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "ok\n", "")

            executor._run_process = fake_run_process  # type: ignore[assignment]
            first_eval = {
                "enabled": True,
                "blocking_events": ["benchmark_parity_missing:provider_setup_error"],
            }
            result = executor._maybe_run_benchmark_fix_slice(
                context=ctx,
                bundle=bundle,
                worktree_dir=worktree,
                previous_record={"exit_code": 0, "summary": "first round done"},
                first_evaluation=first_eval,
            )
            self.assertTrue(result["attempted"])
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["before_missing"], ["provider_setup_error"])
            self.assertEqual(result["after_missing"], [])
            self.assertIn("provider_setup_error", result["fix_record"]["remediated_capabilities"])
            prompt_path = run_dir / "codex" / "fix_slice_prompt.md"
            self.assertTrue(prompt_path.exists())
            prompt_text = prompt_path.read_text(encoding="utf-8")
            self.assertIn("Benchmark Fix Slice", prompt_text)
            self.assertIn("provider_setup_error", prompt_text)
            agqs = json.loads((run_dir / "agqs_score.json").read_text(encoding="utf-8"))
            self.assertEqual(agqs["hard_gate_status"], "passed")

    def test_fails_when_second_round_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            run_dir, worktree, contract = _make_run_dir(tmp)
            app_dir = worktree / contract["generated_app_dir"]
            _write_app_files(app_dir)

            executor = _make_executor(run_dir, tmp)
            bundle = executor.write_prompt_bundle("coder", _make_context(run_dir, tmp))
            ctx = _make_context(run_dir, tmp)

            def fake_run_process(command, prompt_text, cwd, stdout_path, stderr_path):
                return subprocess.CompletedProcess(command, 2, "", "boom\n")

            executor._run_process = fake_run_process  # type: ignore[assignment]
            first_eval = {
                "enabled": True,
                "blocking_events": ["benchmark_parity_missing:provider_setup_error"],
            }
            result = executor._maybe_run_benchmark_fix_slice(
                context=ctx,
                bundle=bundle,
                worktree_dir=worktree,
                previous_record={"exit_code": 0, "summary": "first round done"},
                first_evaluation=first_eval,
            )
            self.assertTrue(result["attempted"])
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["reason"].startswith("codex_exit:") or result["reason"].startswith("response_invalid"))

    def test_runtime_smoke_failure_fix_prompt_includes_verification_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            run_dir, worktree, contract = _make_run_dir(tmp)
            app_dir = worktree / contract["generated_app_dir"]
            _write_app_files(app_dir)
            codex_dir = run_dir / "codex"
            codex_dir.mkdir(exist_ok=True)
            (codex_dir / "app_runtime_verify_1_stdout.log").write_text("booting app\n", encoding="utf-8")
            (codex_dir / "app_runtime_verify_1_stderr.log").write_text(
                "ReferenceError: Cannot access 'state' before initialization\n",
                encoding="utf-8",
            )
            (codex_dir / "app_runtime_verification.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "failed",
                        "commands": [
                            {
                                "command": "node generated_apps/dingdang-main-image-agent/runtime_smoke.js",
                                "exit_code": 1,
                                "stdout_path": "codex/app_runtime_verify_1_stdout.log",
                                "stderr_path": "codex/app_runtime_verify_1_stderr.log",
                            }
                        ],
                        "blocking_events": [
                            "app_runtime_verification_failed:node generated_apps/dingdang-main-image-agent/runtime_smoke.js:1"
                        ],
                    }
                ),
                encoding="utf-8",
            )

            executor = _make_executor(run_dir, tmp)
            bundle = executor.write_prompt_bundle("coder", _make_context(run_dir, tmp))
            ctx = _make_context(run_dir, tmp)
            captured: dict[str, str] = {}

            def fake_run_process(command, prompt_text, cwd, stdout_path, stderr_path):
                captured["prompt"] = prompt_text
                return subprocess.CompletedProcess(command, 2, "", "boom\n")

            executor._run_process = fake_run_process  # type: ignore[assignment]
            result = executor._maybe_run_benchmark_fix_slice(
                context=ctx,
                bundle=bundle,
                worktree_dir=worktree,
                previous_record={"exit_code": 0, "summary": "first round done"},
                first_evaluation={
                    "enabled": True,
                    "blocking_events": [
                        "app_runtime_verification_failed:node generated_apps/dingdang-main-image-agent/runtime_smoke.js:1"
                    ],
                },
            )
            prompt_text = captured["prompt"]
            self.assertTrue(result["attempted"])
            self.assertEqual(result["before_missing"], ["runtime_startup_smoke"])
            self.assertIn("runtime_startup_smoke", prompt_text)
            self.assertIn("node generated_apps/dingdang-main-image-agent/runtime_smoke.js", prompt_text)
            self.assertIn("ReferenceError: Cannot access 'state' before initialization", prompt_text)
            self.assertIn("booting app", prompt_text)

    def test_openrouter_protocol_failure_fix_prompt_is_specific(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            run_dir, worktree, contract = _make_run_dir(tmp)
            app_dir = worktree / contract["generated_app_dir"]
            _write_app_files(app_dir)

            executor = _make_executor(run_dir, tmp)
            bundle = executor.write_prompt_bundle("coder", _make_context(run_dir, tmp))
            ctx = _make_context(run_dir, tmp)
            captured: dict[str, str] = {}

            def fake_run_process(command, prompt_text, cwd, stdout_path, stderr_path):
                captured["prompt"] = prompt_text
                return subprocess.CompletedProcess(command, 2, "", "boom\n")

            executor._run_process = fake_run_process  # type: ignore[assignment]
            result = executor._maybe_run_benchmark_fix_slice(
                context=ctx,
                bundle=bundle,
                worktree_dir=worktree,
                previous_record={"exit_code": 0, "summary": "first round done"},
                first_evaluation={
                    "enabled": True,
                    "blocking_events": ["benchmark_parity_missing:openrouter_images_endpoint"],
                },
            )
            prompt_text = captured["prompt"]
            self.assertTrue(result["attempted"])
            self.assertEqual(result["before_missing"], ["openrouter_images_endpoint"])
            self.assertIn("https://openrouter.ai/api/v1/images", prompt_text)
            self.assertIn("input_references", prompt_text)
            self.assertIn("do not use chat/completions plus modalities", prompt_text)

    def test_local_iteration_fix_prompt_includes_business_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            run_dir, worktree, contract = _make_run_dir(tmp)
            app_dir = worktree / contract["generated_app_dir"]
            _write_app_files(app_dir)

            executor = _make_executor(run_dir, tmp)
            bundle = executor.write_prompt_bundle("coder", _make_context(run_dir, tmp))
            ctx = _make_context(run_dir, tmp)
            captured: dict[str, str] = {}

            def fake_run_process(command, prompt_text, cwd, stdout_path, stderr_path):
                captured["prompt"] = prompt_text
                return subprocess.CompletedProcess(command, 2, "", "boom\n")

            executor._run_process = fake_run_process  # type: ignore[assignment]
            result = executor._maybe_run_benchmark_fix_slice(
                context=ctx,
                bundle=bundle,
                worktree_dir=worktree,
                previous_record={"exit_code": 0, "summary": "first round done"},
                first_evaluation={
                    "enabled": True,
                    "blocking_events": ["benchmark_parity_missing:local_iteration"],
                },
            )
            prompt_text = captured["prompt"]
            self.assertTrue(result["attempted"])
            self.assertEqual(result["before_missing"], ["local_iteration"])
            self.assertIn("第 X 张", prompt_text)
            self.assertIn("第 Y 层", prompt_text)
            self.assertIn("重新生成", prompt_text)


if __name__ == "__main__":
    unittest.main()
