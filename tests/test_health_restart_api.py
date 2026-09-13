"""Tests for the per-container health-restart API surface.

Covers the two routes added in Phase 4 (``POST``/``DELETE
/containers/{name}/health-restart``) plus the settings round-trip for the
``health_restart`` flag list.
"""

from __future__ import annotations


def _config_path(tmp_path):
    return tmp_path / "config.toml"


def _db_path(tmp_path):
    return tmp_path / "manifests.db"


def _patch_paths(monkeypatch, tmp_path):
    import dockwatch.config as config_module
    import dockwatch.db as db_module

    config_path = _config_path(tmp_path)
    db_path = _db_path(tmp_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config_module.load_config, "__defaults__", (config_path,))
    monkeypatch.setattr(config_module.save_config, "__defaults__", (config_path,))
    monkeypatch.setattr(db_module, "STATE_DB_PATH", db_path)
    monkeypatch.setattr(db_module.ManifestStore.__init__, "__defaults__", (db_path,))
    return config_path, db_path


def _seed_admin(monkeypatch, tmp_path):
    config_path, _db_path = _patch_paths(monkeypatch, tmp_path)

    from dockwatch.config import hash_password, load_config, save_config

    config = load_config(config_path)
    config.auth.username = "admin"
    config.auth.password_hash = hash_password("correct-password")
    save_config(config, config_path)

    from dockwatch.db import ManifestStore

    store = ManifestStore()
    try:
        store.create_user("admin", config.auth.password_hash, "admin")
    except ValueError:
        pass
    return store


def _make_client(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)

    from fastapi.testclient import TestClient

    from dockwatch.api import app as app_module
    from dockwatch.api import deps as deps_module
    from dockwatch.api.routes import auth as auth_module
    from dockwatch.db import STATE_DB_PATH, ManifestStore

    auth_module._failed_attempts.clear()
    deps_module._store = ManifestStore(path=STATE_DB_PATH)
    deps_module._results_cache = []

    return TestClient(app_module.create_app())


def _login(client, username="admin", password="correct-password"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_health_restart_requires_restart_containers_permission(monkeypatch, tmp_path):
    """POST /containers/{name}/health-restart returns 403 without restart_containers."""
    _seed_admin(monkeypatch, tmp_path)

    from dockwatch.config import hash_password
    from dockwatch.db import ManifestStore

    store = ManifestStore()
    if store.get_role("updater") is None:
        store.create_role("updater", ["update_containers"])
    store.create_user("updater_user", hash_password("correct-password"), "updater")

    client = _make_client(monkeypatch, tmp_path)
    _login(client, username="updater_user", password="correct-password")

    response = client.post("/api/containers/web/health-restart")

    assert response.status_code == 403


def test_health_restart_add_remove_round_trip(monkeypatch, tmp_path):
    """POST then DELETE /containers/{name}/health-restart round-trips the flag."""
    _seed_admin(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    response = client.post("/api/containers/web/health-restart")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "web" in data["health_restart"]

    response = client.delete("/api/containers/web/health-restart")
    assert response.status_code == 200
    assert "web" not in response.json()["health_restart"]

    # Removing a flag that is no longer set is a 404, mirroring auto-update.
    response = client.delete("/api/containers/web/health-restart")
    assert response.status_code == 404


def test_health_restart_in_settings_get_and_put(monkeypatch, tmp_path):
    """health_restart appears in GET /api/settings and is settable via PUT."""
    _seed_admin(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)
    _login(client)

    response = client.get("/api/settings")
    assert response.status_code == 200
    assert response.json()["health_restart"] == []

    response = client.put("/api/settings", json={"health_restart": ["web", "db"]})
    assert response.status_code == 200
    assert sorted(response.json()["health_restart"]) == ["db", "web"]

    response = client.get("/api/settings")
    assert sorted(response.json()["health_restart"]) == ["db", "web"]
