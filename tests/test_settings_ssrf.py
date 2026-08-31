from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from dockwatch.api.routes.settings import _validate_public_url


class ValidatePublicUrlTests(unittest.TestCase):
    def test_accepts_empty_url(self) -> None:
        self.assertEqual(_validate_public_url(""), "")
        self.assertEqual(_validate_public_url("   "), "")

    def test_rejects_non_http_scheme(self) -> None:
        with self.assertRaises(HTTPException):
            _validate_public_url("ftp://example.com/hook")
        with self.assertRaises(HTTPException):
            _validate_public_url("file:///etc/passwd")

    def test_rejects_literal_restricted_addresses(self) -> None:
        for url in (
            "http://127.0.0.1:5000/hook",
            "http://192.168.1.10/hook",
            "http://10.0.0.5/hook",
            "http://169.254.169.254/latest/meta-data/",
            "http://0.0.0.0/hook",
            "http://[::1]:5000/hook",
            "http://[fe80::1]/hook",
        ):
            with self.assertRaises(HTTPException):
                _validate_public_url(url)

    def test_accepts_literal_public_address(self) -> None:
        self.assertEqual(
            _validate_public_url("http://93.184.216.34/hook"),
            "http://93.184.216.34/hook",
        )

    def test_rejects_hostname_resolving_only_to_restricted_addresses(self) -> None:
        sockaddr = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))
        with patch(
            "dockwatch.api.routes.settings.socket.getaddrinfo",
            return_value=[sockaddr, (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
        ):
            with self.assertRaises(HTTPException):
                _validate_public_url("http://internal.example.test/hook")

    def test_accepts_hostname_with_any_public_address(self) -> None:
        # Round-robin hosts that also carry a public address must pass even
        # when one A record is private.
        sockaddr = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))
        with patch(
            "dockwatch.api.routes.settings.socket.getaddrinfo",
            return_value=[sockaddr, (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))],
        ):
            self.assertEqual(
                _validate_public_url("http://roundrobin.example.test/hook"),
                "http://roundrobin.example.test/hook",
            )

    def test_rejects_unresolvable_hostname(self) -> None:
        with patch(
            "dockwatch.api.routes.settings.socket.getaddrinfo",
            side_effect=OSError("no address"),
        ):
            with self.assertRaises(HTTPException):
                _validate_public_url("http://no-such-host.invalid/hook")


class TestPutSettingsSsrftests:
    def test_put_settings_rejects_private_webhook(self, tmp_path, monkeypatch) -> None:
        import dockwatch.config as config_module
        import dockwatch.db as db_module
        from fastapi.testclient import TestClient

        from dockwatch.api import deps as deps_module
        from dockwatch.api.app import create_app

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
        deps_module._store = db_module.ManifestStore(path=db_path)

        client = TestClient(create_app())
        client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})

        response = client.put("/api/settings", json={"webhook_url": "http://127.0.0.1:9999/hook"})
        assert response.status_code == 422

        # Clearing the field is still allowed.
        response = client.put("/api/settings", json={"webhook_url": ""})
        assert response.status_code == 200
