"""Login/logout/session-cookie authentication tests."""

from __future__ import annotations

import time


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


def test_login_succeeds_with_correct_credentials(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = _login(client)

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["username"] == "admin"
    assert data["role"] == "admin"
    assert "view_containers" in data["permissions"]
    assert "dockwatch_session" in response.cookies


def test_login_fails_with_wrong_password(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})

    assert response.status_code == 401
    assert "dockwatch_session" not in response.cookies


def test_login_fails_when_no_users_exist(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "anything"})

    assert response.status_code == 401


def test_lockout_after_repeated_failures(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    for _ in range(5):
        response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert response.status_code == 401

    locked_response = client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})
    assert locked_response.status_code == 429


def test_protected_route_rejects_without_cookie(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/api/containers")

    assert response.status_code == 401


def test_protected_route_accepts_valid_cookie(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    login = _login(client)
    assert login.status_code == 200

    response = client.get("/api/containers")
    assert response.status_code == 200


def test_protected_route_rejects_expired_cookie(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    from dockwatch.db import ManifestStore
    from dockwatch.config import load_config
    from dockwatch.api.security import _serializer, _COOKIE_NAME

    config = load_config(_config_path(tmp_path))
    store = ManifestStore()
    user = store.get_user_by_username("admin")
    token = _serializer(config.auth.secret_key).dumps({"u": "admin", "uid": user.id})
    client.cookies.set(_COOKIE_NAME, token)

    from dockwatch.api import security as security_module

    monkeypatch.setattr(security_module, "_MAX_AGE", 0)
    time.sleep(1.1)

    response = client.get("/api/containers")
    assert response.status_code == 401


def test_logout_clears_cookie(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)
    assert client.get("/api/containers").status_code == 200

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    response = client.get("/api/containers")
    assert response.status_code == 401


def test_websocket_rejects_without_cookie(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect("/ws"):
            raise AssertionError("expected the connection to be rejected")
    except WebSocketDisconnect:
        pass


def test_websocket_accepts_with_valid_cookie(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    login = _login(client)
    assert login.status_code == 200

    with client.websocket_connect("/ws") as ws:
        assert ws is not None


def test_debug_dist_requires_auth(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/debug/dist")

    assert response.status_code == 401


def test_session_status_reports_unauthenticated_without_cookie(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/api/auth/session")

    assert response.status_code == 401


def test_session_status_reports_authenticated_with_cookie(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert data["username"] == "admin"
    assert data["role"] == "admin"
    assert "view_containers" in data["permissions"]


# --- Registration tests ---

def test_first_registration_becomes_admin(monkeypatch, tmp_path) -> None:
    _patch_config_path(monkeypatch, tmp_path)
    _patch_db_path(monkeypatch, tmp_path)
    _reset_deps_store()

    from fastapi.testclient import TestClient
    from dockwatch.api import app as app_module
    from dockwatch.api.routes import auth as auth_module

    auth_module._failed_attempts.clear()
    client = TestClient(app_module.create_app())

    response = client.post("/api/auth/register", json={"username": "firstuser", "password": "secret123"})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["username"] == "firstuser"
    assert data["role"] == "admin"
    assert "manage_users" in data["permissions"]
    assert "dockwatch_session" in response.cookies


def test_fresh_install_register_then_use_app(monkeypatch, tmp_path) -> None:
    """Regression: on a fresh install with no config.toml credential, the
    first admin registers via the web and must be able to use the app on
    the very next request (previously 503'd on the stale password_hash check).
    """
    _patch_config_path(monkeypatch, tmp_path)
    _patch_db_path(monkeypatch, tmp_path)
    _reset_deps_store()

    from fastapi.testclient import TestClient
    from dockwatch.api import app as app_module
    from dockwatch.api.routes import auth as auth_module

    auth_module._failed_attempts.clear()
    client = TestClient(app_module.create_app())

    response = client.post("/api/auth/register", json={"username": "firstadmin", "password": "secret123"})
    assert response.status_code == 200

    response = client.get("/api/containers")
    assert response.status_code == 200

    response = client.get("/api/auth/session")
    assert response.json()["authenticated"] is True


def test_registration_disabled_after_first_user(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.post("/api/auth/register", json={"username": "second", "password": "secret123"})

    assert response.status_code == 403


def test_registration_allowed_when_env_var_set(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCKWATCH_ALLOW_REGISTRATION", "true")
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.post("/api/auth/register", json={"username": "second", "password": "secret123"})

    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "viewer"
    assert "manage_users" not in data["permissions"]


def test_registration_enabled_endpoint_first_user(monkeypatch, tmp_path) -> None:
    _patch_config_path(monkeypatch, tmp_path)
    _patch_db_path(monkeypatch, tmp_path)
    _reset_deps_store()

    from fastapi.testclient import TestClient
    from dockwatch.api import app as app_module

    client = TestClient(app_module.create_app())

    response = client.get("/api/auth/registration-enabled")
    assert response.status_code == 200
    assert response.json() == {"enabled": True}


def test_registration_enabled_endpoint_after_first_user(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/api/auth/registration-enabled")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}


def test_registration_enabled_endpoint_with_env_var(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCKWATCH_ALLOW_REGISTRATION", "true")
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/api/auth/registration-enabled")
    assert response.status_code == 200
    assert response.json() == {"enabled": True}


# --- Permission tests ---

def test_viewer_cannot_update_containers(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path, username="viewer", password="viewer123", role="viewer")
    client = _make_client(monkeypatch, tmp_path)

    login = _login(client, username="viewer", password="viewer123")
    assert login.status_code == 200

    # viewer can view containers
    assert client.get("/api/containers").status_code == 200

    # viewer cannot update
    response = client.post("/api/containers/nonexistent/update")
    assert response.status_code == 403

    # viewer cannot pin
    response = client.post("/api/containers/nonexistent/pin")
    assert response.status_code == 403

    # viewer cannot access settings
    response = client.get("/api/settings")
    assert response.status_code == 403

    # viewer cannot access environments
    response = client.get("/api/environments")
    assert response.status_code == 403

    # viewer cannot manage users
    response = client.get("/api/users")
    assert response.status_code == 403


def test_admin_can_access_everything(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    login = _login(client)
    assert login.status_code == 200

    # admin can view containers (empty cache, valid response)
    assert client.get("/api/containers").status_code == 200
    # admin can access settings
    assert client.get("/api/settings").status_code == 200
    # admin can access environments
    assert client.get("/api/environments").status_code == 200
    # admin can manage users
    assert client.get("/api/users").status_code == 200
    # admin can list roles
    assert client.get("/api/roles").status_code == 200


def test_role_change_takes_effect_immediately(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    login = _login(client)
    assert login.status_code == 200
    assert client.get("/api/settings").status_code == 200

    from dockwatch.db import ManifestStore
    store = ManifestStore()
    user = store.get_user_by_username("admin")
    store.update_user_role(user.id, "viewer")

    response = client.get("/api/settings")
    assert response.status_code == 403


# --- User/role management tests ---

def test_list_users(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    response = client.get("/api/users")
    assert response.status_code == 200
    users = response.json()
    assert len(users) == 1
    assert users[0]["username"] == "admin"
    assert users[0]["role_name"] == "admin"
    assert "password_hash" not in users[0]


def test_create_user_by_admin(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    response = client.post("/api/users", json={
        "username": "newuser",
        "password": "secret123",
        "role_name": "viewer",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["username"] == "newuser"
    assert data["role_name"] == "viewer"


def test_update_user_role(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    # Create a second admin so changing the first admin's role is safe
    client.post("/api/users", json={
        "username": "secondadmin",
        "password": "secret123",
        "role_name": "admin",
    })

    from dockwatch.db import ManifestStore
    store = ManifestStore()
    user = store.get_user_by_username("admin")

    response = client.patch(f"/api/users/{user.id}", json={"role_name": "viewer"})
    assert response.status_code == 200


def test_cannot_delete_self(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    from dockwatch.db import ManifestStore
    store = ManifestStore()
    user = store.get_user_by_username("admin")

    response = client.delete(f"/api/users/{user.id}")
    assert response.status_code == 409


def test_last_admin_protection(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    from dockwatch.db import ManifestStore
    store = ManifestStore()
    admin_user = store.get_user_by_username("admin")

    response = client.patch(f"/api/users/{admin_user.id}", json={"role_name": "viewer"})
    assert response.status_code == 409


def test_custom_role_create_and_assign(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    response = client.post("/api/roles", json={
        "name": "scanner",
        "permissions": ["view_containers", "scan_containers"],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "scanner"
    assert sorted(data["permissions"]) == ["scan_containers", "view_containers"]
    assert data["is_builtin"] is False


def test_cannot_create_builtin_role_name(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    response = client.post("/api/roles", json={
        "name": "admin",
        "permissions": ["view_containers"],
    })
    assert response.status_code == 409


def test_cannot_create_role_with_unknown_permission(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    response = client.post("/api/roles", json={
        "name": "bogus",
        "permissions": ["view_containers", "super_power"],
    })
    assert response.status_code == 422


def test_cannot_delete_builtin_role(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    response = client.delete("/api/roles/viewer")
    assert response.status_code == 422


def test_cannot_delete_role_assigned_to_user(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    client.post("/api/roles", json={
        "name": "temporary",
        "permissions": ["view_containers"],
    })

    # Create a second user assigned to the new role (not the admin)
    client.post("/api/users", json={
        "username": "tempuser",
        "password": "secret123",
        "role_name": "temporary",
    })

    response = client.delete("/api/roles/temporary")
    assert response.status_code == 409


def test_last_manage_users_with_custom_role(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    client.post("/api/roles", json={
        "name": "manager",
        "permissions": ["manage_users", "view_containers"],
    })

    client.post("/api/users", json={
        "username": "secondadmin",
        "password": "secret123",
        "role_name": "manager",
    })

    from dockwatch.db import ManifestStore
    store = ManifestStore()
    admin_user = store.get_user_by_username("admin")

    response = client.patch(f"/api/users/{admin_user.id}", json={"role_name": "viewer"})
    assert response.status_code == 200


def test_update_custom_role_permissions(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    client.post("/api/roles", json={
        "name": "editor",
        "permissions": ["view_containers"],
    })

    response = client.patch("/api/roles/editor", json={
        "permissions": ["view_containers", "update_containers"],
    })
    assert response.status_code == 200
    data = response.json()
    assert "update_containers" in data["permissions"]


def test_cannot_edit_builtin_role(monkeypatch, tmp_path) -> None:
    _seed_user(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    _login(client)

    response = client.patch("/api/roles/admin", json={
        "permissions": ["view_containers"],
    })
    assert response.status_code == 422


# --- Migration tests ---

def test_auth_migration_creates_user_from_config(monkeypatch, tmp_path) -> None:
    _patch_config_path(monkeypatch, tmp_path)
    _patch_db_path(monkeypatch, tmp_path)

    from dockwatch.config import load_config, save_config, hash_password, migrate_auth_config_to_users
    from dockwatch.db import ManifestStore

    config = load_config(_config_path(tmp_path))
    config.auth.username = "migrated-admin"
    config.auth.password_hash = hash_password("migrated-pass")
    save_config(config, _config_path(tmp_path))

    store = ManifestStore()
    assert store.count_users() == 0

    migrate_auth_config_to_users(config, store)

    assert store.count_users() == 1
    user = store.get_user_by_username("migrated-admin")
    assert user is not None
    assert user.role_name == "admin"


def test_auth_migration_is_idempotent(monkeypatch, tmp_path) -> None:
    _patch_config_path(monkeypatch, tmp_path)
    _patch_db_path(monkeypatch, tmp_path)

    from dockwatch.config import load_config, save_config, hash_password, migrate_auth_config_to_users
    from dockwatch.db import ManifestStore

    config = load_config(_config_path(tmp_path))
    config.auth.username = "only-once"
    config.auth.password_hash = hash_password("only-pass")
    save_config(config, _config_path(tmp_path))

    store = ManifestStore()
    migrate_auth_config_to_users(config, store)
    migrate_auth_config_to_users(config, store)

    assert store.count_users() == 1
