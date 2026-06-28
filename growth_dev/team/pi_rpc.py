"""PI RPC subprocess client.

Wraps a long-lived ``pi --mode rpc`` child process and exposes a streaming
``send_prompt`` generator that yields normalized StreamEvent dicts.

Wire protocol reference: docs/app_generation_agent_bridge_spec.md `### pi_agent`.

Design constraints:

- Child process is launched lazily on first prompt; reused across prompts.
- stdin writes are serialized through ``_write_lock``.
- A dedicated daemon reader thread parses stdout line-by-line and routes events
  into per-prompt ``queue.Queue`` instances keyed by prompt id.
- The reader thread is the only consumer of stdout; ``send_prompt`` consumes its
  queue and yields events to the caller.
- All inbound text values are passed through ``redactor`` before being emitted.
- ``subprocess_launcher`` and ``event_parser`` are injectable for tests.
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

# Default per-prompt response timeout (no events received within window).
DEFAULT_RPC_TIMEOUT_SEC = 60.0
# Default boot timeout for the child process.
DEFAULT_BOOT_TIMEOUT_SEC = 15.0
# Sentinel queue value indicating the reader thread is done with a prompt.
_PROMPT_DONE = object()


StreamEvent = dict[str, Any]
SubprocessLauncher = Callable[[list[str], dict[str, str], Path], Any]
EventParser = Callable[[str], list[StreamEvent]]
Redactor = Callable[[str], str]

# Default --exclude-tools blacklist for the right-side dialog Provider.
# Boundary decision: PI = understand + suggest, not autonomous explorer. The
# prompt already carries the PRD / node context / interaction context, so PI
# should not invoke filesystem or shell tools on its own. ask_question is also
# excluded because the workbench owns the human-in-the-loop UI.
DEFAULT_EXCLUDE_TOOLS: tuple[str, ...] = (
    "read",
    "write",
    "edit",
    "bash",
    "grep",
    "find",
    "ls",
    "ask_question",
)


def _identity_redactor(value: str) -> str:
    return value


# Credentials pi cares about. Each canonical (upper-case) env key maps to the
# aliases that may appear in repo_root/.env. .env wins over os.environ so a
# committed project credential always reaches the pi subprocess, matching the
# codex provider's _codex_credentials precedence.
PI_ENV_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "AICODEMIRROR_API_KEY": ("AICODEMIRROR_API_KEY", "aicodemirror_api_key", "aicodemirror_key"),
    "AICODEMIRROR_BASE_URL": ("AICODEMIRROR_BASE_URL", "aicodemirror_base_url"),
    "ANTHROPIC_API_KEY": ("ANTHROPIC_API_KEY",),
    "OPENAI_API_KEY": ("OPENAI_API_KEY",),
    "OPENROUTER_API_KEY": ("OPENROUTER_API_KEY", "OPENROUTER"),
    "DEEPSEEK_API_KEY": ("DEEPSEEK_API_KEY",),
    "PI_BIN": ("PI_BIN",),
    "PI_DEFAULT_MODEL": ("PI_DEFAULT_MODEL",),
    "PI_DEFAULT_THINKING": ("PI_DEFAULT_THINKING",),
}


def _read_env_file_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_pi_env_overrides(
    repo_root: Path,
    base_env: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Merge whitelisted credential keys from repo_root/.env into the env dict.

    pi resolves upper-case credential env vars itself; this only ensures the
    subprocess inherits keys defined in the project .env (which Python does not
    auto-load). Non-whitelisted .env entries are intentionally not forwarded.
    """
    env = dict(base_env if base_env is not None else os.environ)
    file_values = _read_env_file_values(repo_root / ".env")
    if not file_values:
        return env
    for canonical, aliases in PI_ENV_KEY_ALIASES.items():
        for alias in aliases:
            value = file_values.get(alias)
            if value:
                env[canonical] = value
                break
    return env


def default_subprocess_launcher(cmd: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen:
    """Default Popen launcher.

    stdout/stdin are line-buffered text streams (utf-8); stderr is captured.
    """
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )


