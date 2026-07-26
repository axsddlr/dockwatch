from __future__ import annotations


def test_static_frontend_does_not_mask_api_routes(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))

    import dockwatch.config as config_module
    import dockwatch.db as db_module

    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "manifests.db"
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config_module.load_config, "__defaults__", (config_path,))
    monkeypatch.setattr(db_module, "STATE_DB_PATH", db_path)
    monkeypatch.setattr(db_module.ManifestStore.__init__, "__defaults__", (db_path,))

    config = config_module.load_config(config_path)
    config.auth.username = "admin"
    config.auth.password_hash = config_module.hash_password("correct-password")
    config_module.save_config(config, config_path)

    store = db_module.ManifestStore()
    store.create_user("admin", config.auth.password_hash, "admin")

    from fastapi.testclient import TestClient
    from dockwatch.api import app as app_module
    from dockwatch.api import deps as deps_module

    deps_module._store = db_module.ManifestStore(path=db_path)

    dist_path = tmp_path / "dist"
    assets_path = dist_path / "assets"
    dist_path.mkdir()
    assets_path.mkdir()
    index_html = '<!doctype html><div id="root"></div>'
    (dist_path / "index.html").write_text(index_html, encoding="utf-8")
    (dist_path / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    (assets_path / "app.js").write_text("console.log('ok')", encoding="utf-8")

    monkeypatch.setattr(app_module, "_find_frontend_dist", lambda: dist_path)

    client = TestClient(app_module.create_app())
    client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})

    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    debug_response = client.get("/debug/dist")
    assert debug_response.status_code == 200
    assert debug_response.json()["mounted"] is True

    settings_api_response = client.get("/api/settings")
    assert settings_api_response.status_code == 200
    assert settings_api_response.headers["content-type"].startswith("application/json")

    root_response = client.get("/")
    assert root_response.status_code == 200
    assert root_response.text == index_html

    response = client.get("/settings")
    assert response.status_code == 200
    assert response.text == index_html

    root_file_response = client.get("/favicon.svg")
    assert root_file_response.status_code == 200
    assert root_file_response.text == "<svg></svg>"

    asset_response = client.get("/assets/app.js")
    assert asset_response.status_code == 200
    assert asset_response.text == "console.log('ok')"

    asset_response = client.get("/missing.js")
    assert asset_response.status_code == 404

    api_response = client.get("/api/missing")
    assert api_response.status_code == 404
    assert "root" not in api_response.text
