from __future__ import annotations

import json
import shutil
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


def _can_bind_localhost() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False
    finally:
        sock.close()


CAN_BIND = _can_bind_localhost()


class PreviewRunnerTests(unittest.TestCase):
    @unittest.skipUnless(CAN_BIND, "sandbox forbids socket.bind on 127.0.0.1")
    def test_allocate_port_finds_available_port(self) -> None:
        from growth_dev.team.preview import allocate_port

        port = allocate_port(8788)

        self.assertGreaterEqual(port, 8788)
        self.assertLess(port, 8788 + 50)
        # Verify it's actually available
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
        finally:
            sock.close()

    @unittest.skipUnless(CAN_BIND, "sandbox forbids socket.bind on 127.0.0.1")
    def test_allocate_port_skips_occupied_port(self) -> None:
        from growth_dev.team.preview import allocate_port

        # Occupy the preferred port
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", 8788))
        blocker.listen(1)
        try:
            port = allocate_port(8788)
            self.assertNotEqual(port, 8788)
            self.assertGreater(port, 8788)
        finally:
            blocker.close()

    def test_start_preview_rejects_disallowed_directory(self) -> None:
        from growth_dev.team.preview import PreviewRunRequest, start_preview

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            runs_dir.mkdir()
            disallowed_dir = Path(temp_dir) / "etc"
            disallowed_dir.mkdir()

            request = PreviewRunRequest(
                run_id="test-run",
                app_slug="test",
                generated_app_dir=disallowed_dir,
                preview_command=["node", "server.js"],
                repo_root=Path(temp_dir),
            )

            with self.assertRaises(ValueError) as ctx:
                start_preview(request, runs_dir=runs_dir)

        self.assertIn("allowed", str(ctx.exception).lower())

    def test_start_preview_rejects_disallowed_command(self) -> None:
        from growth_dev.team.preview import PreviewRunRequest, start_preview

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            runs_dir.mkdir()
            app_dir = Path(temp_dir) / "generated_apps" / "test"
            app_dir.mkdir(parents=True)

            request = PreviewRunRequest(
                run_id="test-run",
                app_slug="test",
                generated_app_dir=app_dir,
                preview_command=["rm", "-rf", "/"],
                repo_root=Path(temp_dir),
            )

            with self.assertRaises(ValueError) as ctx:
                start_preview(request, runs_dir=runs_dir)

        self.assertIn("command", str(ctx.exception).lower())

    def test_start_preview_injects_port_and_preview_port(self) -> None:
        from growth_dev.team.preview import PreviewRunRequest, start_preview

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            runs_dir.mkdir()
            app_dir = Path(temp_dir) / "generated_apps" / "test"
            app_dir.mkdir(parents=True)
            captured_env = {}

            class FakeProcess:
                pid = 12345

                def poll(self):
                    return None

            def fake_popen(*_args, **kwargs):
                captured_env.update(kwargs.get("env") or {})
                return FakeProcess()

            request = PreviewRunRequest(
                run_id="test-run",
                app_slug="test",
                generated_app_dir=app_dir,
                preview_command=["node", "server.js"],
                preferred_port=8799,
                repo_root=Path(temp_dir),
            )

            with mock.patch("growth_dev.team.preview.allocate_port", return_value=8799), \
                mock.patch("growth_dev.team.preview.wait_for_health", return_value=(True, "ok")), \
                mock.patch("growth_dev.team.preview.subprocess.Popen", side_effect=fake_popen):
                result = start_preview(request, runs_dir=runs_dir)

        self.assertEqual(result.status, "running")
        self.assertEqual(captured_env["PORT"], "8799")
        self.assertEqual(captured_env["PREVIEW_PORT"], "8799")

    def test_start_preview_injects_provider_env_whitelist(self) -> None:
        from growth_dev.team.preview import PreviewRunRequest, start_preview

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "IMAGE_PROVIDER=openrouter",
                        "OPENROUTER_API_KEY=sk-or-v1-secret",
                        "OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2",
                        "AICODEMIRROR_API_KEY=sk-aicodemirror-secret",
                        "AICODEMIRROR_KEY=sk-aicodemirror-legacy",
                        "AICODEMIRROR_BASE_URL=https://aicodemirror.example/api",
                        "DEEPSEEK_API_KEY=sk-deepseek-secret",
                        "PI_BIN=/usr/local/bin/pi",
                        "PI_DEFAULT_MODEL=aicodemirror/gpt-5.6-sol",
                        "PI_DEFAULT_THINKING=medium",
                        "PI_RPC_TIMEOUT_MS=3000",
                        "DB_ARCHAEOLOGIST_SPEC_PACK=/tmp/db-archaeologist",
                        "DBA_LIVE_PROBE=1",
                        "ZICHEN_BASE_URL=https://zichen.example",
                        "ZICHEN_TENANT_ID=tenant-1",
                        "ZICHEN_USER_ID=user-1",
                        "ZICHEN_APP_CODE_KEY=app-code-key",
                        "ZICHEN_APP_CODE=app-code",
                        "DATABASE_URL=postgres://should-not-pass",
                    ]
                ),
                encoding="utf-8",
            )
            runs_dir = root / "runs"
            runs_dir.mkdir()
            app_dir = root / "generated_apps" / "test"
            app_dir.mkdir(parents=True)
            captured_env = {}

            class FakeProcess:
                pid = 12345

                def poll(self):
                    return None

            def fake_popen(*_args, **kwargs):
                captured_env.update(kwargs.get("env") or {})
                return FakeProcess()

            request = PreviewRunRequest(
                run_id="test-run",
                app_slug="test",
                generated_app_dir=app_dir,
                preview_command=["node", "server.js"],
                preferred_port=8799,
                repo_root=root,
            )

            with mock.patch("growth_dev.team.preview.allocate_port", return_value=8799), \
                mock.patch("growth_dev.team.preview.wait_for_health", return_value=(True, "ok")), \
                mock.patch("growth_dev.team.preview.subprocess.Popen", side_effect=fake_popen):
                start_preview(request, runs_dir=runs_dir)

        self.assertEqual(captured_env["IMAGE_PROVIDER"], "openrouter")
        self.assertEqual(captured_env["OPENROUTER_API_KEY"], "sk-or-v1-secret")
        self.assertEqual(captured_env["OPENROUTER_IMAGE_MODEL"], "openai/gpt-5.4-image-2")
        self.assertEqual(captured_env["AICODEMIRROR_API_KEY"], "sk-aicodemirror-secret")
        self.assertEqual(captured_env["AICODEMIRROR_KEY"], "sk-aicodemirror-legacy")
        self.assertEqual(captured_env["AICODEMIRROR_BASE_URL"], "https://aicodemirror.example/api")
        self.assertEqual(captured_env["DEEPSEEK_API_KEY"], "sk-deepseek-secret")
        self.assertEqual(captured_env["PI_BIN"], "/usr/local/bin/pi")
        self.assertEqual(captured_env["PI_DEFAULT_MODEL"], "aicodemirror/gpt-5.6-sol")
        self.assertEqual(captured_env["PI_DEFAULT_THINKING"], "medium")
        self.assertEqual(captured_env["PI_RPC_TIMEOUT_MS"], "3000")
        self.assertEqual(captured_env["DB_ARCHAEOLOGIST_SPEC_PACK"], "/tmp/db-archaeologist")
        self.assertEqual(captured_env["DBA_LIVE_PROBE"], "1")
        self.assertEqual(captured_env["ZICHEN_BASE_URL"], "https://zichen.example")
        self.assertEqual(captured_env["ZICHEN_TENANT_ID"], "tenant-1")
        self.assertEqual(captured_env["ZICHEN_USER_ID"], "user-1")
        self.assertEqual(captured_env["ZICHEN_APP_CODE_KEY"], "app-code-key")
        self.assertEqual(captured_env["ZICHEN_APP_CODE"], "app-code")
        self.assertNotIn("DATABASE_URL", captured_env)

    @unittest.skipUnless(shutil.which("node") and CAN_BIND, "node or socket bind unavailable")
    def test_start_preview_launches_deterministic_app_and_returns_url(self) -> None:
        from growth_dev.team.app_generation import generate_deterministic_app_files
        from growth_dev.team.preview import PreviewRunRequest, start_preview, stop_preview

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            run_dir = runs_dir / "test-run"
            run_dir.mkdir(parents=True)

            app_slug = "preview-test"
            contract = {
                "app_slug": app_slug,
                "generated_app_dir": f"generated_apps/{app_slug}",
                "preview": {"url": "http://127.0.0.1:8788", "command": "node server.js"},
            }

            generate_deterministic_app_files(
                run_dir=Path(temp_dir),
                app_slug=app_slug,
                prd_text="# Preview Test\n\nTest app.",
                contract=contract,
                repo_root=Path(temp_dir),
            )

            app_dir = Path(temp_dir) / "generated_apps" / app_slug
            request = PreviewRunRequest(
                run_id="test-run",
                app_slug=app_slug,
                generated_app_dir=app_dir,
                preview_command=["node", "server.js"],
                preferred_port=8788,
                health_timeout_seconds=5.0,
                repo_root=Path(temp_dir),
            )

            try:
                result = start_preview(request, runs_dir=runs_dir)

                self.assertEqual(result.status, "running")
                self.assertIsNotNone(result.pid)
                self.assertIsNotNone(result.port)
                self.assertIsNotNone(result.url)
                self.assertEqual(result.health_status, "ok")
                self.assertTrue(result.url.startswith("http://127.0.0.1:"))
                self.assertTrue(result.record_path.exists())

                record = json.loads(result.record_path.read_text(encoding="utf-8"))
                self.assertEqual(record["app_slug"], app_slug)
                self.assertEqual(record["pid"], result.pid)
                self.assertEqual(record["health_status"], "ok")

                # Verify server is actually responding
                import http.client

                conn = http.client.HTTPConnection("127.0.0.1", result.port, timeout=2)
                try:
                    conn.request("GET", "/")
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                finally:
                    conn.close()

            finally:
                if result.record_path.exists():
                    stop_preview(result.record_path)
                    # Give it time to clean up
                    time.sleep(0.5)

    @unittest.skipUnless(shutil.which("node") and CAN_BIND, "node or socket bind unavailable")
    def test_stop_preview_terminates_process_and_releases_port(self) -> None:
        from growth_dev.team.app_generation import generate_deterministic_app_files
        from growth_dev.team.preview import PreviewRunRequest, start_preview, stop_preview

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            run_dir = runs_dir / "test-run"
            run_dir.mkdir(parents=True)

            app_slug = "stop-test"
            contract = {
                "app_slug": app_slug,
                "generated_app_dir": f"generated_apps/{app_slug}",
                "preview": {"url": "http://127.0.0.1:8789"},
            }

            generate_deterministic_app_files(
                run_dir=Path(temp_dir),
                app_slug=app_slug,
                prd_text="# Stop Test",
                contract=contract,
                repo_root=Path(temp_dir),
            )

            app_dir = Path(temp_dir) / "generated_apps" / app_slug
            request = PreviewRunRequest(
                run_id="test-run",
                app_slug=app_slug,
                generated_app_dir=app_dir,
                preview_command=["node", "server.js"],
                preferred_port=8789,
                repo_root=Path(temp_dir),
            )

            result = start_preview(request, runs_dir=runs_dir)
            original_port = result.port

            stop_result = stop_preview(result.record_path)

            self.assertEqual(stop_result["status"], "stopped")
            time.sleep(0.5)

            # Verify port is released
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("127.0.0.1", original_port))
            finally:
                sock.close()

    @unittest.skipUnless(CAN_BIND, "sandbox forbids socket.bind on 127.0.0.1")
    def test_wait_for_health_returns_ok_when_server_responds(self) -> None:
        from growth_dev.team.preview import wait_for_health

        # Start a minimal test server
        import http.server
        import threading

        class QuietHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), QuietHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            ok, message = wait_for_health(f"http://127.0.0.1:{port}/", timeout=2.0)
            self.assertTrue(ok)
            self.assertIn("200", message)
        finally:
            server.shutdown()

    def test_wait_for_health_returns_false_on_timeout(self) -> None:
        from growth_dev.team.preview import wait_for_health

        ok, message = wait_for_health("http://127.0.0.1:9999/nonexistent", timeout=0.5)

        self.assertFalse(ok)
        self.assertIn("timeout", message.lower())

    def test_list_active_previews_returns_running_previews(self) -> None:
        from growth_dev.team.preview import list_active_previews

        with tempfile.TemporaryDirectory() as temp_dir:
            runs_dir = Path(temp_dir) / "runs"
            run1_dir = runs_dir / "run1" / "preview"
            run2_dir = runs_dir / "run2" / "preview"
            run1_dir.mkdir(parents=True)
            run2_dir.mkdir(parents=True)

            (run1_dir / "preview_run_record.json").write_text(
                json.dumps({"run_id": "run1", "app_slug": "app1", "pid": 12345, "port": 8788, "stopped_at": None}),
                encoding="utf-8",
            )
            (run2_dir / "preview_run_record.json").write_text(
                json.dumps({"run_id": "run2", "app_slug": "app2", "pid": 12346, "port": 8789, "stopped_at": "2026-03-14T10:00:00Z"}),
                encoding="utf-8",
            )

            active = list_active_previews(runs_dir)

        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["run_id"], "run1")
        self.assertEqual(active[0]["app_slug"], "app1")


if __name__ == "__main__":
    unittest.main()