def default_event_parser(line: str) -> list[StreamEvent]:
    """Parse a single stdout JSONL line into zero or more StreamEvents.

    Translates the real pi wire protocol (AgentSessionEvent union) into the
    normalized events the frontend understands (message_delta / tool_call /
    tool_result / agent_end / upstream_error). Termination follows model A:
    only the session-level agent_end (or an error) is terminal; the prompt
    response ack (preflight-ok) and per-turn turn_end are NOT terminal.

    Returns a list because one packet may expand into multiple stream events.
    Empty list means the line should be ignored (heartbeat, lifecycle noise,
    thinking-only frames routed elsewhere, etc.).
    """
    line = line.strip()
    if not line:
        return []
    try:
        packet = json.loads(line)
    except json.JSONDecodeError:
        return []
    if not isinstance(packet, dict):
        return []

    top = packet.get("type")
    now = time.time()

    if top == "message_update":
        event = packet.get("assistantMessageEvent")
        if not isinstance(event, dict):
            return []
        return _assistant_message_event_to_stream(event, packet.get("id"), now)

    if top == "tool_execution_start":
        return [
            {
                "type": "tool_call",
                "id": packet.get("id"),
                "payload": {
                    "tool_call_id": str(packet.get("toolCallId") or packet.get("tool_call_id") or ""),
                    "name": str(packet.get("toolName") or packet.get("tool_name") or ""),
                    "input": packet.get("args") if isinstance(packet.get("args"), (dict, list, str)) else {},
                },
                "ts": now,
            }
        ]

    if top == "tool_execution_end":
        return [
            {
                "type": "tool_result",
                "id": packet.get("id"),
                "payload": {
                    "tool_call_id": str(packet.get("toolCallId") or packet.get("tool_call_id") or ""),
                    "output": packet.get("result", packet.get("output", "")),
                    "is_error": bool(packet.get("isError", packet.get("is_error", False))),
                },
                "ts": now,
            }
        ]

    if top == "agent_end":
        return _extract_agent_end(packet, packet.get("id"), now)

    if top in {"turn_start", "turn_end", "message_start", "message_end", "session_info_changed"}:
        return []

    if top == "auto_retry_start":
        return [
            {
                "type": "auto_retry_start",
                "id": packet.get("id"),
                "payload": {
                    "attempt": int(packet.get("attempt") or 0),
                    "maxAttempts": int(packet.get("maxAttempts") or 0),
                    "delayMs": int(packet.get("delayMs") or 0),
                    "errorMessage": str(packet.get("errorMessage") or ""),
                },
                "ts": now,
            }
        ]

    if top == "auto_retry_end":
        if packet.get("success") is False:
            final_error = str(packet.get("finalError") or "auto retry exhausted")
            return [
                {
                    "type": "upstream_error",
                    "id": packet.get("id"),
                    "payload": {
                        "phase": "auto_retry_end",
                        "errorMessage": final_error,
                        "hint": _error_hint(final_error),
                    },
                    "ts": now,
                }
            ]
        return []

    if top == "response":
        # The `prompt` command's response{success:true} is emitted right after
        # preflight succeeds (rpc-mode.ts:390-411), NOT when the answer
        # completes, so it must never terminate the stream. Only success=false
        # surfaces an error; the real terminal signal is the session-level
        # agent_end event.
        if packet.get("success") is False:
            message = str(packet.get("error") or "pi response reported failure")
            return [
                {
                    "type": "upstream_error",
                    "id": packet.get("id"),
                    "payload": {
                        "phase": "response_error",
                        "errorMessage": message,
                        "hint": _error_hint(message),
                    },
                    "ts": now,
                }
            ]
        return []

    if top == "extension_ui_request":
        prompt_id = packet.get("id") or packet.get("request_id")
        return [
            {
                "type": "extension_ui_request",
                "id": prompt_id,
                "payload": {
                    "request_id": packet.get("request_id") or packet.get("id"),
                    "prompt": str(packet.get("prompt") or ""),
                },
                "ts": now,
            }
        ]

    return []


def _assistant_message_event_to_stream(
    event: dict[str, Any],
    prompt_id: Any,
    ts: float,
) -> list[StreamEvent]:
    event_type = event.get("type")
    if event_type == "text_delta":
        text = event.get("delta") or event.get("text") or ""
        return [
            {
                "type": "message_delta",
                "id": prompt_id,
                "payload": {"text": str(text)},
                "ts": ts,
            }
        ]
    if event_type == "text_end":
        # Most PI versions send text_delta before text_end. Avoid duplicating
        # answers; text_end can be used as a future fallback if a probe shows
        # a PI build that emits only final content.
        return []
    if event_type in {"thinking_delta", "thinking_start", "thinking_end"}:
        payload: dict[str, Any] = {"phase": str(event_type)}
        if "delta" in event:
            payload["text"] = str(event.get("delta") or "")
        return [
            {
                "type": "thinking_delta",
                "id": prompt_id,
                "payload": payload,
                "ts": ts,
            }
        ]
    return []


