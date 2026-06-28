"""Tests for PiAgentProvider real subprocess (pi --mode rpc) integration.

Uses an in-process FakeProcess + injected subprocess_launcher to drive the
PiRpcClient end-to-end without depending on a system-installed pi binary.

All fixtures use the REAL pi wire protocol (AgentSessionEvent union):
- assistant text  -> {"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":...}}  (no id)
- thinking        -> {"type":"message_update","assistantMessageEvent":{"type":"thinking_delta","delta":...}}  (no id)
- tool start/end  -> {"type":"tool_execution_start|end", "toolCallId":..., ...}  (no id)
- per-turn marker -> {"type":"turn_end", ...}  (no id, NOT terminal)
- real terminal   -> {"type":"agent_end","messages":[{"usage":...,"stopReason":...}],"willRetry":...}  (no id)
- prompt ack      -> {"type":"response","id":<pid>,"success":...}  (preflight-ok, NOT terminal)

Termination follows model A: only the session-level agent_end (or an error)
ends a turn; the response ack and turn_end never terminate.
"""

import json
import os
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Optional

from growth_dev.team import agent_bridge, pi_rpc


# --------------------------------------------------------------------------- #
# Real pi protocol packet builders
# --------------------------------------------------------------------------- #
def _text_delta(text: str, content_index: int = 0) -> dict[str, Any]:
    return {
        "type": "message_update",
        "assistantMessageEvent": {
            "type": "text_delta",
            "delta": text,
            "contentIndex": content_index,
        },
    }


def _thinking_delta(text: str, content_index: int = 0) -> dict[str, Any]:
    return {
        "type": "message_update",
        "assistantMessageEvent": {
            "type": "thinking_delta",
            "delta": text,
            "contentIndex": content_index,
        },
    }


def _tool_start(tool_call_id: str, name: str, args: Any) -> dict[str, Any]:
    return {
        "type": "tool_execution_start",
        "toolCallId": tool_call_id,
        "toolName": name,
        "args": args,
    }


def _tool_end(tool_call_id: str, result: Any, is_error: bool = False) -> dict[str, Any]:
    return {
        "type": "tool_execution_end",
        "toolCallId": tool_call_id,
        "toolName": "",
        "result": result,
        "isError": is_error,
    }


def _agent_end(
    usage: Optional[dict[str, Any]] = None,
    stop_reason: str = "end_turn",
    will_retry: bool = False,
    error_message: Optional[str] = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"stopReason": stop_reason}
    if usage:
        message["usage"] = usage
    if error_message:
        message["errorMessage"] = error_message
    return {"type": "agent_end", "messages": [message], "willRetry": will_retry}


class _FakeStdin:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.closed = False

    def write(self, data: str) -> int:
        self.lines.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeStdout:
    """Blocking line iterator backed by a queue. send_line() pushes data."""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()

    def __iter__(self):
        return self

    def __next__(self) -> str:
        item = self._q.get()
        if item is None:
            raise StopIteration
        return item

    def send_line(self, line: str) -> None:
        if not line.endswith("\n"):
            line += "\n"
        self._q.put(line)

    def close_stream(self) -> None:
        self._q.put(None)


class _FakeStderr:
    def __iter__(self):
        return iter(())


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout()
        self.stderr = _FakeStderr()
        self._poll: int | None = None
        self.terminate_called = False
        self.kill_called = False

    def poll(self) -> int | None:
        return self._poll

    def terminate(self) -> None:
        self.terminate_called = True
        self._poll = 0

    def kill(self) -> None:
        self.kill_called = True
        self._poll = -9

    def wait(self, timeout: float | None = None) -> int:
        return self._poll if self._poll is not None else 0

    # Helpers for tests.
    def emit(self, packet: dict[str, Any]) -> None:
        self.stdout.send_line(json.dumps(packet))

    def prompt_id(self) -> str:
        return json.loads(self.stdin.lines[0])["id"]

    def close_stdout(self) -> None:
        self.stdout.close_stream()


