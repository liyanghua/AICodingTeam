"""Tests for the app_generation Agent Bridge providers."""

import json
import tempfile
import unittest
from pathlib import Path

from growth_dev.team import agent_bridge


def _write_env(root: Path, contents: str) -> None:
    (root / ".env").write_text(contents, encoding="utf-8")


_NODE_CONTEXT = {
    "node_id": "planning_tdd",
    "node_title": "规划与验收",
    "node_summary": "生成验收标准、coverage matrix、TDD 计划和 slices。",
    "run_id": "app-generation-workbench",
    "selected_variant": "codex",
    "comparison_group_id": "cmp-demo",
    "context_revision": "sha256:demo",
    "app_slug": "todo-prototype",
    "inputs": [
        {
            "path": "requirements/normalized_prd.md",
            "title": "标准化 PRD",
            "status": "ready",
            "summary": "包含目标、范围、状态和假设。",
            "content_hash": "sha256:input",
        }
    ],
    "outputs": [
        {
            "path": "slices/slice_001.yaml",
            "title": "第一个实现切片",
            "status": "ready",
            "summary": "覆盖移动端空状态和本地保存验收。",
            "content_hash": "sha256:output",
        }
    ],
    "risks": [],
}


class CodexProviderTests(unittest.TestCase):
    def test_status_is_ready_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            status = agent_bridge.provider_status("codex", repo_root=root)
        self.assertEqual(status["provider"], "codex")
        self.assertEqual(status["status"], "ready")
        self.assertFalse(status["llm_configured"])
        self.assertIn("compare", "".join(status["capabilities"]) + "compare")

    def test_status_reports_llm_configured_when_env_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_env(
                root,
                "aicodemirror_key=sk-test-abcdef123456\naicodemirror_base_url=https://example.test/api\n",
            )
            status = agent_bridge.provider_status("codex", repo_root=root)
        self.assertEqual(status["status"], "ready")
        self.assertTrue(status["llm_configured"])

    def test_send_message_falls_back_to_deterministic_baseline_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=_NODE_CONTEXT,
                mode="compare",
                message="对比 rule 和 codex。",
                repo_root=root,
            )
        self.assertEqual(response["status"], "completed")
        self.assertTrue(any(a["type"] == "compare_variants" for a in response["actions"]))
        self.assertEqual(response["usage"]["total_tokens"], "unknown")
        self.assertEqual(response["usage"]["usage_source"], "deterministic_baseline")
        self.assertEqual(response["risk_events"], [])

    def test_send_message_uses_interaction_context_for_artifact_actions(self) -> None:
        interaction_context = {
            "context_revision": "sha256:demo",
            "focus": {
                "card": "artifact_preview",
                "artifact_ref": "slices/slice_001.yaml",
                "selected_text": "empty state",
                "view_mode": "artifact_preview",
            },
            "allowed_operations": ["explain", "read_artifact", "suggest_artifact_regeneration"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=_NODE_CONTEXT,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="看看这个中间产物是否需要重跑",
                repo_root=root,
            )
        action_types = [action["type"] for action in response["actions"]]
        self.assertIn("read_artifact", action_types)
        self.assertIn("suggest_artifact_regeneration", action_types)
        read_action = next(action for action in response["actions"] if action["type"] == "read_artifact")
        self.assertEqual(read_action["target_artifact"], "slices/slice_001.yaml")
        self.assertFalse(read_action["requires_confirmation"])
        rerun_action = next(action for action in response["actions"] if action["type"] == "suggest_artifact_regeneration")
        self.assertTrue(rerun_action["requires_confirmation"])

    def test_canvas_selection_routes_to_object_actions_and_preserves_source_object(self) -> None:
        interaction_context = {
            "context_revision": "sha256:demo",
            "focus": {"card": "canvas_object", "view_mode": "canvas_object_detail"},
            "canvas_selection": {
                "selection_type": "canvas_object",
                "selection_id": "capability:image_generation.single",
                "object_type": "capability",
                "title": "单张图片生成",
                "status": "needs_attention",
                "business_node": "验证业务能力",
                "business_node_id": "capability_verification",
                "allowed_actions": ["explain_object", "verify_capability", "repair_generated_app"],
            },
            "allowed_operations": ["explain_object", "verify_capability", "repair_generated_app", "delegate_code_repair"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=_NODE_CONTEXT,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="解释这个能力为什么需要关注",
                repo_root=Path(temp_dir),
            )
            verify_response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=_NODE_CONTEXT,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="验证一下这个能力",
                repo_root=Path(temp_dir),
            )

        self.assertEqual(response["resolved_intent"], "explain_object")
        explain_action = response["actions"][0]
        self.assertEqual(explain_action["type"], "explain_object")
        self.assertEqual(explain_action["source_object_id"], "capability:image_generation.single")
        self.assertEqual(explain_action["source_object_title"], "单张图片生成")
        self.assertEqual(verify_response["resolved_intent"], "verify_capability")
        verify_action = verify_response["actions"][0]
        self.assertEqual(verify_action["type"], "verify_capability")
        self.assertEqual(verify_action["source_object_id"], "capability:image_generation.single")

    def test_canvas_repair_action_overrides_edit_mode_to_delegate_repair(self) -> None:
        interaction_context = {
            "context_revision": "sha256:demo",
            "focus": {"card": "canvas_object", "view_mode": "canvas_object_detail"},
            "canvas_selection": {
                "selection_type": "canvas_object",
                "selection_id": "capability:image_generation.single",
                "object_type": "capability",
                "title": "单张图片生成",
                "status": "needs_attention",
                "business_node": "验证业务能力",
                "business_node_id": "capability_verification",
                "allowed_actions": ["explain_object", "verify_capability", "repair_generated_app"],
            },
            "allowed_operations": ["repair_generated_app", "delegate_code_repair", "suggest_input_patch"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=_NODE_CONTEXT,
                interaction_context=interaction_context,
                intent="edit",
                mode="edit",
                message="请基于业务对象「单张图片生成」诊断并修复生成应用中的问题。",
                repo_root=Path(temp_dir),
            )

        self.assertEqual(response["resolved_intent"], "delegate_code_repair")
        action_types = [action["type"] for action in response["actions"]]
        self.assertIn("delegate_code_repair", action_types)
        self.assertNotIn("suggest_input_patch", action_types)

    def test_flow_step_selection_routes_to_step_explanation_actions(self) -> None:
        interaction_context = {
            "context_revision": "sha256:demo",
            "focus": {"card": "flow_step", "view_mode": "business_step_detail"},
            "canvas_selection": {
                "selection_type": "flow_step",
                "step_id": "prototype_generation",
                "step_type": "business",
                "title": "生成应用原型",
                "status": "generated",
                "runtime_nodes": ["implementation"],
                "input_summary": ["应用契约", "TDD 计划"],
                "process_summary": ["Code Agent 生成本地应用"],
                "output_summary": ["生成应用代码", "实现 diff"],
                "evidence_refs": ["codex/diff.patch"],
                "allowed_actions": ["explain_step", "explain_step_io", "inspect_evidence", "rerun_step", "delegate_code_repair"],
            },
            "allowed_operations": ["explain_step", "explain_step_io", "inspect_evidence", "rerun_step", "delegate_code_repair"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=_NODE_CONTEXT,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="这一步在干什么？",
                repo_root=Path(temp_dir),
            )
            io_response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=_NODE_CONTEXT,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="输入输出是什么？",
                repo_root=Path(temp_dir),
            )

        self.assertEqual(response["resolved_intent"], "explain_step")
        self.assertEqual(response["actions"][0]["type"], "explain_step")
        self.assertEqual(response["actions"][0]["source_step_id"], "prototype_generation")
        self.assertEqual(io_response["resolved_intent"], "explain_step_io")
        self.assertEqual(io_response["actions"][0]["type"], "explain_step_io")
        prompt_context = agent_bridge._agent_prompt_context(_NODE_CONTEXT, interaction_context, "explain_step")
        self.assertEqual(prompt_context["canvas_selection"]["selection_type"], "flow_step")
        self.assertEqual(prompt_context["canvas_selection"]["title"], "生成应用原型")
        self.assertIn("应用契约", prompt_context["canvas_selection"]["input_summary"])

    def test_flow_step_selection_rerun_maps_to_runtime_node(self) -> None:
        interaction_context = {
            "context_revision": "sha256:demo",
            "focus": {"card": "flow_step", "view_mode": "business_step_detail"},
            "canvas_selection": {
                "selection_type": "flow_step",
                "step_id": "prototype_generation",
                "step_type": "business",
                "title": "生成应用原型",
                "status": "generated",
                "runtime_nodes": ["implementation"],
                "allowed_actions": ["explain_step", "rerun_step"],
            },
            "allowed_operations": ["explain_step", "rerun_step"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=_NODE_CONTEXT,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="重新跑这一步",
                repo_root=Path(temp_dir),
            )

        self.assertEqual(response["resolved_intent"], "rerun_step")
        action = response["actions"][0]
        self.assertEqual(action["type"], "rerun_step")
        self.assertEqual(action["rerun_from_node"], "implementation")
        self.assertEqual(action["source_step_title"], "生成应用原型")

    def test_app_preview_flow_step_repair_prefers_delegate_code_repair(self) -> None:
        interaction_context = {
            "context_revision": "sha256:demo",
            "focus": {"card": "flow_step", "view_mode": "business_step_detail"},
            "canvas_selection": {
                "selection_type": "flow_step",
                "step_id": "app_preview",
                "step_type": "ui",
                "title": "可预览应用",
                "status": "running",
                "runtime_nodes": [],
                "allowed_actions": ["inspect_evidence", "delegate_code_repair"],
            },
            "allowed_operations": ["inspect_evidence", "delegate_code_repair"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=_NODE_CONTEXT,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="生成单张图时报 gpt-image-1 not configured，请只修复当前预览问题",
                repo_root=Path(temp_dir),
            )

        self.assertEqual(response["resolved_intent"], "delegate_code_repair")
        action = response["actions"][0]
        self.assertEqual(action["type"], "delegate_code_repair")
        self.assertEqual(action["target"], "published_app")

    def test_auto_intent_reruns_node_from_natural_language(self) -> None:
        interaction_context = {
            "context_revision": "sha256:demo",
            "focus": {"card": "node_summary", "view_mode": "node_detail"},
            "allowed_operations": ["explain", "rerun_from_node", "ask_clarification"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=_NODE_CONTEXT,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="重新跑这个节点，补充移动端空状态",
                repo_root=Path(temp_dir),
            )
        self.assertEqual(response.get("resolved_intent"), "rerun_from_node")
        action_types = [action["type"] for action in response["actions"]]
        self.assertIn("rerun_from_node", action_types)
        rerun_action = next(action for action in response["actions"] if action["type"] == "rerun_from_node")
        self.assertTrue(rerun_action["requires_confirmation"])
        self.assertEqual(rerun_action["rerun_from_node"], "planning_tdd")

    def test_app_preview_repair_intent_generates_patch_app_from_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "runs" / "run-1" / "generated_apps" / "todo-prototype"
            app_dir.mkdir(parents=True)
            (app_dir / "server.js").write_text(
                "const model = process.env.OPENAI_IMAGE_MODEL || 'gpt-image-1';\n",
                encoding="utf-8",
            )
            node_context = {**_NODE_CONTEXT, "run_id": "run-1", "run_dir": str(root / "runs" / "run-1")}
            interaction_context = {
                "focus": {"card": "app_preview", "view_mode": "app_preview"},
                "allowed_operations": ["patch_app", "diagnose_app_bug"],
            }
            response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=node_context,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="生成单张图时报 gpt-image-1 not configured，把默认模型换成 gpt-5.4-image-2",
                repo_root=root,
            )

        self.assertEqual(response.get("resolved_intent"), "patch_app")
        patch_action = next(action for action in response["actions"] if action["type"] == "patch_app")
        self.assertEqual(patch_action["source"], "provider_text_fallback")
        self.assertEqual(patch_action["patches"][0]["target_path"], "generated_apps/todo-prototype/server.js")
        self.assertIn("openai/gpt-5.4-image-2", patch_action["patches"][0]["new_content"])

    def test_app_repair_intent_injects_patch_targets_outside_app_preview_focus(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "runs" / "run-1" / "generated_apps" / "todo-prototype"
            app_dir.mkdir(parents=True)
            (app_dir / "server.js").write_text(
                "const model = process.env.OPENAI_IMAGE_MODEL || 'gpt-image-1';\n",
                encoding="utf-8",
            )
            node_context = {**_NODE_CONTEXT, "run_id": "run-1", "run_dir": str(root / "runs" / "run-1")}
            interaction_context = {
                "focus": {"card": "node_summary", "view_mode": "node_detail"},
                "allowed_operations": ["patch_app", "diagnose_app_bug", "suggest_input_patch"],
            }
            resolved = agent_bridge._resolve_intent(
                node_context,
                "explain",
                "生成单张图时报 gpt-image-1 not configured，把默认模型换成 gpt-5.4-image-2",
                interaction_context,
                "auto",
            )
            context = agent_bridge._agent_prompt_context(node_context, interaction_context, resolved)

        self.assertEqual(resolved, "patch_app")
        self.assertIn("app_patch_targets", context)
        self.assertEqual(context["app_patch_targets"][0]["path"], "generated_apps/todo-prototype/server.js")
        self.assertTrue(context["app_patch_targets"][0]["agent_edit_anchors"])

    def test_app_preview_repair_without_unique_anchor_returns_diagnose(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "runs" / "run-1" / "generated_apps" / "todo-prototype"
            app_dir.mkdir(parents=True)
            (app_dir / "server.js").write_text("const model = process.env.OPENROUTER_IMAGE_MODEL;\n", encoding="utf-8")
            node_context = {**_NODE_CONTEXT, "run_id": "run-1", "run_dir": str(root / "runs" / "run-1")}
            interaction_context = {
                "focus": {"card": "app_preview", "view_mode": "app_preview"},
                "allowed_operations": ["patch_app", "diagnose_app_bug"],
            }
            response = agent_bridge.send_agent_message(
                provider_id="codex",
                node_context=node_context,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="生成单张图时报 gpt-image-1 not configured，把默认模型换成 gpt-5.4-image-2",
                repo_root=root,
            )

        self.assertEqual(response.get("resolved_intent"), "patch_app")
        self.assertTrue(any(action["type"] == "diagnose_app_bug" for action in response["actions"]))
        self.assertFalse(any(action["type"] == "patch_app" and not action.get("patches") for action in response["actions"]))

    def test_invalid_patch_app_from_provider_text_is_replaced_by_fallback_patchset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_env(root, "aicodemirror_key=sk-test-abcdef123456\naicodemirror_base_url=https://example.test/api\n")
            app_dir = root / "runs" / "run-1" / "generated_apps" / "todo-prototype"
            app_dir.mkdir(parents=True)
            (app_dir / "server.js").write_text(
                "const model = process.env.OPENAI_IMAGE_MODEL || 'gpt-image-1';\n",
                encoding="utf-8",
            )
            node_context = {**_NODE_CONTEXT, "run_id": "run-1", "run_dir": str(root / "runs" / "run-1")}
            interaction_context = {
                "focus": {"card": "node_summary", "view_mode": "node_detail"},
                "allowed_operations": ["patch_app", "diagnose_app_bug", "suggest_input_patch"],
            }

            def fake_http(_url: str, _headers: dict[str, str], _body: bytes) -> dict[str, object]:
                content = (
                    "建议只修改当前已发布应用，把 gpt-image-1 改为 gpt-5.4-image-2。\n"
                    "```json\n"
                    + json.dumps(
                        {
                            "actions": [
                                {"type": "diagnose_app_bug", "summary": "模型配置未读取 OPENROUTER_IMAGE_MODEL", "requires_confirmation": False},
                                {"type": "patch_app", "summary": "修改已发布应用", "requires_confirmation": True},
                            ]
                        }
                    )
                    + "\n```"
                )
                return {"choices": [{"message": {"content": content}}], "usage": {}}

            provider = agent_bridge.CodexProvider(http_caller=fake_http)
            response = provider.send_message(
                node_context=node_context,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="生成单张图时报 gpt-image-1 not configured。我的 .env 里配置的是 OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2。",
                repo_root=root,
            )

        self.assertEqual(response["resolved_intent"], "patch_app")
        self.assertTrue(any(action["type"] == "diagnose_app_bug" for action in response["actions"]))
        patch_action = next(action for action in response["actions"] if action["type"] == "patch_app")
        self.assertTrue(patch_action.get("patches"))
        self.assertEqual(patch_action["patches"][0]["target_path"], "generated_apps/todo-prototype/server.js")
        self.assertIn("openai/gpt-5.4-image-2", patch_action["patches"][0]["new_content"])

    def test_prompt_context_injects_app_patch_targets_not_full_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "runs" / "run-1" / "generated_apps" / "todo-prototype"
            app_dir.mkdir(parents=True)
            (app_dir / "server.js").write_text(
                "const model = process.env.OPENAI_IMAGE_MODEL || 'gpt-image-1';\nconst other = 'secret-free';\n",
                encoding="utf-8",
            )
            node_context = {**_NODE_CONTEXT, "run_id": "run-1", "run_dir": str(root / "runs" / "run-1")}
            context = agent_bridge._agent_prompt_context(
                node_context,
                {"focus": {"card": "app_preview", "view_mode": "app_preview"}},
                "patch_app",
            )

        self.assertIn("app_patch_targets", context)
        target = context["app_patch_targets"][0]
        self.assertEqual(target["path"], "generated_apps/todo-prototype/server.js")
        self.assertIn("content_hash", target)
        self.assertIn("agent_edit_anchors", target)
        self.assertNotIn("content_head", target)

    def test_pi_protocol_and_parser_accept_patchset_actions(self) -> None:
        self.assertIn("patch_app", agent_bridge.PI_ALLOWED_ACTION_TYPES)
        self.assertIn("rollback_patch", agent_bridge.PI_ALLOWED_ACTION_TYPES)
        text = (
            "建议修复。\n```json\n"
            + json.dumps(
                {
                    "actions": [
                        {
                            "type": "patch_app",
                            "patches": [
                                {
                                    "target_path": "generated_apps/todo-prototype/server.js",
                                    "edit_kind": "replace_text",
                                    "old_content": "old",
                                    "new_content": "new",
                                }
                            ],
                            "requires_confirmation": True,
                        }
                    ]
                }
            )
            + "\n```"
        )
        _cleaned, actions = agent_bridge._parse_trailing_actions(text, context_revision="rev1")
        self.assertIsNotNone(actions)
        self.assertEqual(actions[0]["type"], "patch_app")  # type: ignore[index]
        self.assertEqual(actions[0]["context_revision"], "rev1")  # type: ignore[index]

    def test_llm_prompt_includes_business_context_for_inputs_question(self) -> None:
        captured: dict[str, object] = {}

        def fake_http(url: str, headers: dict[str, str], body: bytes) -> dict[str, object]:
            import json

            captured["payload"] = json.loads(body.decode("utf-8"))
            return {"choices": [{"message": {"content": "输入包含标准化 PRD。"}}], "usage": {}}

        provider = agent_bridge.CodexProvider(http_caller=fake_http)
        interaction_context = {
            "context_revision": "sha256:demo",
            "focus": {"card": "inputs", "view_mode": "node_detail"},
            "allowed_operations": ["explain", "read_artifact", "ask_clarification"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_env(
                root,
                "aicodemirror_key=sk-test-abcdef123456\naicodemirror_base_url=https://example.test/api\n",
            )
            response = provider.send_message(
                node_context=_NODE_CONTEXT,
                interaction_context=interaction_context,
                intent="auto",
                mode="explain",
                message="输入是什么？",
                repo_root=root,
            )
        self.assertEqual(response.get("resolved_intent"), "explain_inputs")
        messages = captured["payload"]["messages"]  # type: ignore[index]
        user_prompt = messages[1]["content"]
        self.assertIn("规划与验收", user_prompt)
        self.assertIn("标准化 PRD", user_prompt)
        self.assertIn("requirements/normalized_prd.md", user_prompt)
        self.assertIn("包含目标、范围、状态和假设", user_prompt)

    def test_send_message_uses_real_llm_when_credentials_present(self) -> None:
        captured: dict[str, object] = {}

        def fake_http(url: str, headers: dict[str, str], body: bytes) -> dict[str, object]:
            captured["url"] = url
            captured["auth"] = headers.get("Authorization", "")
            return {
                "choices": [{"message": {"role": "assistant", "content": "Codex 真实回复：rule 更稳定。"}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 48, "total_tokens": 168},
            }

        provider = agent_bridge.CodexProvider(http_caller=fake_http)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_env(
                root,
                "aicodemirror_key=sk-test-abcdef123456\naicodemirror_base_url=https://example.test/api\n",
            )
            response = provider.send_message(
                node_context=_NODE_CONTEXT,
                mode="compare",
                message="对比 rule 和 codex。",
                repo_root=root,
            )
        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["message"], "Codex 真实回复：rule 更稳定。")
        self.assertEqual(response["usage"]["total_tokens"], 168)
        self.assertEqual(response["usage"]["usage_source"], "provider_api")
        self.assertTrue(any(a["type"] == "compare_variants" for a in response["actions"]))
        self.assertTrue(str(captured["url"]).endswith("/chat/completions"))
        self.assertIn("Bearer", str(captured["auth"]))

    def test_send_message_recovers_from_llm_error_with_baseline_and_risk_event(self) -> None:
        def failing_http(url: str, headers: dict[str, str], body: bytes) -> dict[str, object]:
            raise OSError("connection refused")

        provider = agent_bridge.CodexProvider(http_caller=failing_http)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_env(
                root,
                "aicodemirror_key=sk-test-abcdef123456\naicodemirror_base_url=https://example.test/api\n",
            )
            response = provider.send_message(
                node_context=_NODE_CONTEXT,
                mode="explain",
                message="解释当前节点。",
                repo_root=root,
            )
        self.assertEqual(response["status"], "completed")
        self.assertTrue(any(a["type"] == "explain_node" for a in response["actions"]))
        self.assertEqual(response["usage"]["usage_source"], "llm_unavailable")
        self.assertTrue(any(e["id"] == "codex_llm_unavailable" for e in response["risk_events"]))

    def test_send_message_response_does_not_leak_api_key(self) -> None:
        def echo_key_http(url: str, headers: dict[str, str], body: bytes) -> dict[str, object]:
            return {"choices": [{"message": {"content": "key is sk-test-abcdef123456 leaked"}}]}

        provider = agent_bridge.CodexProvider(http_caller=echo_key_http)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_env(
                root,
                "aicodemirror_key=sk-test-abcdef123456\naicodemirror_base_url=https://example.test/api\n",
            )
            response = provider.send_message(
                node_context=_NODE_CONTEXT,
                mode="explain",
                message="解释当前节点。",
                repo_root=root,
            )
        self.assertNotIn("sk-test-abcdef123456", agent_bridge._redact_text(response["message"]))


class PiAgentProviderTests(unittest.TestCase):
    def test_status_is_not_configured_when_pi_not_on_path(self) -> None:
        from growth_dev.team import pi_rpc

        status = pi_rpc.pi_status(which=lambda _name: None)
        self.assertEqual(status["provider"], "pi_agent")
        self.assertEqual(status["status"], "not_configured")
        self.assertIn("PI-Agent", status["message"])
        self.assertEqual(status["capabilities"], [])

    def test_status_is_ready_when_pi_on_path(self) -> None:
        from growth_dev.team import pi_rpc

        status = pi_rpc.pi_status(which=lambda _name: "/opt/homebrew/bin/pi")
        self.assertEqual(status["status"], "ready")
        self.assertIn("/opt/homebrew/bin/pi", status["message"])
        self.assertIn("stream", status["capabilities"])
        self.assertIn("tool_calls", status["capabilities"])


class GenericLlmProviderTests(unittest.TestCase):
    def test_status_is_not_configured_by_default(self) -> None:
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as temp_dir:
                status = agent_bridge.provider_status("llm", repo_root=Path(temp_dir))
        self.assertEqual(status["provider"], "llm")
        self.assertEqual(status["status"], "not_configured")
        self.assertIn("LLM", status["message"])
        self.assertEqual(status["capabilities"], [])


if __name__ == "__main__":
    unittest.main()