def _extract_agent_end(
    packet: dict[str, Any],
    prompt_id: Any,
    ts: float,
) -> list[StreamEvent]:
    """Translate a session-level agent_end into the terminal stream event.

    Real pi agent_end = {type, messages: AgentMessage[], willRetry}. usage and
    stopReason/errorMessage live inside messages[], not at the top level, so we
    scan messages (latest non-empty wins) and fall back to top-level aliases for
    forward/backward compatibility. Per termination model A, willRetry==true is
    NOT terminal: the parser stays silent and waits for the next agent_end (or
    an auto_retry_end failure), so the workbench never closes a turn early.
    """
    will_retry = bool(packet.get("willRetry", False))
    messages = packet.get("messages") if isinstance(packet.get("messages"), list) else []
    usage = packet.get("usage") if isinstance(packet.get("usage"), dict) else {}
    stop_reason = packet.get("stop_reason") or packet.get("stopReason")
    error_message = packet.get("error") or packet.get("errorMessage")
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        msg_usage = msg.get("usage")
        if isinstance(msg_usage, dict) and msg_usage:
            usage = msg_usage
        sr = msg.get("stopReason") or msg.get("stop_reason")
        if sr:
            stop_reason = sr
        em = msg.get("errorMessage") or msg.get("error")
        if em:
            error_message = em
    stop_reason = stop_reason or "end_turn"

    if will_retry:
        return []

    if stop_reason == "error" or error_message:
        message = str(error_message or "agent_end reported error")
        return [
            {
                "type": "upstream_error",
                "id": prompt_id,
                "payload": {
                    "phase": "agent_end_error",
                    "errorMessage": message,
                    "hint": _error_hint(message),
                },
                "ts": ts,
            }
        ]

    return [
        {
            "type": "agent_end",
            "id": prompt_id,
            "payload": {
                "stop_reason": str(stop_reason),
                "usage": usage if isinstance(usage, dict) else {},
                "willRetry": False,
            },
            "ts": ts,
        }
    ]


def _error_hint(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("econnrefused", "enotfound", "network", "unreachable")):
        return "network_unreachable"
    if any(token in lowered for token in ("401", "403", "unauthorized", "forbidden", "invalid api key", "invalid token")):
        return "auth_invalid"
    if "429" in lowered or "rate" in lowered:
        return "rate_limited"
    if "timeout" in lowered or "timed out" in lowered:
        return "upstream_timeout"
    return "upstream_unknown"


def pi_status(
    *,
    pi_bin: Optional[str] = None,
    redactor: Redactor = _identity_redactor,
    which: Optional[Callable[[str], Optional[str]]] = None,
) -> dict[str, Any]:
    """Probe whether the pi binary is available without starting it."""
    binary = pi_bin or os.environ.get("PI_BIN") or "pi"
    resolver = which if which is not None else shutil.which
    abs_path = resolver(binary)
    if abs_path:
        return {
            "provider": "pi_agent",
            "status": "ready",
            "message": redactor(f"pi available at {abs_path}"),
            "capabilities": ["chat", "tool_calls", "stream"],
        }
    return {
        "provider": "pi_agent",
        "status": "not_configured",
        "message": "PI-Agent (pi) binary not found on PATH; install via npm i -g @earendil-works/pi-coding-agent",
        "capabilities": [],
    }