_NODE_CONTEXT = {
    "node_id": "planning_tdd",
    "node_title": "规划与验收",
    "node_summary": "生成验收标准、coverage matrix、TDD 计划和 slices。",
    "run_id": "pi-rpc-run",
    "selected_variant": "codex",
    "app_slug": "demo",
    "inputs": [
        {
            "path": "requirements/normalized_prd.md",
            "title": "标准化 PRD",
            "status": "ready",
            "summary": "包含目标、范围、状态和假设。",
        }
    ],
    "outputs": [
        {
            "path": "planning/tdd_plan.json",
            "title": "TDD 计划",
            "status": "ready",
            "summary": "列出验收切片和验证命令。",
        }
    ],
    "risks": [],
    "context_revision": "sha256:test",
}


class PiAgentProviderRpcTests(unittest.TestCase):
    def setUp(self) -> None:
        agent_bridge.reset_provider_singletons()

    def tearDown(self) -> None:
        agent_bridge.reset_provider_singletons()

    def _make_provider_with_fake(
        self, fake_proc: FakeProcess
    ) -> agent_bridge.PiAgentProvider:
        def launcher(cmd, env, cwd):
            return fake_proc

        def ready_probe(**_kwargs):
            return {
                "provider": "pi_agent",
                "status": "ready",
                "message": "fake pi ready",
                "capabilities": ["chat", "tool_calls", "stream"],
            }

        return agent_bridge.PiAgentProvider(
            subprocess_launcher=launcher,
            status_probe=ready_probe,
        )

    def _run_stream(
        self, provider: agent_bridge.PiAgentProvider, **kwargs
    ) -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory() as temp_dir:
            kwargs.setdefault("repo_root", Path(temp_dir))
            kwargs.setdefault("node_context", _NODE_CONTEXT)
            kwargs.setdefault("mode", "explain")
            return list(provider.stream_message(**kwargs))

    # ------------------------------------------------------------------ status

    def test_status_ready_when_pi_on_path(self) -> None:
        status = pi_rpc.pi_status(which=lambda _name: "/fake/pi")
        self.assertEqual(status["status"], "ready")
        self.assertIn("/fake/pi", status["message"])
        self.assertIn("chat", status["capabilities"])

    def test_status_not_configured_when_pi_missing(self) -> None:
        status = pi_rpc.pi_status(which=lambda _name: None)
        self.assertEqual(status["status"], "not_configured")
        self.assertIn("PI-Agent", status["message"])

    # ------------------------------------------------------- answer streaming

    def test_stream_message_emits_message_delta_and_agent_end(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_text_delta("你好"))
            fake_proc.emit(_text_delta("，世界"))
            fake_proc.emit(
                _agent_end(
                    usage={"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}
                )
            )

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(provider, message="解释当前节点")

        types = [e["type"] for e in events]
        self.assertEqual(types[:2], ["message_delta", "message_delta"])
        self.assertEqual(types[-1], "agent_end")
        self.assertEqual(events[-1]["payload"]["usage"]["total_tokens"], 130)
        prompt_packet = json.loads(fake_proc.stdin.lines[0])
        self.assertEqual(prompt_packet["type"], "prompt")
        self.assertIn("planning_tdd", prompt_packet["message"])

    def test_stream_message_includes_interaction_context_and_agent_actions(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)
        interaction_context = {
            "context_revision": "sha256:test",
            "focus": {
                "card": "artifact_preview",
                "artifact_ref": "planning/tdd_plan.json",
                "selected_text": "mobile empty state",
                "view_mode": "artifact_preview",
            },
            "allowed_operations": ["explain", "read_artifact", "suggest_artifact_regeneration"],
        }

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_text_delta("看到了"))
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(
            provider,
            interaction_context=interaction_context,
            intent="auto",
            message="这个中间产物是否需要重跑？",
        )

        prompt_packet = json.loads(fake_proc.stdin.lines[0])
        self.assertIn("planning/tdd_plan.json", prompt_packet["message"])
        self.assertIn("mobile empty state", prompt_packet["message"])
        agent_end = events[-1]
        self.assertEqual(agent_end["type"], "agent_end")
        action_types = [action["type"] for action in agent_end["payload"]["actions"]]
        self.assertIn("read_artifact", action_types)
        self.assertIn("suggest_artifact_regeneration", action_types)

    def test_idless_text_delta_routes_to_active_prompt(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_text_delta("正式回答"))
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(provider, message="这个节点干啥？")

        types = [event["type"] for event in events]
        self.assertIn("message_delta", types)
        self.assertEqual(types.count("upstream_error"), 0)
        self.assertEqual(events[-1]["type"], "agent_end")
        delta = next(event for event in events if event["type"] == "message_delta")
        self.assertEqual(delta["payload"]["text"], "正式回答")

    def test_thinking_delta_is_not_rendered_as_answer(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_thinking_delta("内部推理", content_index=0))
            fake_proc.emit(_text_delta("给用户看的答案", content_index=1))
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        with tempfile.TemporaryDirectory() as temp_dir:
            response = provider.send_message(
                node_context=_NODE_CONTEXT,
                mode="explain",
                message="解释当前节点",
                repo_root=Path(temp_dir),
            )
        self.assertEqual(response["message"], "给用户看的答案")
        self.assertNotIn("内部推理", response["message"])

    # --------------------------------------------------------- tool execution

    def test_tool_execution_start_end_map_to_tool_call_result(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(
                _tool_start("tc-real", "read_file", {"path": "planning/tdd_plan.json"})
            )
            fake_proc.emit(_tool_end("tc-real", "ok", is_error=False))
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(provider, message="读一下产物")

        tool_call = next(event for event in events if event["type"] == "tool_call")
        tool_result = next(event for event in events if event["type"] == "tool_result")
        self.assertEqual(tool_call["payload"]["tool_call_id"], "tc-real")
        self.assertEqual(tool_call["payload"]["name"], "read_file")
        self.assertEqual(tool_result["payload"]["tool_call_id"], "tc-real")
        self.assertEqual(tool_result["payload"]["output"], "ok")
        self.assertFalse(tool_result["payload"]["is_error"])

    # -------------------------------------------------- termination model (A)

    def test_success_response_is_not_terminal_and_waits_for_agent_end(self) -> None:
        """response{success:true} is preflight-ok, not completion: must NOT close
        the stream. The terminal signal is the later agent_end."""
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            pid = fake_proc.prompt_id()
            fake_proc.emit(_text_delta("第一段"))
            fake_proc.emit({"type": "response", "id": pid, "success": True})
            fake_proc.emit(_text_delta("第二段"))
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(provider, message="hi")

        deltas = [e["payload"]["text"] for e in events if e["type"] == "message_delta"]
        self.assertEqual(deltas, ["第一段", "第二段"])
        self.assertEqual([e["type"] for e in events].count("upstream_error"), 0)
        self.assertEqual(events[-1]["type"], "agent_end")

    def test_turn_end_is_not_terminal(self) -> None:
        """turn_end fires once per turn in multi-turn tool loops; it must not end
        the stream early."""
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_text_delta("回合一"))
            fake_proc.emit({"type": "turn_end", "message": {}, "toolResults": []})
            fake_proc.emit(_text_delta("回合二"))
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(provider, message="hi")

        deltas = [e["payload"]["text"] for e in events if e["type"] == "message_delta"]
        self.assertEqual(deltas, ["回合一", "回合二"])
        self.assertEqual(events[-1]["type"], "agent_end")

    def test_agent_end_with_will_retry_is_not_terminal(self) -> None:
        """agent_end{willRetry:true} means the agent will retry; it must not close
        the stream. The next agent_end{willRetry:false} is the real terminal."""
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_text_delta("尝试一"))
            fake_proc.emit(_agent_end(stop_reason="error", will_retry=True))
            fake_proc.emit(_text_delta("尝试二"))
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(provider, message="hi")

        deltas = [e["payload"]["text"] for e in events if e["type"] == "message_delta"]
        self.assertEqual(deltas, ["尝试一", "尝试二"])
        self.assertEqual([e["type"] for e in events].count("agent_end"), 1)
        self.assertEqual(events[-1]["type"], "agent_end")

    def test_response_failure_surfaces_upstream_error(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            pid = fake_proc.prompt_id()
            fake_proc.emit(
                {
                    "type": "response",
                    "id": pid,
                    "success": False,
                    "error": "model unavailable",
                }
            )

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(provider, message="hi")

        types = [e["type"] for e in events]
        self.assertEqual(types.count("upstream_error"), 1)
        self.assertEqual(types[-1], "upstream_error")
        self.assertEqual(events[-1]["payload"]["phase"], "response_error")
        self.assertIn("model unavailable", events[-1]["payload"]["errorMessage"])

    def test_agent_end_error_surfaces_upstream_error(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_text_delta("partial"))
            fake_proc.emit(
                _agent_end(stop_reason="error", error_message="upstream 500")
            )

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(provider, message="hi")

        types = [e["type"] for e in events]
        self.assertEqual(types.count("upstream_error"), 1)
        self.assertEqual(types[-1], "upstream_error")
        self.assertEqual(events[-1]["payload"]["phase"], "agent_end_error")

    def test_stream_closed_without_agent_end_emits_upstream_error(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_text_delta("partial"))
            fake_proc.close_stdout()

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(provider, message="hi")

        types = [e["type"] for e in events]
        self.assertIn("message_delta", types)
        self.assertEqual(types.count("upstream_error"), 1)
        self.assertEqual(types[-1], "upstream_error")
        self.assertEqual(events[-1]["payload"]["phase"], "stream_closed")

    # ------------------------------------------------------------- redaction

    def test_stream_message_redacts_api_key_substrings(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_text_delta("key=sk-ant-abcdef1234567890 leaked"))
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        events = self._run_stream(provider, message="hi")

        delta_text = next(e for e in events if e["type"] == "message_delta")["payload"]["text"]
        self.assertNotIn("sk-ant-abcdef1234567890", delta_text)
        self.assertIn("redacted", delta_text)

    # ----------------------------------------------------------- send_message

    def test_send_message_folds_stream_into_agent_response(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            for chunk in ["这是", " pi", " 的回复"]:
                fake_proc.emit(_text_delta(chunk))
            fake_proc.emit(_tool_start("tc-x", "bash", {"command": "ls"}))
            fake_proc.emit(_tool_end("tc-x", "README.md", is_error=False))
            fake_proc.emit(
                _agent_end(
                    usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
                )
            )

        threading.Thread(target=producer, daemon=True).start()
        with tempfile.TemporaryDirectory() as temp_dir:
            response = provider.send_message(
                node_context=_NODE_CONTEXT,
                mode="explain",
                message="hi",
                repo_root=Path(temp_dir),
            )
        self.assertEqual(response["provider"], "pi_agent")
        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["message"], "这是 pi 的回复")
        self.assertEqual(len(response["tool_calls"]), 1)
        self.assertEqual(response["tool_calls"][0]["output"], "README.md")
        self.assertEqual(response["usage"]["total_tokens"], 30)
        self.assertEqual(response["usage"]["usage_source"], "pi_agent_end")

    # --------------------------------------------------------- lifecycle/env

    def test_subprocess_terminated_on_provider_close(self) -> None:
        fake_proc = FakeProcess()
        provider = self._make_provider_with_fake(fake_proc)

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        self._run_stream(provider, message="hi")
        self.assertFalse(fake_proc.terminate_called)
        provider._safe_close()
        self.assertTrue(fake_proc.terminate_called)
        self.assertTrue(fake_proc.stdin.closed)

    def test_load_pi_env_overrides_pulls_credentials_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / ".env").write_text(
                "aicodemirror_key=sk-ant-fromfile-001\n"
                "aicodemirror_base_url=https://example.test/api\n",
                encoding="utf-8",
            )
            env = pi_rpc.load_pi_env_overrides(repo_root, base_env={"PATH": "/usr/bin"})
        self.assertEqual(env["AICODEMIRROR_API_KEY"], "sk-ant-fromfile-001")
        self.assertEqual(env["AICODEMIRROR_BASE_URL"], "https://example.test/api")
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_env_file_credentials_reach_pi_subprocess(self) -> None:
        captured: dict[str, dict[str, str]] = {}
        fake_proc = FakeProcess()

        def launcher(cmd, env, cwd):
            captured["env"] = env
            return fake_proc

        def ready_probe(**_kwargs):
            return {
                "provider": "pi_agent",
                "status": "ready",
                "message": "fake pi ready",
                "capabilities": ["chat"],
            }

        provider = agent_bridge.PiAgentProvider(
            subprocess_launcher=launcher,
            status_probe=ready_probe,
        )

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / ".env").write_text(
                "AICODEMIRROR_API_KEY=sk-ant-wired-999\n", encoding="utf-8"
            )
            list(
                provider.stream_message(
                    node_context=_NODE_CONTEXT,
                    mode="explain",
                    message="hi",
                    repo_root=repo_root,
                )
            )
        self.assertEqual(captured["env"]["AICODEMIRROR_API_KEY"], "sk-ant-wired-999")

    def test_env_file_pi_defaults_reach_pi_subprocess_command_and_env(self) -> None:
        captured: dict[str, Any] = {}
        fake_proc = FakeProcess()

        def launcher(cmd, env, cwd):
            captured["cmd"] = cmd
            captured["env"] = env
            return fake_proc

        def ready_probe(**_kwargs):
            return {
                "provider": "pi_agent",
                "status": "ready",
                "message": "fake pi ready",
                "capabilities": ["chat"],
            }

        provider = agent_bridge.PiAgentProvider(
            subprocess_launcher=launcher,
            status_probe=ready_probe,
        )

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / ".env").write_text(
                "PI_DEFAULT_MODEL=aicodemirror/gpt-5.5\n"
                "PI_DEFAULT_THINKING=medium\n",
                encoding="utf-8",
            )
            list(
                provider.stream_message(
                    node_context=_NODE_CONTEXT,
                    mode="explain",
                    message="hi",
                    repo_root=repo_root,
                )
            )
        self.assertEqual(
            captured["cmd"],
            [
                "pi",
                "--mode",
                "rpc",
                "--model",
                "aicodemirror/gpt-5.5",
                "--thinking",
                "medium",
                "--exclude-tools",
                "read,write,edit,bash,grep,find,ls,ask_question",
            ],
        )
        self.assertEqual(captured["env"]["PI_DEFAULT_MODEL"], "aicodemirror/gpt-5.5")
        self.assertEqual(captured["env"]["PI_DEFAULT_THINKING"], "medium")

    def test_env_file_pi_default_model_overrides_process_env_for_command(self) -> None:
        captured: dict[str, Any] = {}
        fake_proc = FakeProcess()
        old_model = os.environ.get("PI_DEFAULT_MODEL")
        os.environ["PI_DEFAULT_MODEL"] = "anthropic/claude-from-process"
        self.addCleanup(
            lambda: os.environ.pop("PI_DEFAULT_MODEL", None)
            if old_model is None
            else os.environ.__setitem__("PI_DEFAULT_MODEL", old_model)
        )

        def launcher(cmd, env, cwd):
            captured["cmd"] = cmd
            captured["env"] = env
            return fake_proc

        def ready_probe(**_kwargs):
            return {
                "provider": "pi_agent",
                "status": "ready",
                "message": "fake pi ready",
                "capabilities": ["chat"],
            }

        provider = agent_bridge.PiAgentProvider(
            subprocess_launcher=launcher,
            status_probe=ready_probe,
        )

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / ".env").write_text(
                "PI_DEFAULT_MODEL=aicodemirror/gpt-5.5\n", encoding="utf-8"
            )
            list(
                provider.stream_message(
                    node_context=_NODE_CONTEXT,
                    mode="explain",
                    message="hi",
                    repo_root=repo_root,
                )
            )
        self.assertEqual(captured["env"]["PI_DEFAULT_MODEL"], "aicodemirror/gpt-5.5")
        self.assertEqual(
            captured["cmd"],
            [
                "pi",
                "--mode",
                "rpc",
                "--model",
                "aicodemirror/gpt-5.5",
                "--exclude-tools",
                "read,write,edit,bash,grep,find,ls,ask_question",
            ],
        )

    def test_default_exclude_tools_blacklist_passed_to_pi_command(self) -> None:
        """Right-side provider must default to the filesystem/shell-tool blacklist.

        The right-side dialog is positioned as `understand + suggest`. The prompt
        already carries PRD + node + interaction context, so PI should not invoke
        read/write/edit/bash/grep/find/ls/ask_question on its own. This pins the
        default `--exclude-tools` payload so the boundary cannot regress silently.
        """
        captured: dict[str, Any] = {}
        fake_proc = FakeProcess()

        def launcher(cmd, env, cwd):
            captured["cmd"] = cmd
            return fake_proc

        def ready_probe(**_kwargs):
            return {
                "provider": "pi_agent",
                "status": "ready",
                "message": "fake pi ready",
                "capabilities": ["chat"],
            }

        provider = agent_bridge.PiAgentProvider(
            subprocess_launcher=launcher,
            status_probe=ready_probe,
        )

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            list(
                provider.stream_message(
                    node_context=_NODE_CONTEXT,
                    mode="explain",
                    message="hi",
                    repo_root=repo_root,
                )
            )
        self.assertIn("--exclude-tools", captured["cmd"])
        idx = captured["cmd"].index("--exclude-tools")
        self.assertEqual(
            captured["cmd"][idx + 1],
            "read,write,edit,bash,grep,find,ls,ask_question",
        )

    def test_exclude_tools_empty_tuple_omits_flag(self) -> None:
        """exclude_tools=() must drop the flag entirely (escape hatch for probes)."""
        captured: dict[str, Any] = {}
        fake_proc = FakeProcess()

        def launcher(cmd, env, cwd):
            captured["cmd"] = cmd
            return fake_proc

        client = pi_rpc.PiRpcClient(
            repo_root=Path("."),
            default_model=None,
            default_thinking=None,
            subprocess_launcher=launcher,
            env_override={"PI_BIN": "pi"},
            exclude_tools=(),
        )

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        try:
            list(client.send_prompt("hi"))
        finally:
            client.close()
        self.assertNotIn("--exclude-tools", captured["cmd"])


