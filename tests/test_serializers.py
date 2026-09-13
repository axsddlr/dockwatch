from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dockwatch.api.serializers import (
    deserialize_settings,
    serialize_settings,
    serialize_update_result,
)
from dockwatch.config import (
    MAX_HOOK_TIMEOUT_SECONDS,
    DockwatchConfig,
    HealthConfig,
    HookConfig,
    HookDefaultsConfig,
    PruneConfig,
)
from dockwatch.db import ManifestStore
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult


class SerializeUpdateResultTests(unittest.TestCase):
    def test_includes_display_ready_fields(self) -> None:
        info = ContainerInfo(
            name="bazarr",
            container_id="1",
            image_ref="lscr.io/linuxserver/bazarr:latest",
            registry=RegistryType.LSCR,
            namespace="linuxserver",
            image_name="bazarr",
            current_tag="latest",
            version_label="v1.5.4-ls334",
        )
        result = UpdateResult(
            container_info=info,
            latest_tag="v1.5.5-ls335",
            latest_version="v1.5.5-ls335",
            is_outdated=True,
            deployed_tag="latest",
            deployed_version="v1.5.4-ls334",
            deployed_digest="sha256:local",
            remote_tag="latest",
            remote_digest="sha256:remote",
            comparison_basis="digest",
        )

        data = serialize_update_result(result)

        self.assertEqual(data["deployed_display"], "latest (v1.5.4-ls334)")
        self.assertEqual(data["remote_display"], "v1.5.5-ls335 (sha256:remote)")

    def test_container_payload_includes_state_and_health_status(self) -> None:
        info = ContainerInfo(
            name="bazarr",
            container_id="1",
            image_ref="lscr.io/linuxserver/bazarr:latest",
            registry=RegistryType.LSCR,
            namespace="linuxserver",
            image_name="bazarr",
            current_tag="latest",
            state="running",
            health_status="healthy",
        )

        data = serialize_update_result(UpdateResult(container_info=info))

        self.assertEqual(data["container_info"]["state"], "running")
        self.assertEqual(data["container_info"]["health_status"], "healthy")


