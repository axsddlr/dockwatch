"""Login/logout/session-cookie authentication tests."""

from __future__ import annotations

import time


def _make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    from fastapi.testclient import TestClient
    from dockwatch.api import app as app_module
    from dockwatch.api.routes import auth as auth_module

    # TestClient always reports the same client host ("testclient"), so the
    # module-level lockout dict (keyed by client IP in production) must be
    # reset per test, or an earlier test's failed attempts leak into this one.
    auth_module._failed_attempts.clear()

    return TestClient(app_module.create_app())


def _config_path(tmp_path):
    return tmp_path / "config.toml"


def _patch_config_path(monkeypatch, tmp_path):
    # dockwatch.config.CONFIG_PATH is a module-level constant, and
    # load_config's `path: Path = CONFIG_PATH` binds that value into the
    # function's __defaults__ at *function definition* time (module import),
    # not at call time. monkeypatch.setattr on the CONFIG_PATH name alone
    # does not change an already-bound default. Every route/require_auth
    # call resolves load_config()'s default via that frozen tuple, so the
    # only way to redirect the app under test is to patch the bound default
    # directly.
    import dockwatch.config as config_module

    path = _config_path(tmp_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", path)
    monkeypatch.setattr(config_module.load_config, "__defaults__", (path,))
    return path


def _make_client(monkeypatch, tmp_path):
    path = _patch_config_path(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient
    from dockwatch.api import app as app_module
    from dockwatch.api.routes import auth as auth_module

    # TestClient always reports the same client host ("testclient"), so the
    # module-level lockout dict (keyed by client IP in production) must be
    # reset per test, or an earlier test's failed attempts leak into this one.
    auth_module._failed_attempts.clear()

    return TestClient(app_module.create_app())


def _seed_credentials(monkeypatch, tmp_path, username: str = "admin", password: str = "correct-password"):
    path = _patch_config_path(monkeypatch, tmp_path)
    from dockwatch.config import load_config, save_config, hash_password

    config = load_config(path)
    config.auth.username = username
    config.auth.password_hash = hash_password(password)
    save_config(config, path)


def test_login_succeeds_with_correct_credentials(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "username": "admin"}
    assert "dockwatch_session" in response.cookies


def test_login_fails_with_wrong_password(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})

    assert response.status_code == 401
    assert "dockwatch_session" not in response.cookies


def test_login_fails_when_no_credentials_configured(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "anything"})

    assert response.status_code == 503


def test_lockout_after_repeated_failures(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    for _ in range(5):
        response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert response.status_code == 401

    locked_response = client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})
    assert locked_response.status_code == 429


def test_protected_route_rejects_without_cookie(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/api/containers")

    assert response.status_code == 401


def test_protected_route_accepts_valid_cookie(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})
    assert login.status_code == 200

    response = client.get("/api/containers")
    assert response.status_code == 200


def test_protected_route_rejects_expired_cookie(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    from dockwatch.config import load_config
    from dockwatch.api.security import _serializer, _COOKIE_NAME

    config = load_config(_config_path(tmp_path))
    token = _serializer(config.auth.secret_key).dumps({"u": "admin"})
    client.cookies.set(_COOKIE_NAME, token)

    from dockwatch.api import security as security_module

    monkeypatch.setattr(security_module, "_MAX_AGE", 0)
    time.sleep(1.1)

    response = client.get("/api/containers")
    assert response.status_code == 401


def test_logout_clears_cookie(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})
    assert client.get("/api/containers").status_code == 200

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    response = client.get("/api/containers")
    assert response.status_code == 401


def test_websocket_rejects_without_cookie(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect("/ws"):
            raise AssertionError("expected the connection to be rejected")
    except WebSocketDisconnect:
        pass


def test_websocket_accepts_with_valid_cookie(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})
    assert login.status_code == 200

    with client.websocket_connect("/ws") as ws:
        assert ws is not None


def test_debug_dist_requires_auth(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/debug/dist")

    assert response.status_code == 401


def test_session_status_reports_unauthenticated_without_cookie(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}


def test_session_status_reports_authenticated_with_cookie(monkeypatch, tmp_path) -> None:
    _seed_credentials(monkeypatch, tmp_path)
    client = _make_client(monkeypatch, tmp_path)

    client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "username": "admin"}