class PiTrailingActionsTests(unittest.TestCase):
    """Cover the structured-action protocol: trailing ```json {"actions":[...]}``` block."""

    def test_parses_known_action_types_and_strips_tail(self) -> None:
        answer = (
            "节点解释……\n"
            "```json\n"
            '{"actions": [{"type": "rerun_from_node", "patch_summary": "从此节点重跑"}]}\n'
            "```"
        )
        cleaned, actions = agent_bridge._parse_trailing_actions(
            answer, context_revision="ctx-1"
        )
        self.assertEqual(cleaned, "节点解释……")
        self.assertIsNotNone(actions)
        assert actions is not None
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "rerun_from_node")
        self.assertEqual(actions[0]["context_revision"], "ctx-1")
        self.assertEqual(actions[0]["source"], "pi_agent")
        self.assertTrue(actions[0]["requires_confirmation"])

    def test_unknown_action_type_filtered_out(self) -> None:
        answer = (
            "ok\n```json\n{\"actions\": ["
            "{\"type\": \"explain_node\"}, {\"type\": \"shell_exec\"}]}\n```"
        )
        _cleaned, actions = agent_bridge._parse_trailing_actions(answer)
        assert actions is not None
        self.assertEqual([a["type"] for a in actions], ["explain_node"])

    def test_no_trailing_block_returns_none(self) -> None:
        cleaned, actions = agent_bridge._parse_trailing_actions("纯文本答案，没有 JSON 块。")
        self.assertEqual(cleaned, "纯文本答案，没有 JSON 块。")
        self.assertIsNone(actions)

    def test_malformed_json_returns_none(self) -> None:
        answer = "前言\n```json\n{not valid json}\n```"
        cleaned, actions = agent_bridge._parse_trailing_actions(answer)
        self.assertEqual(cleaned, answer)
        self.assertIsNone(actions)

    def test_explicit_empty_actions_returns_empty_list(self) -> None:
        answer = "结论：暂无可执行建议。\n```json\n{\"actions\": []}\n```"
        cleaned, actions = agent_bridge._parse_trailing_actions(answer)
        self.assertEqual(cleaned, "结论：暂无可执行建议。")
        self.assertEqual(actions, [])

    def test_block_in_middle_is_not_consumed(self) -> None:
        answer = "前言\n```json\n{\"actions\": [{\"type\": \"explain_node\"}]}\n```\n后续说明。"
        cleaned, actions = agent_bridge._parse_trailing_actions(answer)
        self.assertEqual(cleaned, answer)
        self.assertIsNone(actions)