class SettingsSerializationTests(unittest.TestCase):
    def test_health_settings_round_trip(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(path=Path(tmp_dir) / "test.db")
            config = DockwatchConfig(
                health=HealthConfig(
                    enabled=True,
                    interval_seconds=120,
                    auto_restart=True,
                    restart_unhealthy_only=False,
                    unhealthy_after_samples=5,
                    max_restarts_per_hour=10,
                    cooldown_seconds=600,
                    notify_transitions=False,
                )
            )
            restored = deserialize_settings(serialize_settings(config, store), DockwatchConfig(), store)
            self.assertEqual(restored.health, config.health)

    def test_hooks_settings_round_trip(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(path=Path(tmp_dir) / "test.db")
            config = DockwatchConfig(
                hooks={
                    "web": HookConfig(
                        pre_update=["echo hi"], post_update=["echo bye"], pre_stop=["echo stop"]
                    ),
                    "empty": HookConfig(),
                },
                hook_defaults=HookDefaultsConfig(timeout_seconds=90, user="app", workdir="/srv"),
            )
            restored = deserialize_settings(serialize_settings(config, store), DockwatchConfig(), store)
            self.assertEqual(restored.hooks, config.hooks)
            self.assertEqual(restored.hook_defaults, config.hook_defaults)

    def test_prune_settings_round_trip(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(path=Path(tmp_dir) / "test.db")
            config = DockwatchConfig(
                prune=PruneConfig(
                    enabled=True,
                    interval_hours=48,
                    run_on_startup=True,
                    mode="unused",
                    keep_recent_per_repository=5,
                    notify=True,
                )
            )
            restored = deserialize_settings(serialize_settings(config, store), DockwatchConfig(), store)
            self.assertEqual(restored.prune, config.prune)


class TestSettingsHooksGate:
    def _setup_client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        import dockwatch.config as config_module
        import dockwatch.db as db_module
        from dockwatch.api import deps as deps_module
        from dockwatch.api import rate_limit
        from dockwatch.api.app import create_app

        # The PUT /settings rate limiter is a module-global bucket shared across
        # the whole test session; clear it so each settings test starts fresh and
        # does not 429 once the cumulative 10-per-60s budget is exhausted.
        rate_limit._buckets.clear()

        config_path = tmp_path / "config.toml"
        db_path = tmp_path / "manifests.db"
        monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
        monkeypatch.setattr(config_module.load_config, "__defaults__", (config_path,))
        monkeypatch.setattr(config_module.save_config, "__defaults__", (config_path,))
        monkeypatch.setattr(db_module, "STATE_DB_PATH", db_path)
        monkeypatch.setattr(db_module.ManifestStore.__init__, "__defaults__", (db_path,))

        config = config_module.load_config(config_path)
        config.auth.username = "admin"
        config.auth.password_hash = config_module.hash_password("correct-password")
        config.hooks = {
            "web": HookConfig(pre_update=["echo hi"], post_update=["echo bye"]),
            "db": HookConfig(pre_rollback=["echo rollback"]),
        }
        config.hook_defaults = HookDefaultsConfig(timeout_seconds=30, user="app", workdir="/srv")
        config_module.save_config(config, config_path)

        store = db_module.ManifestStore()
        store.create_user("admin", config.auth.password_hash, "admin")
        deps_module._store = db_module.ManifestStore(path=db_path)

        client = TestClient(create_app())
        client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"})
        return client, config_module, config_path

    def test_put_settings_rejects_changed_hooks_when_gate_off(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DOCKWATCH_ENABLE_HOOKS", raising=False)
        client, _, _ = self._setup_client(tmp_path, monkeypatch)
        response = client.put(
            "/api/settings",
            json={
                "hooks": {
                    "web": {
                        "pre_update": ["echo changed"],
                        "post_update": [],
                        "pre_stop": [],
                        "pre_rollback": [],
                        "post_rollback": [],
                    },
                },
            },
        )
        assert response.status_code == 422
        assert "DOCKWATCH_ENABLE_HOOKS" in response.json()["detail"]

    def test_put_settings_allows_unchanged_hooks_when_gate_off(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DOCKWATCH_ENABLE_HOOKS", raising=False)
        client, config_module, config_path = self._setup_client(tmp_path, monkeypatch)
        from dockwatch.api import deps as deps_module

        current = serialize_settings(config_module.load_config(config_path), deps_module._store)
        response = client.put("/api/settings", json=current)
        assert response.status_code == 200

    def test_put_settings_allows_changed_hooks_when_gate_on(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
        client, _, _ = self._setup_client(tmp_path, monkeypatch)
        response = client.put(
            "/api/settings",
            json={
                "hooks": {
                    "web": {
                        "pre_update": ["echo changed"],
                        "post_update": [],
                        "pre_stop": [],
                        "pre_rollback": [],
                        "post_rollback": [],
                    },
                },
            },
        )
        assert response.status_code == 200

    def test_put_settings_removes_container_hooks_when_gate_on(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
        client, config_module, config_path = self._setup_client(tmp_path, monkeypatch)
        # Omit "db" from the body: with wholesale-replace semantics this must
        # remove db's hooks, not silently keep them (merge-in-place bug).
        response = client.put(
            "/api/settings",
            json={
                "hooks": {
                    "web": {
                        "pre_update": ["echo hi"],
                        "post_update": ["echo bye"],
                        "pre_stop": [],
                        "pre_rollback": [],
                        "post_rollback": [],
                    },
                },
            },
        )
        assert response.status_code == 200
        assert set(response.json()["hooks"]) == {"web"}
        loaded = config_module.load_config(config_path)
        assert set(loaded.hooks) == {"web"}

    def test_put_settings_rejects_hooks_removal_when_gate_off(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DOCKWATCH_ENABLE_HOOKS", raising=False)
        client, _, _ = self._setup_client(tmp_path, monkeypatch)
        # Removing "db" (by omitting it) is itself a change, so the gate rejects.
        response = client.put(
            "/api/settings",
            json={
                "hooks": {
                    "web": {
                        "pre_update": ["echo hi"],
                        "post_update": ["echo bye"],
                        "pre_stop": [],
                        "pre_rollback": [],
                        "post_rollback": [],
                    },
                },
            },
        )
        assert response.status_code == 422
        assert "DOCKWATCH_ENABLE_HOOKS" in response.json()["detail"]

    def test_rejected_hooks_put_does_not_mutate_store(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DOCKWATCH_ENABLE_HOOKS", raising=False)
        client, _, _ = self._setup_client(tmp_path, monkeypatch)
        from dockwatch.api import deps as deps_module

        response = client.put(
            "/api/settings",
            json={
                "hooks": {
                    "web": {
                        "pre_update": ["echo changed"],
                        "post_update": [],
                        "pre_stop": [],
                        "pre_rollback": [],
                        "post_rollback": [],
                    },
                },
                "pinned": ["nginx"],
                "auto_update": ["web"],
            },
        )
        assert response.status_code == 422
        assert deps_module._store.get_pinned() == []
        assert deps_module._store.get_auto_update() == []

    def test_put_settings_normalizes_invalid_prune_mode(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("DOCKWATCH_ENABLE_HOOKS", raising=False)
        client, _, _ = self._setup_client(tmp_path, monkeypatch)
        response = client.put("/api/settings", json={"prune": {"mode": "bogus"}})
        assert response.status_code == 200
        assert response.json()["prune"]["mode"] == "dangling"

    def test_put_settings_clamps_hook_timeout_in_response(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
        client, config_module, config_path = self._setup_client(tmp_path, monkeypatch)
        response = client.put("/api/settings", json={"hook_defaults": {"timeout_seconds": 500}})
        assert response.status_code == 200
        assert response.json()["hook_defaults"]["timeout_seconds"] == MAX_HOOK_TIMEOUT_SECONDS
        assert config_module.load_config(config_path).hook_defaults.timeout_seconds == MAX_HOOK_TIMEOUT_SECONDS

    def test_put_settings_clamps_health_interval_in_response(self, tmp_path, monkeypatch) -> None:
        client, config_module, config_path = self._setup_client(tmp_path, monkeypatch)
        response = client.put("/api/settings", json={"health": {"interval_seconds": 5}})
        assert response.status_code == 200
        assert response.json()["health"]["interval_seconds"] == 10
        assert config_module.load_config(config_path).health.interval_seconds == 10

    def test_put_settings_clamps_prune_keep_recent_in_response(self, tmp_path, monkeypatch) -> None:
        client, config_module, config_path = self._setup_client(tmp_path, monkeypatch)
        response = client.put("/api/settings", json={"prune": {"keep_recent_per_repository": -1}})
        assert response.status_code == 200
        assert response.json()["prune"]["keep_recent_per_repository"] == 0
        assert config_module.load_config(config_path).prune.keep_recent_per_repository == 0


def test_hooks_changed_filters_blank_commands():
    from dockwatch.api.routes.settings import _hooks_changed

    clean = {
        "pre_update": ["echo hi"],
        "post_update": [],
        "pre_stop": [],
        "pre_rollback": [],
        "post_rollback": [],
    }
    stored_blanks = {
        "pre_update": ["", "  ", "echo hi"],
        "post_update": [],
        "pre_stop": [],
        "pre_rollback": [],
        "post_rollback": [],
    }
    defaults = {"timeout_seconds": 30, "user": "app", "workdir": "/srv"}

    # The dashboard's cleanHooks rewrites stored empty-string commands to [].
    # A blank on either side of the comparison must not register as a change.
    assert _hooks_changed({"hooks": {"web": clean}, "hook_defaults": defaults}, {"hooks": {"web": stored_blanks}, "hook_defaults": defaults}) is False
    assert _hooks_changed({"hooks": {"web": stored_blanks}, "hook_defaults": defaults}, {"hooks": {"web": clean}, "hook_defaults": defaults}) is False

    # A genuine command change is still a change.
    changed = dict(clean, pre_update=["echo changed"])
    assert _hooks_changed({"hooks": {"web": changed}, "hook_defaults": defaults}, {"hooks": {"web": clean}, "hook_defaults": defaults}) is True


if __name__ == "__main__":
    unittest.main()
