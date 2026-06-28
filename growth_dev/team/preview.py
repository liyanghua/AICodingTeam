from __future__ import annotations

import errno
import http.client
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from ..utils import ensure_dir, now_iso, write_json


ALLOWED_COMMANDS = frozenset({"node", "python3", "python"})
ALLOWED_DIR_MARKER = "generated_apps"
PORT_SCAN_LIMIT = 50
HEALTH_POLL_INTERVAL = 0.1
ENV_WHITELIST = frozenset(
    {
        "IMAGE_PROVIDER",
        "OPENROUTER_API_KEY",
        "OPENROUTER_API_BASE_URL",
        "OPENROUTER_IMAGE_MODEL",
        "OPENROUTER_IMAGE_SIZE",
        "OPENROUTER_IMAGE_QUALITY",
        "OPENROUTER_IMAGE_OUTPUT_FORMAT",
        "IMAGE_REQUEST_TIMEOUT_MS",
        "OPENAI_API_KEY",
        "OPENAI_IMAGE_MODEL",
        "OPENAI_IMAGE_SIZE",
        "OPENAI_IMAGE_QUALITY",
        "OPENAI_IMAGE_OUTPUT_FORMAT",
    }
)


@dataclass
class PreviewRunRequest:
    run_id: str
    app_slug: str
    generated_app_dir: Path
    preview_command: list[str]
    preferred_port: int = 8788
    health_path: str = "/"
    health_timeout_seconds: float = 5.0
    repo_root: Path = field(default_factory=lambda: Path("."))
    inject_env: bool = True


@dataclass
class PreviewRunResult:
    status: Literal["running", "failed", "timeout"]
    pid: int | None
    port: int | None
    url: str | None
    health_status: Literal["ok", "failed", "unknown"]
    started_at: str
    log_path: Path
    record_path: Path
    risk_events: list[str]
    message: str


def allocate_port(preferred: int) -> int:
    last_error: OSError | None = None
    for offset in range(PORT_SCAN_LIMIT):
        candidate = preferred + offset
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", candidate))
            return candidate
        except OSError as exc:
            last_error = exc
            if exc.errno in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
                continue
            raise RuntimeError(
                f"cannot bind 127.0.0.1 in this environment: {exc}"
            ) from exc
        finally:
            sock.close()
    raise RuntimeError(
        f"no available port within {PORT_SCAN_LIMIT} of {preferred} (last error: {last_error})"
    )


def wait_for_health(url: str, *, timeout: float) -> tuple[bool, str]:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/"
    deadline = time.monotonic() + timeout
    last_error = "no response"

    while time.monotonic() < deadline:
        conn = http.client.HTTPConnection(host, port, timeout=1.0)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            response.read()
            if response.status == 200:
                return True, f"GET {path} returned 200"
            last_error = f"GET {path} returned {response.status}"
        except (ConnectionRefusedError, OSError, http.client.HTTPException) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        finally:
            conn.close()
        time.sleep(HEALTH_POLL_INTERVAL)

    return False, f"health check timeout after {timeout}s ({last_error})"


def _inject_preview_env(repo_root: Path) -> dict[str, str]:
    env_path = repo_root / ".env"
    if not env_path.exists():
        return {}
    injected: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in ENV_WHITELIST:
            injected[key] = value.strip().strip("'\"")
    return injected


def _validate_request(request: PreviewRunRequest) -> None:
    resolved = request.generated_app_dir.resolve()
    if ALLOWED_DIR_MARKER not in resolved.parts:
        raise ValueError(
            f"generated_app_dir is not under an allowed '{ALLOWED_DIR_MARKER}/' path: {resolved}"
        )
    if ".." in request.generated_app_dir.parts:
        raise ValueError("generated_app_dir must not contain path traversal segments")

    if not request.preview_command:
        raise ValueError("preview_command must not be empty")
    executable = Path(request.preview_command[0]).name
    if executable not in ALLOWED_COMMANDS:
        raise ValueError(
            f"preview command '{executable}' is not allowed; allowed: {sorted(ALLOWED_COMMANDS)}"
        )


def start_preview(request: PreviewRunRequest, *, runs_dir: Path) -> PreviewRunResult:
    _validate_request(request)

    preview_dir = ensure_dir(runs_dir / request.run_id / "preview")
    log_path = preview_dir / "preview.log"
    record_path = preview_dir / "preview_run_record.json"
    started_at = now_iso()

    port = allocate_port(request.preferred_port)
    url = f"http://127.0.0.1:{port}{request.health_path}"

    env = dict(os.environ)
    if request.inject_env:
        env.update(_inject_preview_env(request.repo_root.resolve()))
    env["PORT"] = str(port)
    env["PREVIEW_PORT"] = str(port)

    risk_events: list[str] = []
    log_handle = log_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            request.preview_command,
            cwd=str(request.generated_app_dir),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            shell=False,
        )
    finally:
        log_handle.close()

    ok, health_message = wait_for_health(url, timeout=request.health_timeout_seconds)
    health_status: Literal["ok", "failed", "unknown"] = "ok" if ok else "failed"
    status: Literal["running", "failed", "timeout"] = "running" if ok else "timeout"

    if not ok and process.poll() is None:
        risk_events.append("health_check_failed_killing_process")
        _terminate(process)

    record = {
        "schema_version": 1,
        "run_id": request.run_id,
        "app_slug": request.app_slug,
        "pid": process.pid,
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "command": list(request.preview_command),
        "cwd": str(request.generated_app_dir),
        "started_at": started_at,
        "stopped_at": None,
        "health_status": health_status,
        "health_message": health_message,
        "log_path": "preview/preview.log",
        "risk_events": risk_events,
    }
    write_json(record_path, record)

    return PreviewRunResult(
        status=status,
        pid=process.pid if ok else None,
        port=port if ok else None,
        url=f"http://127.0.0.1:{port}" if ok else None,
        health_status=health_status,
        started_at=started_at,
        log_path=log_path,
        record_path=record_path,
        risk_events=risk_events,
        message=health_message,
    )


def _terminate(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3.0)
    except ProcessLookupError:
        pass


def stop_preview(record_path: Path) -> dict[str, Any]:
    record = _read_record(record_path)
    pid = record.get("pid")

    killed = False
    if isinstance(pid, int):
        killed = _kill_pid(pid)

    record["stopped_at"] = now_iso()
    record["health_status"] = "unknown"
    write_json(record_path, record)

    return {"status": "stopped", "pid": pid, "killed": killed}


def _kill_pid(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return True


def list_active_previews(runs_dir: Path) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return active

    for record_path in sorted(runs_dir.glob("*/preview/preview_run_record.json")):
        try:
            record = _read_record(record_path)
        except Exception:
            continue
        if record.get("stopped_at") is None:
            active.append(record)
    return active


def _read_record(record_path: Path) -> dict[str, Any]:
    import json

    return json.loads(record_path.read_text(encoding="utf-8"))
