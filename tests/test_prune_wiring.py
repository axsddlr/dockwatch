from __future__ import annotations

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

    from dockwatch.config import hash_password, load_config, save_config

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
    from dockwatch.db import STATE_DB_PATH, ManifestStore

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


def _enable_prune(monkeypatch, tmp_path):
    from dockwatch.config import load_config, save_config

    config = load_config(_config_path(tmp_path))
    config.prune.enabled = True
    save_config(config, _config_path(tmp_path))
    return config


def test_preview_requires_prune_images(monkeypatch, tmp_path):
    _seed_role_user(monkeypatch, tmp_path, "viewer", "viewer", ["view_containers"])
    client = _make_client(monkeypatch, tmp_path)
    _login(client, username="viewer", password="correct-password")

    response = client.get("/api/prune/preview")

    assert response.status_code == 403


def test_preview_422_when_disabled(monkeypatch, tmp_path):
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    response = client.get("/api/prune/preview")

    assert response.status_code == 422


def test_preview_mutates_nothing(monkeypatch, tmp_path):
    _seed_user(monkeypatch, tmp_path)
    _enable_prune(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    from dockwatch.docker_client import ImageInfo

    dangling = ImageInfo(image_id="sha256:abc", repo_tags=[], created=100, size_bytes=50)
    monkeypatch.setattr("dockwatch.api.routes.prune.docker_client.list_images", lambda: [dangling])
    monkeypatch.setattr("dockwatch.api.routes.prune.docker_client.in_use_image_ids", lambda: set())
    remove_mock = MagicMock()
    monkeypatch.setattr("dockwatch.docker_client.remove_image", remove_mock)

    response = client.get("/api/prune/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["preview"]["candidates"][0]["image_id"] == "sha256:abc"
    remove_mock.assert_not_called()


def test_images_requires_prune_images(monkeypatch, tmp_path):
    _seed_role_user(monkeypatch, tmp_path, "viewer", "viewer", ["view_containers"])
    client = _make_client(monkeypatch, tmp_path)
    _login(client, username="viewer", password="correct-password")

    response = client.post("/api/prune/images", json={})

    assert response.status_code == 403


def test_images_422_when_disabled(monkeypatch, tmp_path):
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    response = client.post("/api/prune/images", json={})

    assert response.status_code == 422


def test_images_executes_and_broadcasts(monkeypatch, tmp_path):
    _seed_user(monkeypatch, tmp_path)
    _enable_prune(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    from dockwatch.docker_client import ImageInfo

    dangling = ImageInfo(image_id="sha256:abc", repo_tags=[], created=100, size_bytes=50)
    monkeypatch.setattr("dockwatch.docker_client.list_images", lambda: [dangling])
    monkeypatch.setattr("dockwatch.docker_client.in_use_image_ids", lambda: set())
    remove_mock = MagicMock()
    monkeypatch.setattr("dockwatch.docker_client.remove_image", remove_mock)
    broadcast = AsyncMock()
    monkeypatch.setattr("dockwatch.api.routes.prune.manager.broadcast", broadcast)

    response = client.post("/api/prune/images", json={"mode": "dangling", "keep_recent": 0})

    assert response.status_code == 200
    assert response.json()["removed"] == ["sha256:abc"]
    remove_mock.assert_called_once_with("sha256:abc")
    names = [call.args[0] for call in broadcast.await_args_list]
    assert names == ["prune_started", "prune_complete"]


def test_prune_cli_dry_run_does_not_mutate(tmp_path):
    from typer.testing import CliRunner

    from dockwatch.config import AgentConfig, DockwatchConfig
    from dockwatch.db import ManifestStore
    from dockwatch.docker_client import ImageInfo
    from dockwatch.main import app

    config = DockwatchConfig()
    config.prune.enabled = True
    config.agents = [AgentConfig(name="pc1", url="http://pc1:8081", token="tok", enabled=True)]
    dangling = ImageInfo(image_id="sha256:abc", repo_tags=[], created=100, size_bytes=50)
    store = ManifestStore(path=tmp_path / "manifests.db")

    with patch("dockwatch.main.load_config", return_value=config), patch(
        "dockwatch.main.ManifestStore", lambda: store
    ), patch("dockwatch.main.list_images", return_value=[dangling]), patch(
        "dockwatch.main.in_use_image_ids", return_value=set()
    ), patch("dockwatch.main.prune_all", new=AsyncMock()) as prune_all_mock, patch(
        "dockwatch.prune.AgentClient"
    ) as agent_client_mock:
        result = CliRunner().invoke(app, ["prune", "--dry-run"])

    assert result.exit_code == 0
    assert "Dry run complete." in result.stdout
    prune_all_mock.assert_not_called()
    agent_client_mock.assert_not_called()


def test_prune_cli_reaches_agent_hosts(tmp_path):
    from typer.testing import CliRunner

    from dockwatch.config import AgentConfig, DockwatchConfig
    from dockwatch.db import ManifestStore
    from dockwatch.main import app

    config = DockwatchConfig()
    config.prune.enabled = True
    config.prune.mode = "dangling"
    config.prune.keep_recent_per_repository = 3
    config.agents = [AgentConfig(name="pc1", url="http://pc1:8081", token="tok", enabled=True)]
    store = ManifestStore(path=tmp_path / "manifests.db")

    fake_client = MagicMock()
    fake_client.prune_images = AsyncMock(return_value={"removed": ["x"], "failed": [], "reclaimed_bytes": 10})

    with patch("dockwatch.main.load_config", return_value=config), patch(
        "dockwatch.main.ManifestStore", lambda: store
    ), patch("dockwatch.main.list_images", return_value=[]), patch(
        "dockwatch.main.in_use_image_ids", return_value=set()
    ), patch("dockwatch.docker_client.list_images", return_value=[]), patch(
        "dockwatch.docker_client.in_use_image_ids", return_value=set()
    ), patch("dockwatch.prune.AgentClient", return_value=fake_client):
        result = CliRunner().invoke(app, ["prune", "--yes"])

    assert result.exit_code == 0
    fake_client.prune_images.assert_awaited_once_with(mode="dangling", keep_recent=3)


def test_prune_cli_states_agent_hosts_are_pruned_too(tmp_path):
    from typer.testing import CliRunner

    from dockwatch.config import AgentConfig, DockwatchConfig
    from dockwatch.db import ManifestStore
    from dockwatch.docker_client import ImageInfo
    from dockwatch.main import app

    config = DockwatchConfig()
    config.prune.enabled = True
    config.agents = [AgentConfig(name="pc1", url="http://pc1:8081", token="tok", enabled=True)]
    dangling = ImageInfo(image_id="sha256:abc", repo_tags=[], created=100, size_bytes=50)
    store = ManifestStore(path=tmp_path / "manifests.db")

    with patch("dockwatch.main.load_config", return_value=config), patch(
        "dockwatch.main.ManifestStore", lambda: store
    ), patch("dockwatch.main.list_images", return_value=[dangling]), patch(
        "dockwatch.main.in_use_image_ids", return_value=set()
    ):
        result = CliRunner().invoke(app, ["prune", "--dry-run"])

    assert result.exit_code == 0
    assert "agent" in result.stdout.lower()
    assert "not enumerated" in result.stdout


def test_images_threads_mode_and_keep_overrides_to_every_agent(monkeypatch, tmp_path):
    from dockwatch.config import AgentConfig, load_config, save_config

    _seed_user(monkeypatch, tmp_path)
    _enable_prune(monkeypatch, tmp_path)
    config = load_config(_config_path(tmp_path))
    config.prune.mode = "dangling"
    config.prune.keep_recent_per_repository = 3
    config.agents = [
        AgentConfig(name="pc1", url="http://pc1:8081", token="tok", enabled=True),
        AgentConfig(name="pc2", url="http://pc2:8081", token="tok", enabled=True),
    ]
    save_config(config, _config_path(tmp_path))

    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    monkeypatch.setattr("dockwatch.docker_client.list_images", list)
    monkeypatch.setattr("dockwatch.docker_client.in_use_image_ids", lambda: set())

    fake_agent = MagicMock()
    fake_agent.prune_images = AsyncMock(return_value={"removed": [], "failed": [], "reclaimed_bytes": 0})
    monkeypatch.setattr("dockwatch.prune.AgentClient", lambda **kwargs: fake_agent)

    response = client.post("/api/prune/images", json={"mode": "unused", "keep_recent": 0})

    assert response.status_code == 200
    assert len(fake_agent.prune_images.await_args_list) == 2
    for call in fake_agent.prune_images.await_args_list:
        assert call.kwargs == {"mode": "unused", "keep_recent": 0}


def test_images_more_generous_override_honoured_for_agents(monkeypatch, tmp_path):
    from dockwatch.config import AgentConfig, load_config, save_config

    _seed_user(monkeypatch, tmp_path)
    _enable_prune(monkeypatch, tmp_path)
    config = load_config(_config_path(tmp_path))
    config.prune.mode = "unused"
    config.prune.keep_recent_per_repository = 1
    config.agents = [AgentConfig(name="pc1", url="http://pc1:8081", token="tok", enabled=True)]
    save_config(config, _config_path(tmp_path))

    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    monkeypatch.setattr("dockwatch.docker_client.list_images", list)
    monkeypatch.setattr("dockwatch.docker_client.in_use_image_ids", lambda: set())

    fake_agent = MagicMock()
    fake_agent.prune_images = AsyncMock(return_value={"removed": [], "failed": [], "reclaimed_bytes": 0})
    monkeypatch.setattr("dockwatch.prune.AgentClient", lambda **kwargs: fake_agent)

    response = client.post("/api/prune/images", json={"mode": "dangling", "keep_recent": 10})

    assert response.status_code == 200
    fake_agent.prune_images.assert_awaited_once_with(mode="dangling", keep_recent=10)


class PruneSchedulerWiringTests(unittest.IsolatedAsyncioTestCase):
    async def _created_task_count(self, enabled: bool) -> int:
        from dockwatch.api.app import _lifespan
        from dockwatch.config import DockwatchConfig

        config = DockwatchConfig()
        config.prune.enabled = enabled

        created: list = []

        class FakeTask:
            def cancel(self) -> None:
                pass

            def __await__(self):
                if False:
                    yield None

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

    async def test_scheduled_prune_task_created_only_when_enabled(self) -> None:
        self.assertEqual(await self._created_task_count(False), 2)
        self.assertEqual(await self._created_task_count(True), 3)


class DaemonPruneWiringTests(unittest.IsolatedAsyncioTestCase):
    async def _created_task_count(self, *, health: bool, prune: bool) -> int:
        from dockwatch.config import DockwatchConfig
        from dockwatch.main import _run_daemon

        config = DockwatchConfig()
        config.health.enabled = health
        config.prune.enabled = prune

        runner = MagicMock()
        runner.serve_forever = AsyncMock(return_value=None)

        created: list = []

        class FakeTask:
            def __await__(self):
                if False:
                    yield None

        def _fake_create_task(coro):
            coro.close()
            created.append(coro)
            return FakeTask()

        async def _fake_gather(*tasks):
            return None

        with patch("asyncio.create_task", side_effect=_fake_create_task), patch(
            "asyncio.gather", side_effect=_fake_gather
        ):
            await _run_daemon(config, MagicMock(), runner, lambda m: None)

        return len(created)

    async def test_daemon_prune_task_created_only_when_enabled(self) -> None:
        self.assertEqual(await self._created_task_count(health=False, prune=False), 1)
        self.assertEqual(await self._created_task_count(health=False, prune=True), 2)

    async def test_daemon_health_task_created_only_when_enabled(self) -> None:
        self.assertEqual(await self._created_task_count(health=True, prune=False), 2)
        self.assertEqual(await self._created_task_count(health=True, prune=True), 3)


if __name__ == "__main__":
    import unittest

    unittest.main()
