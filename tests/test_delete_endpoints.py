"""Tests for DELETE /containers/{name} and DELETE /containers/{name}/image endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

from docker.errors import DockerException


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


def _reset_deps_store():
    from dockwatch.api import deps as deps_module
    from dockwatch.db import ManifestStore, STATE_DB_PATH

    deps_module._store = ManifestStore(path=STATE_DB_PATH)


def _make_client(monkeypatch, tmp_path):
    _patch_config_path(monkeypatch, tmp_path)
    _patch_db_path(monkeypatch, tmp_path)

    from fastapi.testclient import TestClient
    from dockwatch.api import app as app_module
    from dockwatch.api.routes import auth as auth_module

    auth_module._failed_attempts.clear()
    _reset_deps_store()

    return TestClient(app_module.create_app())


def _login(client, username="admin", password="correct-password"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _make_test_result(name: str, source: str = "local", environment_id: str | None = None):
    """Create a mock UpdateResult for testing."""
    from dockwatch.models import UpdateResult, ContainerInfo, RegistryType

    container_info = ContainerInfo(
        name=name,
        container_id=f"container-{name}",
        image_ref=f"test-image:{name}",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name="test-image",
        current_tag=name,
        source=source,
        environment_id=environment_id,
    )
    return UpdateResult(container_info=container_info)


# =============================================================================
# POST /containers/{name}/restart - restart_container
# =============================================================================


def test_restart_container_portainer_success(monkeypatch, tmp_path):
    """POST /containers/{name}/restart on portainer source calls PortainerClient.restart_container."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_portainer_restart = AsyncMock()
    mock_portainer_client = MagicMock()
    mock_portainer_client.restart_container = mock_portainer_restart
    mock_portainer_init = MagicMock(return_value=mock_portainer_client)
    monkeypatch.setattr("dockwatch.api.routes.containers.PortainerClient", mock_portainer_init)

    from dockwatch.config import load_config, PortainerConfig

    config = load_config(_config_path(tmp_path))
    config.portainer = PortainerConfig(url="http://portainer:9000", api_key="test-key", enabled=True)
    monkeypatch.setattr("dockwatch.api.routes.containers.get_config", lambda: config)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("restart-me", source="portainer", environment_id="5")
    deps_module._results_cache = [test_result]

    mock_broadcast = AsyncMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.manager.broadcast", mock_broadcast)

    response = client.post("/api/containers/restart-me/restart")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    mock_portainer_restart.assert_called_once_with(5, "container-restart-me")


def test_restart_container_non_portainer_rejected(monkeypatch, tmp_path):
    """POST /containers/{name}/restart on non-portainer source returns 422."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("local-restart", source="local")
    deps_module._results_cache = [test_result]

    response = client.post("/api/containers/local-restart/restart")

    assert response.status_code == 422
    data = response.json()
    assert "only supported for Portainer" in data["detail"]


def test_restart_container_portainer_disabled(monkeypatch, tmp_path):
    """POST /containers/{name}/restart returns 422 when portainer.enabled is False."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_portainer_restart = AsyncMock()
    mock_portainer_client = MagicMock()
    mock_portainer_client.restart_container = mock_portainer_restart
    mock_portainer_init = MagicMock(return_value=mock_portainer_client)
    monkeypatch.setattr("dockwatch.api.routes.containers.PortainerClient", mock_portainer_init)

    from dockwatch.config import load_config, PortainerConfig

    config = load_config(_config_path(tmp_path))
    config.portainer = PortainerConfig(url="http://portainer:9000", api_key="test-key", enabled=False)
    monkeypatch.setattr("dockwatch.api.routes.containers.get_config", lambda: config)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("restart-disabled", source="portainer", environment_id="5")
    deps_module._results_cache = [test_result]

    response = client.post("/api/containers/restart-disabled/restart")

    assert response.status_code == 422
    data = response.json()
    assert "disabled" in data["detail"].lower()
    mock_portainer_restart.assert_not_called()


# =============================================================================
# DELETE /containers/{name} - delete_container
# =============================================================================