class PiRpcClient:
    """Long-lived ``pi --mode rpc`` client.

    Lifecycle:
    - Lazy boot on first ``send_prompt``.
    - Reused across prompts; serialized via ``_write_lock``.
    - ``close()`` terminates the child process; registered as atexit by default.

    Errors:
    - Boot failure within ``boot_timeout_sec`` -> raises ``RuntimeError``.
    - stdout closed before agent_end -> emits synthetic
      ``upstream_error{phase: "stream_closed"}`` and exits the iterator.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        pi_bin: Optional[str] = None,
        default_model: Optional[str] = None,
        default_thinking: Optional[str] = None,
        rpc_timeout_sec: float = DEFAULT_RPC_TIMEOUT_SEC,
        boot_timeout_sec: float = DEFAULT_BOOT_TIMEOUT_SEC,
        subprocess_launcher: SubprocessLauncher = default_subprocess_launcher,
        event_parser: EventParser = default_event_parser,
        redactor: Redactor = _identity_redactor,
        env_override: Optional[dict[str, str]] = None,
        exclude_tools: Optional[tuple[str, ...]] = DEFAULT_EXCLUDE_TOOLS,
    ) -> None:
        self._repo_root = repo_root
        self._pi_bin = pi_bin
        self._default_model = default_model
        self._default_thinking = default_thinking
        self._rpc_timeout_sec = rpc_timeout_sec
        self._boot_timeout_sec = boot_timeout_sec
        self._launcher = subprocess_launcher
        self._parser = event_parser
        self._redactor = redactor
        self._env_override = env_override
        self._exclude_tools = tuple(exclude_tools) if exclude_tools else ()

        self._process: Any = None
        self._reader_thread: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()
        self._pending: dict[str, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._active_prompt_id: Optional[str] = None
        self._active_queue: Optional[queue.Queue] = None
        self._stderr_buffer: list[str] = []
        self._closed = False

    # ------------------------------------------------------------------ boot

    def _build_cmd(self, env: Optional[dict[str, str]] = None) -> list[str]:
        resolved_env = env or {}
        pi_bin = self._pi_bin if self._pi_bin is not None else (resolved_env.get("PI_BIN") or "pi")
        default_model = (
            self._default_model
            if self._default_model is not None
            else resolved_env.get("PI_DEFAULT_MODEL", "")
        )
        default_thinking = (
            self._default_thinking
            if self._default_thinking is not None
            else resolved_env.get("PI_DEFAULT_THINKING", "")
        )
        cmd = [pi_bin, "--mode", "rpc"]
        if default_model:
            cmd += ["--model", default_model]
        if default_thinking:
            cmd += ["--thinking", default_thinking]
        if self._exclude_tools:
            cmd += ["--exclude-tools", ",".join(self._exclude_tools)]
        return cmd

    def _build_env(self) -> dict[str, str]:
        if self._env_override is not None:
            return dict(self._env_override)
        return load_pi_env_overrides(self._repo_root)

    def _ensure_process(self) -> None:
        if self._closed:
            raise RuntimeError("PiRpcClient has been closed")
        proc = self._process
        if proc is not None and getattr(proc, "poll", lambda: None)() is None:
            return
        self._spawn()

    def _spawn(self) -> None:
        env = self._build_env()
        cmd = self._build_cmd(env)
        try:
            self._process = self._launcher(cmd, env, self._repo_root)
        except FileNotFoundError as exc:
            raise RuntimeError(f"pi binary not found: {cmd[0]}") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"failed to launch pi: {exc!s}") from exc

        if self._process is None or self._process.stdout is None or self._process.stdin is None:
            raise RuntimeError("pi subprocess missing stdio handles")

        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="pi-rpc-reader", daemon=True
        )
        self._reader_thread.start()
        if getattr(self._process, "stderr", None) is not None:
            threading.Thread(
                target=self._stderr_loop, name="pi-rpc-stderr", daemon=True
            ).start()

    # ---------------------------------------------------------------- reader

    def _reader_loop(self) -> None:
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        try:
            for raw_line in proc.stdout:
                events = self._parser(raw_line)
                for event in events:
                    self._dispatch(event)
        except Exception:  # pragma: no cover - defensive
            pass
        finally:
            self._fanout_stream_closed()

    def _stderr_loop(self) -> None:
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        for raw_line in proc.stderr:
            if not raw_line:
                continue
            line = raw_line.rstrip("\n")
            if not line:
                continue
            redacted = self._redactor(line)
            self._stderr_buffer.append(redacted)
            if len(self._stderr_buffer) > 200:
                self._stderr_buffer = self._stderr_buffer[-200:]

    def _dispatch(self, event: StreamEvent) -> None:
        prompt_id = event.get("id")
        prompt_id_s = str(prompt_id) if prompt_id is not None else ""
        with self._pending_lock:
            if prompt_id is None:
                target = self._active_queue
            else:
                target = self._pending.get(prompt_id_s)
        if target is None:
            return
        if "payload" in event and isinstance(event["payload"], dict):
            event["payload"] = self._redact_payload(event["payload"])
        target.put(event)
        if event.get("type") in {"agent_end", "upstream_error"}:
            target.put(_PROMPT_DONE)
            with self._pending_lock:
                if prompt_id is None or self._active_prompt_id == prompt_id_s:
                    self._active_prompt_id = None
                    self._active_queue = None

    def _redact_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, str):
                redacted[key] = self._redactor(value)
            elif isinstance(value, dict):
                redacted[key] = self._redact_payload(value)
            elif isinstance(value, list):
                redacted[key] = [
                    self._redactor(item) if isinstance(item, str) else item for item in value
                ]
            else:
                redacted[key] = value
        return redacted

    def _fanout_stream_closed(self) -> None:
        stderr_summary = " | ".join(self._stderr_buffer[-5:]) if self._stderr_buffer else ""
        message = "pi stream closed before agent_end"
        if stderr_summary:
            message = f"{message}: {stderr_summary}"
        with self._pending_lock:
            pending_ids = list(self._pending.keys())
        now = time.time()
        for prompt_id in pending_ids:
            with self._pending_lock:
                target = self._pending.get(prompt_id)
            if target is None:
                continue
            target.put(
                {
                    "type": "upstream_error",
                    "id": prompt_id,
                    "payload": {
                        "phase": "stream_closed",
                        "errorMessage": message,
                        "hint": "upstream_unknown",
                    },
                    "ts": now,
                }
            )
            target.put(_PROMPT_DONE)

    # ------------------------------------------------------------------ send

    def send_prompt(
        self,
        message: str,
        *,
        streaming_behavior: str = "followUp",
    ) -> Iterator[StreamEvent]:
        if self._closed:
            raise RuntimeError("PiRpcClient is closed")
        self._ensure_process()
        prompt_id = str(uuid.uuid4())
        q: queue.Queue = queue.Queue()
        with self._pending_lock:
            self._pending[prompt_id] = q

        packet = {
            "type": "prompt",
            "id": prompt_id,
            "message": message,
            "streamingBehavior": streaming_behavior,
        }
        try:
            with self._write_lock:
                with self._pending_lock:
                    self._active_prompt_id = prompt_id
                    self._active_queue = q
                proc = self._process
                if proc is None or proc.stdin is None or getattr(proc, "poll", lambda: None)() is not None:
                    yield {
                        "type": "upstream_error",
                        "id": prompt_id,
                        "payload": {
                            "phase": "stream_closed",
                            "errorMessage": "pi subprocess is not running",
                            "hint": "upstream_unknown",
                        },
                        "ts": time.time(),
                    }
                    return
                try:
                    proc.stdin.write(json.dumps(packet, ensure_ascii=False) + "\n")
                    proc.stdin.flush()
                except (BrokenPipeError, OSError) as exc:
                    yield {
                        "type": "upstream_error",
                        "id": prompt_id,
                        "payload": {
                            "phase": "stream_closed",
                            "errorMessage": f"stdin write failed: {exc!s}",
                            "hint": "upstream_unknown",
                        },
                        "ts": time.time(),
                    }
                    return

            while True:
                try:
                    event = q.get(timeout=self._rpc_timeout_sec)
                except queue.Empty:
                    yield {
                        "type": "upstream_error",
                        "id": prompt_id,
                        "payload": {
                            "phase": "stream_timeout",
                            "errorMessage": f"no event received within {self._rpc_timeout_sec}s",
                            "hint": "upstream_timeout",
                        },
                        "ts": time.time(),
                    }
                    return
                if event is _PROMPT_DONE:
                    return
                yield event  # type: ignore[misc]
        finally:
            with self._pending_lock:
                self._pending.pop(prompt_id, None)
                if self._active_prompt_id == prompt_id:
                    self._active_prompt_id = None
                    self._active_queue = None

    # ----------------------------------------------------------------- close

    def close(self, *, timeout: float = 2.0) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self._process
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:  # pragma: no cover - defensive
                    pass
            terminate = getattr(proc, "terminate", None)
            if callable(terminate):
                terminate()
            wait = getattr(proc, "wait", None)
            if callable(wait):
                try:
                    wait(timeout=timeout)
                except Exception:  # pragma: no cover - defensive
                    kill = getattr(proc, "kill", None)
                    if callable(kill):
                        kill()
        finally:
            self._process = None


__all__ = [
    "DEFAULT_EXCLUDE_TOOLS",
    "PiRpcClient",
    "StreamEvent",
    "default_event_parser",
    "default_subprocess_launcher",
    "load_pi_env_overrides",
    "pi_status",
    "PI_ENV_KEY_ALIASES",
    "DEFAULT_RPC_TIMEOUT_SEC",
    "DEFAULT_BOOT_TIMEOUT_SEC",
]