class PiAgentProviderStructuredActionsTests(unittest.TestCase):
    """stream_message must inject cleaned_message + pi_structured actions on agent_end."""

    def setUp(self) -> None:
        agent_bridge.reset_provider_singletons()

    def tearDown(self) -> None:
        agent_bridge.reset_provider_singletons()

    def _ready_probe(self, **_kwargs):
        return {
            "provider": "pi_agent",
            "status": "ready",
            "message": "fake pi ready",
            "capabilities": ["chat"],
        }

    def test_agent_end_payload_carries_cleaned_message_and_pi_structured_actions(self) -> None:
        fake_proc = FakeProcess()

        def launcher(cmd, env, cwd):
            return fake_proc

        provider = agent_bridge.PiAgentProvider(
            subprocess_launcher=launcher,
            status_probe=self._ready_probe,
        )

        prose = "context_contract 节点的作用是把 PRD 和领域配置整理成上下文契约。"
        tail = (
            "\n```json\n"
            '{"actions": [{"type": "rerun_from_node", '
            '"patch_summary": "从 context_contract 重跑"}]}\n'
            "```"
        )

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_text_delta(prose))
            fake_proc.emit(_text_delta(tail))
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        with tempfile.TemporaryDirectory() as temp_dir:
            events = list(
                provider.stream_message(
                    node_context={**_NODE_CONTEXT, "context_revision": "ctx-XYZ"},
                    mode="explain",
                    message="解释这个节点",
                    repo_root=Path(temp_dir),
                )
            )

        terminals = [e for e in events if e.get("type") == "agent_end"]
        self.assertEqual(len(terminals), 1)
        payload = terminals[0]["payload"]
        self.assertEqual(payload["cleaned_message"], prose)
        self.assertEqual(payload["actions_source"], "pi_structured")
        self.assertEqual(payload["actions"][0]["type"], "rerun_from_node")
        self.assertEqual(payload["actions"][0]["context_revision"], "ctx-XYZ")

    def test_no_trailing_block_falls_back_to_deterministic_baseline(self) -> None:
        fake_proc = FakeProcess()

        def launcher(cmd, env, cwd):
            return fake_proc

        provider = agent_bridge.PiAgentProvider(
            subprocess_launcher=launcher,
            status_probe=self._ready_probe,
        )

        def producer() -> None:
            time.sleep(0.02)
            fake_proc.emit(_text_delta("纯文本回答，没有结构化块。"))
            fake_proc.emit(_agent_end())

        threading.Thread(target=producer, daemon=True).start()
        with tempfile.TemporaryDirectory() as temp_dir:
            events = list(
                provider.stream_message(
                    node_context=_NODE_CONTEXT,
                    mode="explain",
                    message="hi",
                    repo_root=Path(temp_dir),
                )
            )

        payload = next(e for e in events if e.get("type") == "agent_end")["payload"]
        self.assertEqual(payload["cleaned_message"], "纯文本回答，没有结构化块。")
        self.assertEqual(payload["actions_source"], "deterministic_baseline")
        self.assertIsInstance(payload["actions"], list)


if __name__ == "__main__":
    unittest.main()