def test_delete_container_local_success(monkeypatch, tmp_path):
    """DELETE /containers/{name} on local source calls docker_client.delete_container."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    # Mock the docker_client.delete_container function
    mock_delete = MagicMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.delete_container", mock_delete)

    # Mock the results cache to include our test container
    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("test-container", source="local")
    deps_module._results_cache = [test_result]

    # Mock websocket broadcast
    mock_broadcast = AsyncMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.manager.broadcast", mock_broadcast)

    response = client.delete("/api/containers/test-container")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["name"] == "test-container"

    # Verify docker_client.delete_container was called with correct args
    mock_delete.assert_called_once_with("test-container", force=False)

    # Verify websocket broadcast was called
    mock_broadcast.assert_called_once()
    broadcast_event, broadcast_payload = mock_broadcast.call_args[0]
    assert broadcast_event == "container_deleted"
    assert broadcast_payload["name"] == "test-container"

    # Verify container was removed from cache
    assert len(deps_module._results_cache) == 0


def test_delete_container_local_with_force(monkeypatch, tmp_path):
    """DELETE /containers/{name}?force=true passes force=True to docker_client."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_delete = MagicMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.delete_container", mock_delete)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("force-test", source="local")
    deps_module._results_cache = [test_result]

    mock_broadcast = AsyncMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.manager.broadcast", mock_broadcast)

    response = client.delete("/api/containers/force-test?force=true")

    assert response.status_code == 200
    mock_delete.assert_called_once_with("force-test", force=True)


def test_delete_container_local_docker_exception(monkeypatch, tmp_path):
    """DELETE /containers/{name} returns 502 when docker_client raises DockerException."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_delete = MagicMock(side_effect=DockerException("Container in use"))
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.delete_container", mock_delete)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("error-container", source="local")
    deps_module._results_cache = [test_result]

    response = client.delete("/api/containers/error-container")

    assert response.status_code == 502
    data = response.json()
    assert "Container in use" in data["detail"]


def test_delete_container_local_logs_action_success(monkeypatch, tmp_path):
    """DELETE /containers/{name} logs a successful delete_container action."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_delete = MagicMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.delete_container", mock_delete)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("logged-container", source="local")
    deps_module._results_cache = [test_result]

    mock_broadcast = AsyncMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.manager.broadcast", mock_broadcast)

    # Mock the store's record_update_event
    mock_record = MagicMock()
    deps_module._store.record_update_event = mock_record

    response = client.delete("/api/containers/logged-container")

    assert response.status_code == 200

    # Verify action was logged
    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args[1]
    assert call_kwargs["container_name"] == "logged-container"
    assert call_kwargs["action"] == "delete_container"
    assert call_kwargs["source"] == "local"
    assert call_kwargs["status"] == "success"
    assert call_kwargs["error"] is None


def test_delete_container_local_logs_action_failure(monkeypatch, tmp_path):
    """DELETE /containers/{name} logs a failed delete_container action with error."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    error_msg = "Container still running"
    mock_delete = MagicMock(side_effect=DockerException(error_msg))
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.delete_container", mock_delete)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("failed-delete", source="local")
    deps_module._results_cache = [test_result]

    # Mock the store's record_update_event
    mock_record = MagicMock()
    deps_module._store.record_update_event = mock_record

    response = client.delete("/api/containers/failed-delete")

    assert response.status_code == 502

    # Verify action was logged with error
    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args[1]
    assert call_kwargs["container_name"] == "failed-delete"
    assert call_kwargs["action"] == "delete_container"
    assert call_kwargs["source"] == "local"
    assert call_kwargs["status"] == "failed"
    assert call_kwargs["error"] == error_msg


def test_delete_container_portainer_success(monkeypatch, tmp_path):
    """DELETE /containers/{name} on portainer source calls PortainerClient.delete_container."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    # Mock PortainerClient
    mock_portainer_delete = AsyncMock()
    mock_portainer_client = MagicMock()
    mock_portainer_client.delete_container = mock_portainer_delete
    mock_portainer_init = MagicMock(return_value=mock_portainer_client)
    monkeypatch.setattr("dockwatch.api.routes.containers.PortainerClient", mock_portainer_init)

    # Mock the config
    from dockwatch.config import load_config, PortainerConfig

    config = load_config(_config_path(tmp_path))
    config.portainer = PortainerConfig(url="http://portainer:9000", api_key="test-key", enabled=True)
    monkeypatch.setattr("dockwatch.api.routes.containers.get_config", lambda: config)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("portainer-container", source="portainer", environment_id="5")
    deps_module._results_cache = [test_result]

    mock_broadcast = AsyncMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.manager.broadcast", mock_broadcast)

    response = client.delete("/api/containers/portainer-container")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True

    # Verify PortainerClient was initialized with correct config
    mock_portainer_init.assert_called_once_with(
        base_url="http://portainer:9000", api_key="test-key"
    )

    # Verify delete_container was called with correct args
    mock_portainer_delete.assert_called_once_with(5, "container-portainer-container", force=False)


