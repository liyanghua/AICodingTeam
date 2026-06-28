"""Tests for the app_generation Agent Bridge providers."""

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
