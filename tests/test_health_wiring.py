from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def _config_path(tmp_path):
    return tmp_path / "config.toml"


def _db_path(tmp_path):
    return tmp_path / "manifests.db"


def _patch_config_path(monkeypatch, tmp_path):
    import dockwatch.config as config_module

    path = _config_path(tmp_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    monkeypatch.setattr(config_module.load_config, "__defaults__", (path,))
    return path


def _patch_db_path(monkeypatch, tmp_path):
    import dockwatch.db as db_module

    db_path = _db_path(tmp_path)
    monkeypatch.setattr(db_module, "STATE_DB_PATH", db_path)
    monkeypatch.setattr(db_module.ManifestStore.__init__, "__defaults__", (db_path,))
    return db_path


def _seed_user(monkeypatch, tmp_path, username="admin", password="correct-password", role="admin"):
    _patch_config_path(monkeypatch, tmp_path)
    _patch_db_path(monkeypatch, tmp_path)

    from dockwatch.config import load_config, save_config, hash_password

    config = load_config(_config_path(tmp_path))
    config.auth.username = username
    config.auth.password_hash = hash_password(password)
    save_config(config, _config_path(tmp_path))

    from dockwatch.db import ManifestStore

    store = ManifestStore()
    try:
        store.create_user(username, config.auth.password_hash, role)
    except ValueError:
        pass
    return store


def _seed_role_user(monkeypatch, tmp_path, username, role_name, permissions, password="correct-password"):
    _seed_user(monkeypatch, tmp_path)
    from dockwatch.config import hash_password
    from dockwatch.db import ManifestStore

    store = ManifestStore()
    if store.get_role(role_name) is None:
        store.create_role(role_name, permissions)
    store.create_user(username, hash_password(password), role_name)
    return store


def _reset_deps_store():
    from dockwatch.api import deps as deps_module
    from dockwatch.db import ManifestStore, STATE_DB_PATH

    deps_module._store = ManifestStore(path=STATE_DB_PATH)


def _make_client(monkeypatch, tmp_path):
    _patch_config_path(monkeypatch, tmp_path)
    _patch_db_path(monkeypatch, tmp_path)

    from dockwatch.api import app as app_module
    from dockwatch.api.routes import auth as auth_module

    auth_module._failed_attempts.clear()
    _reset_deps_store()

    return TestClient(app_module.create_app())


def _login(client, username="admin", password="correct-password"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_list_health_returns_states(monkeypatch, tmp_path):
    _seed_user(monkeypatch, tmp_path, username="viewer", role="viewer")
    client = _make_client(monkeypatch, tmp_path)
    _login(client, username="viewer", password="correct-password")

    response = client.get("/api/health/containers")

    assert response.status_code == 200
    assert response.json() == []


def test_list_health_requires_view_containers(monkeypatch, tmp_path):
    _seed_role_user(monkeypatch, tmp_path, "no_view", "no_view_role", ["manage_settings"])
    client = _make_client(monkeypatch, tmp_path)
    _login(client, username="no_view", password="correct-password")

    response = client.get("/api/health/containers")

    assert response.status_code == 403


def test_check_requires_restart_containers(monkeypatch, tmp_path):
    # A role that can manage settings but NOT restart containers must be
    # denied: this endpoint restarts containers when auto_restart is on.
    _seed_role_user(monkeypatch, tmp_path, "settings_only", "settings_only_role", ["manage_settings"])
    client = _make_client(monkeypatch, tmp_path)
    _login(client, username="settings_only", password="correct-password")

    response = client.post("/api/health/check")

    assert response.status_code == 403


def test_check_succeeds_with_restart_containers(monkeypatch, tmp_path):
    _seed_role_user(monkeypatch, tmp_path, "restarter", "restarter_role", ["restart_containers"])
    client = _make_client(monkeypatch, tmp_path)
    _login(client, username="restarter", password="correct-password")

    fake_monitor = MagicMock()
    fake_monitor.run_once = AsyncMock(return_value=True)
    monkeypatch.setattr("dockwatch.api.routes.health.HealthMonitor", lambda **kwargs: fake_monitor)

    response = client.post("/api/health/check")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    fake_monitor.run_once.assert_awaited_once_with(force=True)


def test_check_runs_cycle_with_force(monkeypatch, tmp_path):
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    fake_monitor = MagicMock()
    fake_monitor.run_once = AsyncMock(return_value=True)
    monkeypatch.setattr("dockwatch.api.routes.health.HealthMonitor", lambda **kwargs: fake_monitor)

    response = client.post("/api/health/check")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    fake_monitor.run_once.assert_awaited_once_with(force=True)


class HealthSchedulerWiringTests(unittest.IsolatedAsyncioTestCase):
    async def _created_task_count(self, enabled: bool) -> int:
        from dockwatch.api.app import _lifespan
        from dockwatch.config import DockwatchConfig

        config = DockwatchConfig()
        config.health.enabled = enabled

        created: list = []

        class FakeTask:
            def cancel(self) -> None:
                pass

            def __await__(self):
                if False:
                    yield None
                return None

        def _fake_create_task(coro):
            coro.close()
            created.append(coro)
            return FakeTask()

        with patch("dockwatch.api.app.load_config", return_value=config), patch(
            "dockwatch.api.app.get_store"
        ), patch("dockwatch.api.app.migrate_pinned_ignored_to_db"), patch(
            "dockwatch.api.app.migrate_auth_config_to_users"
        ), patch(
            "asyncio.create_task", side_effect=_fake_create_task
        ):
            cm = _lifespan(MagicMock())
            await cm.__aenter__()
            await cm.__aexit__(None, None, None)

        return len(created)

    async def test_scheduled_health_task_created_only_when_enabled(self) -> None:
        self.assertEqual(await self._created_task_count(False), 2)
        self.assertEqual(await self._created_task_count(True), 3)


def test_health_cli_json(tmp_path):
    from typer.testing import CliRunner

    from dockwatch.config import DockwatchConfig
    from dockwatch.db import ManifestStore
    from dockwatch.main import app
    from dockwatch.sources import SourceDiscoveryResult

    db_path = tmp_path / "manifests.db"
    store = ManifestStore(path=db_path)
    config = DockwatchConfig()
    config.health.enabled = True

    with patch("dockwatch.main.load_config", return_value=config), patch(
        "dockwatch.main.ManifestStore", lambda: store
    ), patch(
        "dockwatch.health.discover_containers",
        new=AsyncMock(return_value=SourceDiscoveryResult()),
    ):
        result = CliRunner().invoke(app, ["health", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_health_cli_dry_run_restarts_nothing(tmp_path):
    from typer.testing import CliRunner

    from dockwatch.config import DockwatchConfig
    from dockwatch.db import HealthStateRecord, ManifestStore
    from dockwatch.health import container_health_key
    from dockwatch.main import app
    from dockwatch.models import ContainerInfo, RegistryType
    from dockwatch.sources import SourceDiscoveryResult

    db_path = tmp_path / "manifests.db"
    store = ManifestStore(path=db_path)
    store.upsert_health_state(
        HealthStateRecord(
            container_key=container_health_key("local", None, "web"),
            container_name="web",
            source="local",
            state="running",
            health_status="unhealthy",
            consecutive_unhealthy=2,
        )
    )

    info = ContainerInfo(
        name="web",
        container_id="abcdef123456",
        image_ref="nginx:1.0.0",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name="nginx",
        current_tag="1.0.0",
        source="local",
        state="running",
        health_status="unhealthy",
        health_restart_override=True,
    )
    config = DockwatchConfig()
    config.health.enabled = True
    config.health.auto_restart = True
    config.health.unhealthy_after_samples = 2

    with patch("dockwatch.main.load_config", return_value=config), patch(
        "dockwatch.main.ManifestStore", lambda: store
    ), patch(
        "dockwatch.health.discover_containers",
        new=AsyncMock(return_value=SourceDiscoveryResult(containers=[info])),
    ), patch("dockwatch.health.docker_client.restart_container") as restart_mock:
        result = CliRunner().invoke(app, ["health", "--dry-run"])

    assert result.exit_code == 0
    restart_mock.assert_not_called()


def _restartable_health_setup(tmp_path):
    """Return (config, store, info) for a restartable unhealthy local container."""
    from dockwatch.config import DockwatchConfig
    from dockwatch.db import HealthStateRecord, ManifestStore
    from dockwatch.health import container_health_key
    from dockwatch.models import ContainerInfo, RegistryType

    store = ManifestStore(path=tmp_path / "manifests.db")
    store.upsert_health_state(
        HealthStateRecord(
            container_key=container_health_key("local", None, "web"),
            container_name="web",
            source="local",
            state="running",
            health_status="unhealthy",
            consecutive_unhealthy=2,
        )
    )

    info = ContainerInfo(
        name="web",
        container_id="abcdef123456",
        image_ref="nginx:1.0.0",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name="nginx",
        current_tag="1.0.0",
        source="local",
        state="running",
        health_status="unhealthy",
        health_restart_override=True,
    )
    config = DockwatchConfig()
    config.health.enabled = True
    config.health.auto_restart = True  # configured background restart would be on
    config.health.unhealthy_after_samples = 2
    return config, store, info


def test_health_cli_no_flags_does_not_restart(tmp_path):
    from typer.testing import CliRunner

    from dockwatch.main import app
    from dockwatch.sources import SourceDiscoveryResult

    config, store, info = _restartable_health_setup(tmp_path)

    with patch("dockwatch.main.load_config", return_value=config), patch(
        "dockwatch.main.ManifestStore", lambda: store
    ), patch(
        "dockwatch.health.discover_containers",
        new=AsyncMock(return_value=SourceDiscoveryResult(containers=[info])),
    ), patch("dockwatch.health.docker_client.restart_container") as restart_mock:
        result = CliRunner().invoke(app, ["health"])

    assert result.exit_code == 0
    restart_mock.assert_not_called()


def test_health_cli_restart_unhealthy_restarts(tmp_path):
    from typer.testing import CliRunner

    from dockwatch.main import app
    from dockwatch.sources import SourceDiscoveryResult

    config, store, info = _restartable_health_setup(tmp_path)

    with patch("dockwatch.main.load_config", return_value=config), patch(
        "dockwatch.main.ManifestStore", lambda: store
    ), patch(
        "dockwatch.health.discover_containers",
        new=AsyncMock(return_value=SourceDiscoveryResult(containers=[info])),
    ), patch("dockwatch.health.docker_client.restart_container") as restart_mock:
        result = CliRunner().invoke(app, ["health", "--restart-unhealthy"])

    assert result.exit_code == 0
    restart_mock.assert_called_once_with("web")


if __name__ == "__main__":
    unittest.main()