def test_delete_container_portainer_with_force(monkeypatch, tmp_path):
    """DELETE /containers/{name}?force=true on portainer passes force=True."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_portainer_delete = AsyncMock()
    mock_portainer_client = MagicMock()
    mock_portainer_client.delete_container = mock_portainer_delete
    mock_portainer_init = MagicMock(return_value=mock_portainer_client)
    monkeypatch.setattr("dockwatch.api.routes.containers.PortainerClient", mock_portainer_init)

    from dockwatch.config import load_config, PortainerConfig

    config = load_config(_config_path(tmp_path))
    config.portainer = PortainerConfig(url="http://portainer:9000", api_key="test-key", enabled=True)
    monkeypatch.setattr("dockwatch.api.routes.containers.get_config", lambda: config)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("portainer-force", source="portainer", environment_id="5")
    deps_module._results_cache = [test_result]

    mock_broadcast = AsyncMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.manager.broadcast", mock_broadcast)

    response = client.delete("/api/containers/portainer-force?force=true")

    assert response.status_code == 200
    mock_portainer_delete.assert_called_once_with(5, "container-portainer-force", force=True)


def test_delete_container_portainer_missing_environment_id(monkeypatch, tmp_path):
    """DELETE /containers/{name} on portainer without environment_id returns 422."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    from dockwatch.api import deps as deps_module

    # Container with portainer source but no environment_id
    test_result = _make_test_result("portainer-no-env", source="portainer", environment_id=None)
    deps_module._results_cache = [test_result]

    response = client.delete("/api/containers/portainer-no-env")

    assert response.status_code == 422
    data = response.json()
    assert "no associated Portainer environment" in data["detail"]


def test_delete_container_portainer_error(monkeypatch, tmp_path):
    """DELETE /containers/{name} on portainer returns 502 when PortainerClient raises error."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    from dockwatch.integrations import PortainerError

    mock_portainer_delete = AsyncMock(side_effect=PortainerError("API error"))
    mock_portainer_client = MagicMock()
    mock_portainer_client.delete_container = mock_portainer_delete
    mock_portainer_init = MagicMock(return_value=mock_portainer_client)
    monkeypatch.setattr("dockwatch.api.routes.containers.PortainerClient", mock_portainer_init)

    from dockwatch.config import load_config, PortainerConfig

    config = load_config(_config_path(tmp_path))
    config.portainer = PortainerConfig(url="http://portainer:9000", api_key="test-key", enabled=True)
    monkeypatch.setattr("dockwatch.api.routes.containers.get_config", lambda: config)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("portainer-error", source="portainer", environment_id="5")
    deps_module._results_cache = [test_result]

    response = client.delete("/api/containers/portainer-error")

    assert response.status_code == 502
    data = response.json()
    assert "API error" in data["detail"]


def test_delete_container_portainer_logs_action_success(monkeypatch, tmp_path):
    """DELETE /containers/{name} on portainer logs successful action with environment_id."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_portainer_delete = AsyncMock()
    mock_portainer_client = MagicMock()
    mock_portainer_client.delete_container = mock_portainer_delete
    mock_portainer_init = MagicMock(return_value=mock_portainer_client)
    monkeypatch.setattr("dockwatch.api.routes.containers.PortainerClient", mock_portainer_init)

    from dockwatch.config import load_config, PortainerConfig

    config = load_config(_config_path(tmp_path))
    config.portainer = PortainerConfig(url="http://portainer:9000", api_key="test-key", enabled=True)
    monkeypatch.setattr("dockwatch.api.routes.containers.get_config", lambda: config)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("portainer-logged", source="portainer", environment_id="5")
    deps_module._results_cache = [test_result]

    mock_broadcast = AsyncMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.manager.broadcast", mock_broadcast)

    # Mock the store's record_update_event
    mock_record = MagicMock()
    deps_module._store.record_update_event = mock_record

    response = client.delete("/api/containers/portainer-logged")

    assert response.status_code == 200

    # Verify action was logged with portainer source and environment_id
    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args[1]
    assert call_kwargs["container_name"] == "portainer-logged"
    assert call_kwargs["action"] == "delete_container"
    assert call_kwargs["source"] == "portainer"
    assert call_kwargs["status"] == "success"
    assert call_kwargs["error"] is None
    assert call_kwargs["environment_id"] == "5"


