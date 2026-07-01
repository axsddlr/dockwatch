from __future__ import annotations

from pathlib import Path


def test_frontend_route_falls_back_to_index_without_masking_missing_assets(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))

    from fastapi.testclient import TestClient
    from dockwatch.api import app as app_module

    dist_path = tmp_path / "dist"
    dist_path.mkdir()
    index_html = '<!doctype html><div id="root"></div>'
    (dist_path / "index.html").write_text(index_html, encoding="utf-8")

    monkeypatch.setattr(app_module, "_find_frontend_dist", lambda: dist_path)

    client = TestClient(app_module.create_app())

    response = client.get("/settings")
    assert response.status_code == 200
    assert response.text == index_html

    asset_response = client.get("/missing.js")
    assert asset_response.status_code == 404

    api_response = client.get("/api/missing")
    assert api_response.status_code == 404
    assert "root" not in api_response.text
