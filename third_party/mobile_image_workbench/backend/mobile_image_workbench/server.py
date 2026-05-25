from __future__ import annotations

import json
import mimetypes
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .events import event_key_for
from .jobs import JobManager


class WorkbenchRequestHandler(BaseHTTPRequestHandler):
    manager: JobManager
    static_root: Path

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/doctor":
                self._send_json(self.manager.doctor())
                return
            if path.startswith("/api/library/"):
                self._handle_library_get(parsed)
                return
            if path.startswith("/api/jobs/"):
                self._handle_job_get(path)
                return
            self._serve_static(path)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/jobs":
                payload = self._read_json()
                record = self.manager.create_job(payload, start=True)
                self._send_json(record.to_dict(), HTTPStatus.CREATED)
                return
            if parsed.path == "/api/library/ingest":
                payload = self._read_json()
                summary = self.manager.ingest_assets(
                    Path(str(payload.get("runDir") or payload.get("run_dir") or "")),
                    job_id=str(payload.get("jobId") or payload.get("job_id") or ""),
                    category=str(payload.get("category") or ""),
                    scene=str(payload.get("scene") or ""),
                    input_mode=str(payload.get("inputMode") or payload.get("input_mode") or ""),
                    uploaded_by=str(payload.get("uploadedBy") or payload.get("uploaded_by") or ""),
                )
                self._send_json(summary, HTTPStatus.CREATED)
                return
            if parsed.path.startswith("/api/jobs/"):
                parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
                if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "sync-cloud":
                    self._send_json(self.manager.sync_job_to_cloud(parts[2]))
                    return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _handle_library_get(self, parsed) -> None:
        path = parsed.path
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if parts[:3] == ["api", "library", "assets"] and len(parts) == 3:
            filters = {
                key: values[0]
                for key, values in parse_qs(parsed.query, keep_blank_values=False).items()
                if values
            }
            self._send_json(self.manager.search_assets(filters))
            return
        if parts[:3] == ["api", "library", "assets"] and len(parts) == 5:
            asset_id = parts[3]
            action = parts[4]
            if action not in {"image", "download"}:
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            blob = self.manager.asset_blob(asset_id)
            self._send_bytes(
                blob.payload,
                blob.content_type,
                download_name=blob.filename if action == "download" else None,
            )
            return
        if parts[:3] == ["api", "library", "objects"] and len(parts) >= 5:
            bucket = parts[3]
            key = "/".join(parts[4:])
            blob = self.manager.object_blob(bucket, key)
            self._send_bytes(blob.payload, blob.content_type)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _handle_job_get(self, path: str) -> None:
        parts = [unquote(part) for part in path.strip("/").split("/")]
        if len(parts) < 3:
            self._send_json({"error": "job id required"}, HTTPStatus.BAD_REQUEST)
            return
        job_id = parts[2]
        suffix = parts[3:] if len(parts) > 3 else []
        record = self.manager.get_job(job_id)
        if not suffix:
            self._send_json(record.to_dict())
            return
        if suffix == ["events"]:
            self._stream_events(job_id)
            return
        if suffix == ["events.json"]:
            self._send_json({"events": self.manager.translated_events(job_id)})
            return
        if suffix == ["results.html"]:
            self._send_run_file(record.collector_run_dir, "results.html", "text/html")
            return
        if suffix == ["results.csv"]:
            self._send_run_file(record.collector_run_dir, "results.csv", "text/csv")
            return
        if suffix == ["results_images.zip"]:
            self._send_run_file(
                record.collector_run_dir, "results_images.zip", "application/zip"
            )
            return
        if suffix and suffix[0] == "assets":
            relative_path = Path(*suffix[1:])
            self._send_asset(record.collector_run_dir, relative_path)
            return
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _stream_events(self, job_id: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        sent_event_keys: set[str] = set()
        while True:
            events = self.manager.translated_events(job_id)
            for event in events:
                event_key = _server_event_key(event)
                if event_key in sent_event_keys:
                    continue
                sent_event_keys.add(event_key)
                self.wfile.write(
                    f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
                )
                self.wfile.flush()
            record = self.manager.get_job(job_id)
            if record.status not in {"queued", "running"}:
                break
            time.sleep(1)

    def _send_run_file(
        self, run_dir: Path | None, filename: str, content_type: str
    ) -> None:
        if run_dir is None:
            self._send_json({"error": "result not ready"}, HTTPStatus.NOT_FOUND)
            return
        self._send_file(run_dir / filename, content_type)

    def _send_asset(self, run_dir: Path | None, relative_path: Path) -> None:
        if run_dir is None:
            self._send_json({"error": "result not ready"}, HTTPStatus.NOT_FOUND)
            return
        target = (run_dir / relative_path).resolve()
        if run_dir.resolve() not in target.parents and target != run_dir.resolve():
            self._send_json({"error": "invalid asset path"}, HTTPStatus.BAD_REQUEST)
            return
        self._send_file(target, mimetypes.guess_type(target.name)[0] or "application/octet-stream")

    def _serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            target = self.static_root / "index.html"
        else:
            target = (self.static_root / path.lstrip("/")).resolve()
            if self.static_root.resolve() not in target.parents and target != self.static_root.resolve():
                self._send_json({"error": "invalid static path"}, HTTPStatus.BAD_REQUEST)
                return
        if not target.exists() and path != "/":
            target = self.static_root / "index.html"
        self._send_file(target, mimetypes.guess_type(target.name)[0] or "text/html")

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        self._send_bytes(path.read_bytes(), content_type)

    def _send_bytes(
        self,
        payload: bytes,
        content_type: str,
        *,
        download_name: str | None = None,
    ) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if download_name:
            safe_name = download_name.replace('"', "")
            self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(
        self, payload: dict, status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def _server_event_key(event: dict) -> str:
    if event.get("eventKey"):
        return str(event["eventKey"])
    raw = event.get("raw")
    if isinstance(raw, dict):
        return event_key_for(raw)
    return event_key_for(event)


def serve(
    *,
    host: str,
    port: int,
    runs_root: Path,
    static_root: Path,
    base_collector_config: Path | None = None,
) -> ThreadingHTTPServer:
    manager = JobManager(runs_root, base_collector_config=base_collector_config)

    class Handler(WorkbenchRequestHandler):
        pass

    Handler.manager = manager
    Handler.static_root = static_root
    server = ThreadingHTTPServer((host, port), Handler)
    return server