def test_delete_container_portainer_disabled(monkeypatch, tmp_path):
    """DELETE /containers/{name} on portainer source returns 422 when portainer.enabled is False."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_portainer_delete = AsyncMock()
    mock_portainer_client = MagicMock()
    mock_portainer_client.delete_container = mock_portainer_delete
    mock_portainer_init = MagicMock(return_value=mock_portainer_client)
    monkeypatch.setattr("dockwatch.api.routes.containers.PortainerClient", mock_portainer_init)

    from dockwatch.config import load_config, PortainerConfig

    config = load_config(_config_path(tmp_path))
    config.portainer = PortainerConfig(url="http://portainer:9000", api_key="test-key", enabled=False)
    monkeypatch.setattr("dockwatch.api.routes.containers.get_config", lambda: config)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("portainer-disabled", source="portainer", environment_id="5")
    deps_module._results_cache = [test_result]

    response = client.delete("/api/containers/portainer-disabled")

    assert response.status_code == 422
    data = response.json()
    assert "disabled" in data["detail"].lower()
    mock_portainer_delete.assert_not_called()


def test_delete_container_not_found(monkeypatch, tmp_path):
    """DELETE /containers/{name} returns 404 when container not in results cache."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    from dockwatch.api import deps as deps_module

    deps_module._results_cache = []

    response = client.delete("/api/containers/nonexistent")

    assert response.status_code == 404
    data = response.json()
    assert "not found in results" in data["detail"]


def test_delete_container_permission_denied(monkeypatch, tmp_path):
    """DELETE /containers/{name} returns 403 for user without delete_containers permission."""
    _seed_user(monkeypatch, tmp_path, username="viewer", role="viewer")
    client = _make_client(monkeypatch, tmp_path)
    _login(client, username="viewer", password="correct-password")

    response = client.delete("/api/containers/any-container")

    assert response.status_code == 403


# =============================================================================
# DELETE /containers/{name}/image - delete_container_image
# =============================================================================


def test_delete_image_local_success(monkeypatch, tmp_path):
    """DELETE /containers/{name}/image on local source calls docker_client.delete_image."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    # Mock docker_client functions
    mock_get_image_id = MagicMock(return_value="sha256:abc123")
    mock_delete_image = MagicMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.get_image_id", mock_get_image_id)
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.delete_image", mock_delete_image)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("test-image-delete", source="local")
    deps_module._results_cache = [test_result]

    response = client.delete("/api/containers/test-image-delete/image")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["name"] == "test-image-delete"
    assert data["image_id"] == "sha256:abc123"

    # Verify get_image_id was called
    mock_get_image_id.assert_called_once_with("test-image-delete")

    # Verify delete_image was called with correct args
    mock_delete_image.assert_called_once_with("sha256:abc123", force=False)


def test_delete_image_local_with_force(monkeypatch, tmp_path):
    """DELETE /containers/{name}/image?force=true passes force=True."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_get_image_id = MagicMock(return_value="sha256:xyz789")
    mock_delete_image = MagicMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.get_image_id", mock_get_image_id)
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.delete_image", mock_delete_image)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("force-image", source="local")
    deps_module._results_cache = [test_result]

    response = client.delete("/api/containers/force-image/image?force=true")

    assert response.status_code == 200
    mock_delete_image.assert_called_once_with("sha256:xyz789", force=True)


