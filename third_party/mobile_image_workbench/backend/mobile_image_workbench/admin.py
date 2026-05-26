from __future__ import annotations

import datetime as dt
import os
import shlex
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def require_admin_token(authorization: str) -> None:
    token = os.environ.get("MWB_ADMIN_TOKEN", "").strip()
    if not token:
        raise PermissionError("MWB_ADMIN_TOKEN is required")
    if authorization.strip() != f"Bearer {token}":
        raise PermissionError("invalid admin token")


@dataclass
class AdminTask:
    task_id: str
    kind: str
    status: str = "queued"
    message: str = ""
    logs: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    exit_code: int | None = None
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "taskId": self.task_id,
            "kind": self.kind,
            "status": self.status,
            "message": self.message,
            "logs": self.logs[-120:],
            "summary": self.summary,
            "exitCode": self.exit_code,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


class AdminTaskManager:
    def __init__(
        self,
        repo_root: Path | None = None,
        *,
        run_async: bool = True,
        command_runner: Callable[..., Any] | None = None,
        popen_runner: Callable[..., Any] | None = None,
    ) -> None:
        self.repo_root = (repo_root or default_repo_root()).resolve()
        self.run_async = run_async
        self.command_runner = command_runner or subprocess.run
        self.popen_runner = popen_runner or subprocess.Popen
        self._tasks: dict[str, AdminTask] = {}
        self._lock = threading.Lock()

    @property
    def mac_deploy_script(self) -> Path:
        return self.repo_root / "third_party/mobile_deploy/mac-mini/install_workbench_launchd.sh"

    @property
    def cloud_deploy_script(self) -> Path:
        return self.repo_root / "third_party/mobile_deploy/server/install_asset_center_systemd.sh"

    def status(self, job_manager: Any) -> dict[str, Any]:
        latest = _latest_syncable_job(job_manager)
        return {
            "adminTokenConfigured": bool(os.environ.get("MWB_ADMIN_TOKEN", "").strip()),
            "cloudSync": _env_check(
                ["MWB_CLOUD_SERVER_URL", "MWB_CLOUD_SYNC_TOKEN", "MWB_COLLECTOR_ID"]
            ),
            "vlm": _env_check(["DASHSCOPE_API_KEY"]),
            "deploy": {
                "mac": {
                    "scriptExists": self.mac_deploy_script.exists(),
                    "script": str(self.mac_deploy_script),
                },
                "cloud": _env_check(
                    [
                        "MWB_DEPLOY_SSH_HOST",
                        "MWB_DEPLOY_SSH_USER",
                        "MWB_DEPLOY_SSH_KEY_PATH",
                    ]
                ),
            },
            "latestSyncableJob": latest.to_dict() if latest else None,
        }

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise FileNotFoundError(f"admin task not found: {task_id}")
            return task.to_dict()

    def start_sync_latest(self, job_manager: Any) -> dict[str, Any]:
        latest = _latest_syncable_job(job_manager)
        if latest is None:
            raise ValueError("没有可同步的 completed/partial 任务")

        def operation(task: AdminTask) -> dict[str, Any]:
            _log(task, f"准备同步最新任务 {latest.job_id}")
            summary = job_manager.sync_job_to_cloud(latest.job_id)
            _log(task, "最新任务云端同步完成")
            return summary

        return self._start_task("sync_latest", operation)

    def start_mac_deploy(self) -> dict[str, Any]:
        script = self.mac_deploy_script

        def operation(task: AdminTask) -> dict[str, Any]:
            if not script.exists():
                raise FileNotFoundError(f"Mac 部署脚本不存在: {script}")
            command = ["bash", str(script)]
            _log(task, "正在启动 Mac mini 工作台部署脚本")
            self.popen_runner(
                command,
                cwd=str(self.repo_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=os.environ.copy(),
            )
            _log(task, "部署脚本已在后台启动；服务可能短暂重启")
            return {"command": command, "detached": True}

        return self._start_task("deploy_mac", operation)

    def start_cloud_deploy(self) -> dict[str, Any]:
        script = self.cloud_deploy_script

        def operation(task: AdminTask) -> dict[str, Any]:
            if not script.exists():
                raise FileNotFoundError(f"云端部署脚本不存在: {script}")
            config = _cloud_deploy_config()
            ssh_target = f"{config['user']}@{config['host']}"
            ssh_options = [
                "ssh",
                "-i",
                config["key_path"],
                "-p",
                config["port"],
                "-o",
                "StrictHostKeyChecking=accept-new",
            ]
            rsync_command = [
                "rsync",
                "-az",
                "--delete",
                "-e",
                " ".join(shlex.quote(part) for part in ssh_options),
                "--exclude",
                ".git/",
                "--exclude",
                ".env*",
                "--exclude",
                "third_party/mobile_asset_center/data/",
                "--exclude",
                "third_party/mobile_image_workbench/runs/",
                "--exclude",
                "node_modules/",
                str(self.repo_root) + "/",
                f"{ssh_target}:{config['remote_root'].rstrip('/')}/",
            ]
            remote_command = (
                f"cd {shlex.quote(config['remote_root'])} && "
                f"sudo INSTALL_DIR={shlex.quote(config['install_dir'])} "
                f"HOST_NAME={shlex.quote(config['host_name'])} "
                "bash third_party/mobile_deploy/server/install_asset_center_systemd.sh"
            )
            ssh_command = ssh_options + [ssh_target, remote_command]
            _run_checked(task, self.command_runner, rsync_command, self.repo_root)
            _run_checked(task, self.command_runner, ssh_command, self.repo_root)
            return {
                "host": config["host"],
                "remoteRoot": config["remote_root"],
                "installDir": config["install_dir"],
            }

        return self._start_task("deploy_cloud", operation)

    def _start_task(
        self, kind: str, operation: Callable[[AdminTask], dict[str, Any]]
    ) -> dict[str, Any]:
        task = AdminTask(task_id=_make_task_id(), kind=kind)
        with self._lock:
            self._tasks[task.task_id] = task
        if self.run_async:
            thread = threading.Thread(
                target=self._run_task, args=(task, operation), daemon=True
            )
            thread.start()
        else:
            self._run_task(task, operation)
        return task.to_dict()

    def _run_task(
        self, task: AdminTask, operation: Callable[[AdminTask], dict[str, Any]]
    ) -> None:
        task.status = "running"
        task.started_at = _now()
        try:
            task.summary = operation(task)
            task.status = "completed"
            task.exit_code = 0
            task.message = "执行完成"
        except Exception as exc:  # pragma: no cover - exercised through public API
            task.status = "failed"
            task.exit_code = 1
            task.message = str(exc)
            _log(task, str(exc))
        finally:
            task.finished_at = _now()


def _latest_syncable_job(job_manager: Any) -> Any | None:
    candidates: list[Any] = []
    root_dir = Path(job_manager.root_dir)
    if not root_dir.exists():
        return None
    for child in root_dir.iterdir():
        if not child.is_dir() or not (child / "job.json").exists():
            continue
        try:
            record = job_manager.get_job(child.name)
        except Exception:
            continue
        if record.status in {"completed", "partial"}:
            candidates.append(record)
    candidates.sort(key=lambda record: record.job_id, reverse=True)
    return candidates[0] if candidates else None


def _env_check(names: list[str]) -> dict[str, Any]:
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    return {"configured": not missing, "missing": missing}


def _cloud_deploy_config() -> dict[str, str]:
    required = _env_check(
        ["MWB_DEPLOY_SSH_HOST", "MWB_DEPLOY_SSH_USER", "MWB_DEPLOY_SSH_KEY_PATH"]
    )
    if required["missing"]:
        raise ValueError("missing deploy config: " + ", ".join(required["missing"]))
    return {
        "host": os.environ["MWB_DEPLOY_SSH_HOST"].strip(),
        "user": os.environ["MWB_DEPLOY_SSH_USER"].strip(),
        "key_path": os.environ["MWB_DEPLOY_SSH_KEY_PATH"].strip(),
        "port": os.environ.get("MWB_DEPLOY_SSH_PORT", "22").strip() or "22",
        "remote_root": os.environ.get(
            "MWB_DEPLOY_REMOTE_ROOT", "/tmp/mobile-deploy-workspace"
        ).strip()
        or "/tmp/mobile-deploy-workspace",
        "install_dir": os.environ.get(
            "MWB_DEPLOY_REMOTE_INSTALL_DIR", "/opt/mobile_asset_center"
        ).strip()
        or "/opt/mobile_asset_center",
        "host_name": os.environ.get("MWB_DEPLOY_HOST_NAME", "_").strip() or "_",
    }


def _run_checked(
    task: AdminTask,
    runner: Callable[..., Any],
    command: list[str],
    cwd: Path,
) -> None:
    _log(task, "$ " + " ".join(shlex.quote(part) for part in command))
    completed = runner(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=600,
    )
    stdout = str(getattr(completed, "stdout", "") or "").strip()
    stderr = str(getattr(completed, "stderr", "") or "").strip()
    if stdout:
        _log(task, stdout)
    if stderr:
        _log(task, stderr)
    if int(getattr(completed, "returncode", 1)) != 0:
        raise RuntimeError(f"command failed: {command[0]}")


def _log(task: AdminTask, message: str) -> None:
    task.logs.append(f"{_now()} {message}")


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _make_task_id() -> str:
    return f"admin-{uuid.uuid4().hex[:12]}"
