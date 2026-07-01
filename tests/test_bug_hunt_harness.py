"""Bug-hunt harness 2026-07-01 — reproduces bugs found during systematic audit.

Each test asserts the CORRECT behavior, so it FAILS while the bug exists and
passes once the fix lands. See tasks/bug-hunt-2026-07-01.md for the full list.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import DockerException
from typer.testing import CliRunner

from dockwatch.api.ws import ConnectionManager
from dockwatch.config import DockwatchConfig, ComposeProjectConfig
from dockwatch.db import ManifestStore
from dockwatch.docker_client import get_image_id, get_running_containers
from dockwatch.trivy import _TrivyScanArgs, _scan_one
from dockwatch.updater import UpdatePlan, _execute_compose_update, _execute_plain_update


class _FakeWebSocket:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[str] = []

    async def send_text(self, message: str) -> None:
        if self.fail:
            raise RuntimeError("connection closed")
        self.sent.append(message)


class TestWsBroadcast:
    """Fix verified: api/ws.py:28 — broadcast() references undefined `results`; never sends."""

    def test_broadcast_delivers_to_all_clients(self):
        manager = ConnectionManager()
        good_a = _FakeWebSocket()
        good_b = _FakeWebSocket()
        manager.active = [good_a, good_b]

        asyncio.run(manager.broadcast("check_started", {"x": 1}))

        expected = json.dumps({"type": "check_started", "payload": {"x": 1}})
        assert good_a.sent == [expected]
        assert good_b.sent == [expected]

    def test_broadcast_prunes_dead_connections(self):
        manager = ConnectionManager()
        good = _FakeWebSocket()
        dead = _FakeWebSocket(fail=True)
        manager.active = [good, dead]

        asyncio.run(manager.broadcast("check_complete", {}))

        assert good.sent, "healthy client should still receive the message"
        assert dead not in manager.active, "dead connection should be pruned"
        assert good in manager.active


class TestTrivyTimeoutKillsProcess:
    """Fix verified: trivy.py:106-112 — timeout returns without killing the subprocess."""

    def test_timed_out_scan_kills_subprocess(self):
        spawned: list[asyncio.subprocess.Process] = []
        real_exec = asyncio.create_subprocess_exec

        async def capturing_exec(*args, **kwargs):
            proc = await real_exec(*args, **kwargs)
            spawned.append(proc)
            return proc

        args = _TrivyScanArgs(
            image_ref="example:latest",
            binary=sys.executable,
            severity=["HIGH"],
            scanners=["vuln"],
            timeout_seconds=1,
            skip_db_update=False,
        )

        sleeper_cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
        with patch("dockwatch.trivy._build_cmd", return_value=sleeper_cmd), patch(
            "dockwatch.trivy.asyncio.create_subprocess_exec", capturing_exec
        ):
            result = asyncio.run(_scan_one(args))

        assert result.error and "timed out" in result.error
        assert len(spawned) == 1
        proc = spawned[0]
        assert proc.returncode is not None, "subprocess must be terminated after timeout"


class TestUpdaterPlainFallback:
    """Fix verified: updater.py:282-284 — fallback containers.get raises uncaught DockerException."""

    def _plan(self) -> UpdatePlan:
        return UpdatePlan(
            container_name="ghost",
            container_id="deadbeef1234",
            source="local",
            mode="plain",
            allowed=True,
            image_ref="nginx:latest",
            deployed_display="1.0",
            remote_display="1.1",
        )

    def test_missing_container_returns_failure_not_exception(self):
        client = MagicMock()
        client.containers.get.side_effect = DockerException("no such container")
        with patch("dockwatch.updater._docker_client", return_value=client):
            result = _execute_plain_update(self._plan())
        assert result.success is False
        assert result.mode == "plain"

    def test_client_closed_on_failure(self):
        client = MagicMock()
        client.containers.get.side_effect = DockerException("no such container")
        with patch("dockwatch.updater._docker_client", return_value=client):
            _execute_plain_update(self._plan())
        assert client.close.called, "docker client must be closed on all paths"


class TestDockerClientClose:
    """Fix verified: docker_client.py:221-271 — docker clients never closed (fd leak in daemon)."""

    def test_get_running_containers_closes_client(self):
        client = MagicMock()
        client.containers.list.return_value = []
        with patch("dockwatch.docker_client.docker.from_env", return_value=client):
            containers = get_running_containers()
        assert containers == []
        assert client.close.called

    def test_get_image_id_closes_client(self):
        client = MagicMock()
        container = MagicMock()
        container.image.id = "sha256:abc123"
        client.containers.get.return_value = container
        with patch("dockwatch.docker_client.docker.from_env", return_value=client):
            image_id = get_image_id("web")
        assert image_id == "abc123"
        assert client.close.called

    def test_get_image_id_closes_client_on_lookup_error(self):
        client = MagicMock()
        client.containers.get.side_effect = DockerException("gone")
        with patch("dockwatch.docker_client.docker.from_env", return_value=client):
            assert get_image_id("web") is None
        assert client.close.called


class TestTrivyCacheCorruption:
    """Fix verified: db.py:181-185 — unguarded json.loads / TrivyFinding(**f) on cached rows."""

    def _store_with_row(self, tmp_path: Path, scan_json: str) -> ManifestStore:
        store = ManifestStore(tmp_path / "state.sqlite3")
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(store.path) as conn:
            conn.execute(
                """
                INSERT INTO trivy_scan_cache (
                    image_id, image_ref, scan_json,
                    critical_count, high_count, medium_count, low_count, scanned_at
                ) VALUES (?, ?, ?, 0, 0, 0, 0, ?)
                """,
                ("img1", "nginx:latest", scan_json, now),
            )
        return store

    def test_corrupted_json_treated_as_cache_miss(self, tmp_path: Path):
        store = self._store_with_row(tmp_path, "{this is not json")
        assert store.trivy_cache_get("img1") is None

    def test_unknown_fields_treated_as_cache_miss(self, tmp_path: Path):
        store = self._store_with_row(tmp_path, json.dumps([{"bogus_field": 1}]))
        assert store.trivy_cache_get("img1") is None

    def test_valid_cache_row_still_returned(self, tmp_path: Path):
        payload = json.dumps([
            {
                "vulnerability_id": "CVE-2026-0001",
                "pkg_name": "openssl",
                "installed_version": "1.0",
                "fixed_version": "1.1",
                "severity": "HIGH",
                "title": "test",
                "primary_url": "https://example.com",
                "target": "nginx:latest",
                "class_type": "os-pkgs",
            }
        ])
        store = self._store_with_row(tmp_path, payload)
        result = store.trivy_cache_get("img1")
        assert result is not None
        assert result.findings[0].vulnerability_id == "CVE-2026-0001"


class TestComposeUpdateTimeout:
    """Fix verified: updater.py:362,370 — compose subprocess.run has no timeout; can hang forever."""

    def _plan_and_config(self, tmp_path: Path) -> tuple[UpdatePlan, DockwatchConfig]:
        plan = UpdatePlan(
            container_name="web",
            container_id="deadbeef1234",
            source="local",
            mode="compose",
            allowed=True,
            image_ref="nginx:latest",
            deployed_display="1.0",
            remote_display="1.1",
            compose_project="proj",
            compose_service="web",
        )
        config = DockwatchConfig(
            compose_projects={"proj": ComposeProjectConfig(workdir=str(tmp_path))}
        )
        return plan, config

    def test_subprocess_run_called_with_timeout(self, tmp_path: Path):
        plan, config = self._plan_and_config(tmp_path)
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("dockwatch.updater.subprocess.run", return_value=completed) as run_mock:
            result = _execute_compose_update(plan, config)
        assert result.success is True
        for call in run_mock.call_args_list:
            assert call.kwargs.get("timeout"), "subprocess.run must set a timeout"

    def test_hanging_compose_returns_failure(self, tmp_path: Path):
        plan, config = self._plan_and_config(tmp_path)
        with patch(
            "dockwatch.updater.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="docker compose", timeout=1),
        ):
            result = _execute_compose_update(plan, config)
        assert result.success is False
        assert "time" in result.message.lower()


class TestWebhookUrlMasking:
    """Fix verified: main.py:411-413 — `config list` echoes webhook URLs with embedded tokens."""

    def test_config_list_masks_webhook_tokens(self):
        from dockwatch.main import app

        config = DockwatchConfig(
            webhook_url="https://hooks.example.com/notify?token=SUPERSECRET123",
            discord_webhook="https://discord.com/api/webhooks/1234/ABCDTOKEN",
            ntfy_url="https://ntfy.sh/SECRETTOPIC",
        )
        runner = CliRunner()
        with patch("dockwatch.main.load_config", return_value=config):
            result = runner.invoke(app, ["config", "list"])
        assert result.exit_code == 0
        assert "SUPERSECRET123" not in result.output
        assert "ABCDTOKEN" not in result.output
        assert "SECRETTOPIC" not in result.output