def test_delete_image_local_docker_exception(monkeypatch, tmp_path):
    """DELETE /containers/{name}/image returns 502 when docker_client raises DockerException."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_get_image_id = MagicMock(return_value="sha256:abc123")
    mock_delete_image = MagicMock(side_effect=DockerException("Image still in use"))
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.get_image_id", mock_get_image_id)
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.delete_image", mock_delete_image)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("error-image", source="local")
    deps_module._results_cache = [test_result]

    response = client.delete("/api/containers/error-image/image")

    assert response.status_code == 502
    data = response.json()
    assert "Image still in use" in data["detail"]


def test_delete_image_local_no_image_id(monkeypatch, tmp_path):
    """DELETE /containers/{name}/image returns 404 when get_image_id returns None."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_get_image_id = MagicMock(return_value=None)
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.get_image_id", mock_get_image_id)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("no-image", source="local")
    deps_module._results_cache = [test_result]

    response = client.delete("/api/containers/no-image/image")

    assert response.status_code == 404
    data = response.json()
    assert "Could not resolve an image ID" in data["detail"]


def test_delete_image_local_logs_action_success(monkeypatch, tmp_path):
    """DELETE /containers/{name}/image logs successful delete_image action with image ID."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    mock_get_image_id = MagicMock(return_value="sha256:logged123")
    mock_delete_image = MagicMock()
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.get_image_id", mock_get_image_id)
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.delete_image", mock_delete_image)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("logged-image", source="local")
    deps_module._results_cache = [test_result]

    # Mock the store's record_update_event
    mock_record = MagicMock()
    deps_module._store.record_update_event = mock_record

    response = client.delete("/api/containers/logged-image/image")

    assert response.status_code == 200

    # Verify action was logged with delete_image action and image digest
    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args[1]
    assert call_kwargs["container_name"] == "logged-image"
    assert call_kwargs["action"] == "delete_image"
    assert call_kwargs["source"] == "local"
    assert call_kwargs["status"] == "success"
    assert call_kwargs["error"] is None
    assert call_kwargs["old_digest"] == "sha256:logged123"


def test_delete_image_local_logs_action_failure(monkeypatch, tmp_path):
    """DELETE /containers/{name}/image logs failed delete_image action with error and image ID."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    error_msg = "Image still in use by container"
    mock_get_image_id = MagicMock(return_value="sha256:failed123")
    mock_delete_image = MagicMock(side_effect=DockerException(error_msg))
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.get_image_id", mock_get_image_id)
    monkeypatch.setattr("dockwatch.api.routes.containers.docker_client.delete_image", mock_delete_image)

    from dockwatch.api import deps as deps_module

    test_result = _make_test_result("failed-image", source="local")
    deps_module._results_cache = [test_result]

    # Mock the store's record_update_event
    mock_record = MagicMock()
    deps_module._store.record_update_event = mock_record

    response = client.delete("/api/containers/failed-image/image")

    assert response.status_code == 502

    # Verify action was logged with error
    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args[1]
    assert call_kwargs["container_name"] == "failed-image"
    assert call_kwargs["action"] == "delete_image"
    assert call_kwargs["source"] == "local"
    assert call_kwargs["status"] == "failed"
    assert call_kwargs["error"] == error_msg
    assert call_kwargs["old_digest"] == "sha256:failed123"


def test_delete_image_portainer_source_rejected(monkeypatch, tmp_path):
    """DELETE /containers/{name}/image rejects portainer-sourced containers with 422."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    from dockwatch.api import deps as deps_module

    # Container with portainer source
    test_result = _make_test_result("portainer-image", source="portainer", environment_id="5")
    deps_module._results_cache = [test_result]

    response = client.delete("/api/containers/portainer-image/image")

    assert response.status_code == 422
    data = response.json()
    assert "only supported for local Docker containers" in data["detail"]


def test_delete_image_not_found(monkeypatch, tmp_path):
    """DELETE /containers/{name}/image returns 404 when container not in cache."""
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    from dockwatch.api import deps as deps_module

    deps_module._results_cache = []

    response = client.delete("/api/containers/nonexistent/image")

    assert response.status_code == 404
    data = response.json()
    assert "not found in results" in data["detail"]


def test_delete_image_permission_denied(monkeypatch, tmp_path):
    """DELETE /containers/{name}/image returns 403 for user without delete_containers permission."""
    _seed_user(monkeypatch, tmp_path, username="viewer", role="viewer")
    client = _make_client(monkeypatch, tmp_path)
    _login(client, username="viewer", password="correct-password")

    response = client.delete("/api/containers/any-container/image")

    assert response.status_code == 403
