from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from dockwatch.agent.protocol import deserialize_container_info, serialize_container_info
from dockwatch.agent.server import create_agent_app
from dockwatch.config import AgentConfig, DockwatchConfig
from dockwatch.db import ManifestStore
from dockwatch.integrations.agent import AgentClient, AgentError
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.sources import discover_agents
from dockwatch.updater import UpdateExecutionResult, build_rollback_plan, build_update_plan, execute_agent_rollback, execute_agent_update


class MockResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.request = httpx.Request("GET", "https://agent.test")

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self.request, response=httpx.Response(self.status_code))


class MockAsyncClient:
    def __init__(self, responses: list[MockResponse]):
        self._responses = responses
        self.calls: list[tuple[str, str | None, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def _next(self):
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get(self, url: str, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self._next()

    async def post(self, url: str, **kwargs):
        self.calls.append(("post", url, kwargs))
        return self._next()

    async def delete(self, url: str, **kwargs):
        self.calls.append(("delete", url, kwargs))
        return self._next()


class AgentProtocolTests(unittest.TestCase):
    def test_round_trip_preserves_fields(self) -> None:
        info = ContainerInfo(
            name="web",
            container_id="abcdef123456",
            image_ref="nginx:1.0.0",
            registry=RegistryType.DOCKERHUB,
            namespace="library",
            image_name="nginx",
            current_tag="1.0.0",
            labels={"com.docker.compose.project": "media", "org.opencontainers.image.version": "1.0.0"},
            version_label="1.0.0",
            repo_digest="sha256:abc",
            watch_enabled=False,
            pinned_override=True,
            include_tags_override=["^1\\."],
            update_delay_days_override=7,
            compose_project="media",
            compose_service="web",
        )
        restored = deserialize_container_info(serialize_container_info(info))
        self.assertEqual(restored.name, "web")
        self.assertEqual(restored.registry, RegistryType.DOCKERHUB)
        self.assertEqual(restored.version_label, "1.0.0")
        self.assertEqual(restored.repo_digest, "sha256:abc")
        self.assertIs(restored.watch_enabled, False)
        self.assertIs(restored.pinned_override, True)
        self.assertEqual(restored.include_tags_override, ["^1\\."])
        self.assertEqual(restored.update_delay_days_override, 7)
        self.assertEqual(restored.compose_service, "web")
        # source/environment are central-side; protocol does not carry them
        self.assertEqual(restored.source, "local")
        self.assertIsNone(restored.environment_id)

    def test_deserialize_tolerates_bad_registry(self) -> None:
        restored = deserialize_container_info({"name": "x", "registry": "bogus"})
        self.assertEqual(restored.registry, RegistryType.UNKNOWN)


class AgentClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_health(self) -> None:
        with patch(
            "dockwatch.integrations.agent.httpx.AsyncClient",
            return_value=MockAsyncClient([MockResponse(200, {"ok": True, "version": "0.11.0", "docker": "ok"})]),
        ):
            client = AgentClient(base_url="http://agent.test", token="secret")
            health = await client.health()
        self.assertEqual(health["docker"], "ok")

    async def test_list_containers_returns_items(self) -> None:
        with patch(
            "dockwatch.integrations.agent.httpx.AsyncClient",
            return_value=MockAsyncClient([MockResponse(200, {"containers": [{"name": "web"}]})]),
        ):
            items = await AgentClient(base_url="http://agent.test", token="secret").list_containers()
        self.assertEqual(items, [{"name": "web"}])

    async def test_list_containers_rejects_missing_key(self) -> None:
        with patch(
            "dockwatch.integrations.agent.httpx.AsyncClient",
            return_value=MockAsyncClient([MockResponse(200, {"nope": []})]),
        ):
            with self.assertRaises(AgentError):
                await AgentClient(base_url="http://agent.test", token="secret").list_containers()

    async def test_update_posts_image_ref(self) -> None:
        mock = MockAsyncClient([MockResponse(200, {"ok": True, "message": "updated"})])
        with patch("dockwatch.integrations.agent.httpx.AsyncClient", return_value=mock):
            payload = await AgentClient(base_url="http://agent.test", token="secret").update_container(
                "abc123", "nginx:1.2.0"
            )
        self.assertTrue(payload["ok"])
        self.assertEqual(mock.calls[0][0], "post")
        self.assertIn("/containers/abc123/update", mock.calls[0][1])
        self.assertEqual(mock.calls[0][2]["json"], {"image_ref": "nginx:1.2.0"})

    async def test_restart_sends_bearer_token(self) -> None:
        mock = MockAsyncClient([MockResponse(204)])
        with patch("dockwatch.integrations.agent.httpx.AsyncClient", return_value=mock):
            await AgentClient(base_url="http://agent.test", token="s3cret-test-token-16chars").restart_container("abc123")
        headers = mock.calls[0][2]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer s3cret-test-token-16chars")

    async def test_http_error_raises_agent_error(self) -> None:
        with patch(
            "dockwatch.integrations.agent.httpx.AsyncClient",
            return_value=MockAsyncClient([MockResponse(401)]),
        ):
            with self.assertRaises(AgentError):
                await AgentClient(base_url="http://agent.test", token="secret").restart_container("abc123")

    async def test_retries_once_on_connection_error(self) -> None:
        request = httpx.Request("GET", "https://agent.test")
        mock = MockAsyncClient([httpx.ConnectError("refused", request=request), MockResponse(204)])
        with patch("dockwatch.integrations.agent.httpx.AsyncClient", return_value=mock), patch(
            "dockwatch.integrations.agent.asyncio.sleep", new=AsyncMock(),
        ):
            await AgentClient(base_url="http://agent.test", token="secret").restart_container("abc123")
        self.assertEqual(len(mock.calls), 2)

    async def test_does_not_retry_on_http_status_error(self) -> None:
        mock = MockAsyncClient([MockResponse(401)])
        with patch("dockwatch.integrations.agent.httpx.AsyncClient", return_value=mock):
            with self.assertRaises(AgentError):
                await AgentClient(base_url="http://agent.test", token="secret").restart_container("abc123")
        self.assertEqual(len(mock.calls), 1)


def _make_result(**kwargs) -> UpdateResult:
    container_kwargs = dict(
        name="web",
        container_id="abcdef123456",
        image_ref="nginx:1.0.0",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name="nginx",
        current_tag="1.0.0",
        source="agent",
        environment_id="media-pc",
    )
    container_kwargs.update(kwargs.pop("container_overrides", {}))
    fields = dict(
        container_info=ContainerInfo(**container_kwargs),
        is_outdated=True,
        deployed_tag="1.0.0",
        remote_tag="1.1.0",
        comparison_basis="version",
    )
    fields.update(kwargs)
    return UpdateResult(**fields)


class AgentUpdatePlanTests(unittest.TestCase):
    def test_agent_update_plan_targets_new_tag(self) -> None:
        plan = build_update_plan(_make_result(), DockwatchConfig())
        self.assertTrue(plan.allowed)
        self.assertEqual(plan.mode, "agent-update")
        self.assertEqual(plan.image_ref, "nginx:1.1.0")
        self.assertEqual(plan.environment_id, "media-pc")

    def test_agent_update_floating_tag_keeps_ref(self) -> None:
        plan = build_update_plan(
            _make_result(
                container_overrides={"current_tag": "latest", "image_ref": "nginx:latest"},
                remote_tag="latest",
                comparison_basis="digest",
            ),
            DockwatchConfig(),
        )
        self.assertTrue(plan.allowed)
        self.assertEqual(plan.image_ref, "nginx:latest")

    def test_agent_compose_managed_is_blocked(self) -> None:
        plan = build_update_plan(
            _make_result(container_overrides={"compose_project": "media", "compose_service": "web"}),
            DockwatchConfig(),
        )
        self.assertFalse(plan.allowed)
        self.assertIn("compose-managed", plan.reason or "")

    def test_agent_rollback_plan_reverts_tag(self) -> None:
        # The container was just updated to 1.1.0 (per history), so its
        # deployed tag matches `new_tag` and rollback reverts to 1.0.0.
        plan = build_rollback_plan(
            _make_result(container_overrides={"current_tag": "1.1.0", "image_ref": "nginx:1.1.0"}),
            DockwatchConfig(),
            old_tag="1.0.0",
            new_tag="1.1.0",
        )
        self.assertTrue(plan.allowed)
        self.assertEqual(plan.mode, "agent-rollback")
        self.assertEqual(plan.image_ref, "nginx:1.0.0")

    def test_agent_update_blocked_when_not_outdated(self) -> None:
        plan = build_update_plan(_make_result(is_outdated=False), DockwatchConfig())
        self.assertFalse(plan.allowed)
        self.assertIn("not marked outdated", plan.reason or "")


class AgentExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_agent_update_dispatches_to_client(self) -> None:
        config = DockwatchConfig(agents=[AgentConfig(name="media-pc", url="http://media-pc:8081", token="tok")])
        plan = build_update_plan(_make_result(), config)
        mock_client = MagicMock()
        mock_client.update_container = AsyncMock(return_value={"ok": True, "message": "updated", "details": ["pulled"]})
        with patch("dockwatch.updater.AgentClient", return_value=mock_client):
            result = await execute_agent_update(plan, config)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "updated")
        self.assertEqual(result.details, ["pulled"])
        mock_client.update_container.assert_awaited_once_with("abcdef123456", "nginx:1.1.0")

    async def test_execute_agent_update_missing_agent(self) -> None:
        config = DockwatchConfig(agents=[])
        plan = build_update_plan(_make_result(), config)
        result = await execute_agent_update(plan, config)
        self.assertFalse(result.success)
        self.assertIn("not configured", result.message)

    async def test_execute_agent_rollback_dispatches(self) -> None:
        config = DockwatchConfig(agents=[AgentConfig(name="media-pc", url="http://media-pc:8081", token="tok")])
        plan = build_rollback_plan(
            _make_result(container_overrides={"current_tag": "1.1.0", "image_ref": "nginx:1.1.0"}),
            config,
            old_tag="1.0.0",
            new_tag="1.1.0",
        )
        mock_client = MagicMock()
        mock_client.rollback_container = AsyncMock(return_value={"ok": False, "message": "pull failed"})
        with patch("dockwatch.updater.AgentClient", return_value=mock_client):
            result = await execute_agent_rollback(plan, config)
        self.assertFalse(result.success)
        mock_client.rollback_container.assert_awaited_once_with("abcdef123456", "nginx:1.0.0")


class AgentDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_discover_agents_maps_containers_and_isolates_errors(self) -> None:
        config = DockwatchConfig(
            agents=[
                AgentConfig(name="pc1", url="http://pc1:8081", token="t1"),
                AgentConfig(name="pc2", url="http://pc2:8081", token="t2"),
                AgentConfig(name="off", url="http://off:8081", token="t3", enabled=False),
            ]
        )
        fake_client = MagicMock()
        fake_client.list_containers = AsyncMock(
            side_effect=[
                [{"name": "web", "image_ref": "nginx:1.0.0", "registry": "dockerhub", "namespace": "library", "image_name": "nginx", "current_tag": "1.0.0"}],
                AgentError("boom"),
            ]
        )
        with patch("dockwatch.sources.AgentClient", return_value=fake_client):
            result = await discover_agents(config)

        self.assertEqual(len(result.containers), 1)
        info = result.containers[0]
        self.assertEqual(info.name, "web")
        self.assertEqual(info.source, "agent")
        self.assertEqual(info.environment_id, "pc1")
        self.assertEqual(info.environment_name, "pc1")
        self.assertEqual(len(result.errors), 1)
        self.assertIn("pc2", result.errors[0])


class AgentServerTests(unittest.TestCase):
    def _app(self, token: str = "s3cret-test-token-16chars"):
        return TestClient(create_agent_app(token))

    def _fake_container(self, *, labels=None, image_ref="nginx:1.0.0", name="web", container_id="abcdef123456"):
        class FakeImage:
            attrs = {"RepoDigests": ["sha256:abc"]}

        container = type("FakeContainer", (), {})()
        container.name = name
        container.id = container_id
        container.image = FakeImage()
        container.attrs = {
            "Config": {"Labels": labels or {}, "Image": image_ref},
            "Id": container_id,
            "State": {"Running": True},
            "HostConfig": {},
            "Mounts": [],
        }

        def restart(timeout=10):
            pass

        def remove(force=False):
            pass

        def logs(tail=200, timestamps=True):
            return b"line1\nline2\n"

        container.restart = restart
        container.remove = remove
        container.logs = logs
        return container

    def _fake_client(self, container):
        class FakeImages:
            def __init__(self):
                self.removed = []

            def remove(self, image_id, force=False):
                if image_id == "missing":
                    import docker

                    raise docker.errors.ImageNotFound("no such image")
                self.removed.append(image_id)

        class FakeContainers:
            def __init__(self, container):
                self._container = container

            def get(self, container_id):
                if self._container is not None and self._container.id.startswith(container_id):
                    return self._container
                import docker

                raise docker.errors.NotFound("no such container")

        class FakeDockerClient:
            def __init__(self, container):
                self.containers = FakeContainers(container)
                self.images = FakeImages()

            def ping(self):
                pass

            def close(self):
                pass

        return FakeDockerClient(container)

    def test_requires_token(self) -> None:
        client = self._app()
        self.assertEqual(client.get("/api/agent/v1/health").status_code, 401)
        self.assertEqual(client.get("/api/agent/v1/health", headers={"Authorization": "Bearer wrong"}).status_code, 401)

    def test_rejects_short_token(self) -> None:
        with self.assertRaises(ValueError):
            create_agent_app("short")

    def test_lockout_after_repeated_auth_failures(self) -> None:
        client = self._app()
        for _ in range(10):
            client.get("/api/agent/v1/health", headers={"Authorization": "Bearer wrong"})
        response = client.get("/api/agent/v1/health", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(response.status_code, 429)

    def test_delete_image_not_found_returns_404(self) -> None:
        client = self._app()
        with patch("dockwatch.agent.server.get_docker_client", return_value=self._fake_client(None)):
            response = client.delete(
                "/api/agent/v1/images/missing",
                headers={"Authorization": "Bearer s3cret-test-token-16chars"},
            )
        self.assertEqual(response.status_code, 404)

    def test_health(self) -> None:
        client = self._app()
        with patch("dockwatch.agent.server.get_docker_client", return_value=self._fake_client(None)):
            response = client.get("/api/agent/v1/health", headers={"Authorization": "Bearer s3cret-test-token-16chars"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["docker"], "ok")

    def test_list_containers(self) -> None:
        client = self._app()
        info = ContainerInfo(
            name="web", container_id="abcdef123456", image_ref="nginx:1.0.0",
            registry=RegistryType.DOCKERHUB, namespace="library", image_name="nginx", current_tag="1.0.0",
        )
        with patch("dockwatch.agent.server.get_running_containers", return_value=[info]):
            response = client.get("/api/agent/v1/containers", headers={"Authorization": "Bearer s3cret-test-token-16chars"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["containers"][0]["name"], "web")
        self.assertEqual(response.json()["containers"][0]["registry"], "dockerhub")

    def test_update_recreates_container(self) -> None:
        client = self._app()
        container = self._fake_container()
        with patch("dockwatch.agent.server.get_docker_client", return_value=self._fake_client(container)), patch(
            "dockwatch.agent.server._execute_plain_update",
            return_value=UpdateExecutionResult(True, "plain", "updated", details=["pulled nginx:1.2.0"]),
        ) as exec_mock:
            response = client.post(
                "/api/agent/v1/containers/abcdef123456/update",
                headers={"Authorization": "Bearer s3cret-test-token-16chars"},
                json={"image_ref": "nginx:1.2.0"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        plan = exec_mock.call_args.args[0]
        self.assertEqual(plan.image_ref, "nginx:1.2.0")

    def test_update_rejects_compose_managed(self) -> None:
        client = self._app()
        container = self._fake_container(
            labels={"com.docker.compose.project": "media", "com.docker.compose.service": "web"}
        )
        with patch("dockwatch.agent.server.get_docker_client", return_value=self._fake_client(container)):
            response = client.post(
                "/api/agent/v1/containers/abcdef123456/update",
                headers={"Authorization": "Bearer s3cret-test-token-16chars"},
                json={"image_ref": "nginx:1.2.0"},
            )
        self.assertEqual(response.status_code, 422)

    def test_update_404_for_unknown_container(self) -> None:
        client = self._app()
        with patch("dockwatch.agent.server.get_docker_client", return_value=self._fake_client(None)):
            response = client.post(
                "/api/agent/v1/containers/deadbeef1234/update",
                headers={"Authorization": "Bearer s3cret-test-token-16chars"},
                json={"image_ref": "nginx:1.2.0"},
            )
        self.assertEqual(response.status_code, 404)

    def test_restart_and_delete_and_logs(self) -> None:
        client = self._app()
        container = self._fake_container()
        with patch("dockwatch.agent.server.get_docker_client", return_value=self._fake_client(container)):
            restart = client.post("/api/agent/v1/containers/abcdef123456/restart", headers={"Authorization": "Bearer s3cret-test-token-16chars"})
            delete = client.delete("/api/agent/v1/containers/abcdef123456?force=true", headers={"Authorization": "Bearer s3cret-test-token-16chars"})
            logs = client.get("/api/agent/v1/containers/abcdef123456/logs?tail=50", headers={"Authorization": "Bearer s3cret-test-token-16chars"})
        self.assertEqual(restart.status_code, 200)
        self.assertEqual(delete.status_code, 200)
        self.assertEqual(logs.status_code, 200)
        self.assertIn("line1", logs.json()["logs"])


class UpdateHistoryMigrationTests(unittest.TestCase):
    def test_legacy_update_history_accepts_agent_source(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "legacy.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE update_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    container_name TEXT NOT NULL,
                    action TEXT NOT NULL CHECK (action IN ('update', 'rollback', 'restart', 'delete_container', 'delete_image', 'digest_drift_detected')),
                    source TEXT NOT NULL CHECK (source IN ('local', 'portainer')),
                    environment_id TEXT,
                    old_tag TEXT,
                    new_tag TEXT,
                    old_digest TEXT,
                    new_digest TEXT,
                    status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
                    error TEXT,
                    user_id INTEGER,
                    username TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO update_history (container_name, action, source, status, created_at) VALUES (?, ?, ?, ?, ?)",
                ("web", "update", "local", "success", "2025-01-01T00:00:00+00:00"),
            )
            conn.commit()
            conn.close()

            store = ManifestStore(db_path)
            store.record_update_event(
                container_name="web2",
                action="update",
                source="agent",
                status="success",
                username="test",
                environment_id="media-pc",
            )
            records = store.list_update_history()
            sources = {r.source for r in records}
            self.assertIn("local", sources)
            self.assertIn("agent", sources)
            self.assertEqual(len(records), 2)


class AgentCentralRouteTests(unittest.TestCase):
    def test_restart_agent_container_via_route(self) -> None:
        import dockwatch.config as config_module
        import dockwatch.db as db_module
        from dockwatch.api import deps as deps_module
        from dockwatch.api.app import create_app

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config_path = tmp_path / "config.toml"
            db_path = tmp_path / "manifests.db"
            with patch.object(config_module, "CONFIG_PATH", config_path), patch.object(
                config_module.load_config, "__defaults__", (config_path,),
            ), patch.object(db_module, "STATE_DB_PATH", db_path), patch.object(
                db_module.ManifestStore.__init__, "__defaults__", (db_path,),
            ):
                config = config_module.load_config(config_path)
                config.auth.username = "admin"
                config.auth.password_hash = config_module.hash_password("correct-password")
                config.agents = [AgentConfig(name="media-pc", url="http://media-pc:8081", token="tok")]
                config_module.save_config(config, config_path)

                store = db_module.ManifestStore()
                store.create_user("admin", config.auth.password_hash, "admin")
                deps_module._store = db_module.ManifestStore(path=db_path)

                info = ContainerInfo(
                    name="web", container_id="abcdef123456", image_ref="nginx:1.0.0",
                    registry=RegistryType.DOCKERHUB, namespace="library", image_name="nginx", current_tag="1.0.0",
                    source="agent", environment_id="media-pc",
                )
                result = UpdateResult(container_info=info, is_outdated=True, remote_tag="1.1.0")
                deps_module.get_results_cache().append(result)

                mock_client = MagicMock()
                mock_client.restart_container = AsyncMock()

                client = TestClient(create_app())
                client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})
                with patch("dockwatch.api.routes.containers.AgentClient", return_value=mock_client):
                    response = client.post("/api/containers/web/restart")

                self.assertEqual(response.status_code, 200)
                mock_client.restart_container.assert_awaited_once_with("abcdef123456")
