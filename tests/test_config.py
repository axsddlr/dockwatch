from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from dockwatch import __version__ as dockwatch_version
from dockwatch.config import (
    AuthConfig,
    ComposeProjectConfig,
    DockwatchConfig,
    PortainerConfig,
    bootstrap_auth_from_env,
    hash_password,
    load_config,
    resolve_compose_file,
    save_config,
    validate_compose_project_config,
    verify_password,
)
from dockwatch.main import app
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.registry import check_all
from dockwatch.sources import SourceDiscoveryResult


class HostPathResolutionTests(unittest.TestCase):
    def test_absolute_compose_file_gets_host_mount_prefix(self) -> None:
        with patch.dict("os.environ", {"HOST_MOUNT_PREFIX": "/hostroot"}):
            resolved = resolve_compose_file("/root/jackett/docker-compose.yml", "/root/jackett")
        self.assertEqual(resolved, Path("/hostroot/root/jackett/docker-compose.yml"))

    def test_relative_compose_file_joins_resolved_workdir(self) -> None:
        with patch.dict("os.environ", {"HOST_MOUNT_PREFIX": "/hostroot"}):
            resolved = resolve_compose_file("compose.yml", "/root/jackett")
        self.assertEqual(resolved, Path("/hostroot/root/jackett/compose.yml"))

    def test_no_prefix_is_a_no_op(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("HOST_MOUNT_PREFIX", None)
            resolved = resolve_compose_file("/srv/media/compose.yml", "/srv/media")
        self.assertEqual(resolved, Path("/srv/media/compose.yml"))

    def test_validation_checks_files_under_prefix(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            workdir = Path(tmp_dir) / "root" / "jackett"
            workdir.mkdir(parents=True)
            (workdir / "docker-compose.yml").write_text("services: {}\n")
            with patch.dict("os.environ", {"HOST_MOUNT_PREFIX": tmp_dir}):
                warnings = validate_compose_project_config(
                    ComposeProjectConfig(
                        workdir="/root/jackett",
                        files=["/root/jackett/docker-compose.yml"],
                        project_name="jackett",
                    )
                )
        self.assertEqual(warnings, [])


class ConfigTests(unittest.TestCase):
    def test_load_creates_default_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            load_config(config_path)
            self.assertTrue(config_path.exists())

    def test_save_and_reload_round_trip(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            source = DockwatchConfig(
                notify_only=["nginx"],
                include_tags=[r"^1\\.", r"^1\\."],
                exclude_tags=[r"-rc$"],
                notify_on=["new", "update", "bogus"],
                first_check_notify=True,
                webhook_url="https://example.test/webhook",
                discord_webhook="https://discord.test/hook",
                ntfy_url="https://ntfy.test/topic",
                schedule_interval_seconds=600,
                schedule_jitter_seconds=45,
                run_on_startup=False,
                max_concurrent_checks=8,
                portainer=PortainerConfig(
                    enabled=True,
                    url="https://portainer.example.test:9443",
                    api_key="secret-token",
                    environments=["1", "2"],
                ),
                compose_projects={
                    "media": ComposeProjectConfig(
                        workdir="/srv/media",
                        files=["compose.yml", "compose.override.yml"],
                        project_name="media-stack",
                    )
                },
            )
            save_config(source, config_path)
            loaded = load_config(config_path)
            self.assertEqual(loaded.notify_only, ["nginx"])
            self.assertEqual(loaded.include_tags, [r"^1\\."])
            self.assertEqual(loaded.exclude_tags, [r"-rc$"])
            self.assertEqual(loaded.notify_on, ["new", "update"])
            self.assertTrue(loaded.first_check_notify)
            self.assertEqual(loaded.webhook_url, "https://example.test/webhook")
            self.assertEqual(loaded.discord_webhook, "https://discord.test/hook")
            self.assertEqual(loaded.ntfy_url, "https://ntfy.test/topic")
            self.assertEqual(loaded.schedule_interval_seconds, 600)
            self.assertEqual(loaded.schedule_jitter_seconds, 45)
            self.assertFalse(loaded.run_on_startup)
            self.assertEqual(loaded.max_concurrent_checks, 8)
            self.assertTrue(loaded.portainer.enabled)
            self.assertEqual(loaded.portainer.url, "https://portainer.example.test:9443")
            self.assertEqual(loaded.portainer.api_key, "secret-token")
            self.assertEqual(loaded.portainer.environments, ["1", "2"])
            self.assertIn("media", loaded.compose_projects)
            self.assertEqual(loaded.compose_projects["media"].workdir, "/srv/media")
            self.assertEqual(loaded.compose_projects["media"].files, ["compose.yml", "compose.override.yml"])
            self.assertEqual(loaded.compose_projects["media"].project_name, "media-stack")

    def test_save_normalizes_empty_notify_events_and_scheduler_mins(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            source = DockwatchConfig(
                notify_on=[],
                schedule_interval_seconds=1,
                schedule_jitter_seconds=-4,
                max_concurrent_checks=0,
            )

            save_config(source, config_path)
            loaded = load_config(config_path)

            self.assertEqual(loaded.notify_on, ["update"])
            self.assertEqual(loaded.schedule_interval_seconds, 10)
            self.assertEqual(loaded.schedule_jitter_seconds, 0)
            self.assertEqual(loaded.max_concurrent_checks, 1)


class UnpinUnignoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._config_path = Path(self._tmp.name) / "config.toml"
        self._db_path = Path(self._tmp.name) / "test.db"
        save_config(DockwatchConfig(), self._config_path)

        from dockwatch.db import ManifestStore

        # Pre-populate the store with pinned + ignored entries
        store = ManifestStore(path=self._db_path)
        store.add_flag("web", "pinned")
        store.add_flag("db", "pinned")
        store.add_flag("cache", "ignored")
        store.add_flag("redis", "ignored")
        self._store = store

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *args: str):  # noqa: ANN202
        from dockwatch.db import ManifestStore

        runner = CliRunner()
        with patch("dockwatch.main.load_config", lambda: load_config(self._config_path)), \
             patch("dockwatch.main.ManifestStore", lambda: ManifestStore(path=self._db_path)):
            return runner.invoke(app, list(args))

    def test_unpin_removes_entry(self) -> None:
        result = self._run("unpin", "web")
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("web", self._store.get_pinned())
        self.assertIn("db", self._store.get_pinned())

    def test_unpin_unknown_errors(self) -> None:
        result = self._run("unpin", "nonexistent")
        self.assertNotEqual(result.exit_code, 0)

    def test_unignore_removes_entry(self) -> None:
        result = self._run("unignore", "cache")
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("cache", self._store.get_ignored())
        self.assertIn("redis", self._store.get_ignored())

    def test_unignore_unknown_errors(self) -> None:
        result = self._run("unignore", "nonexistent")
        self.assertNotEqual(result.exit_code, 0)

    def test_check_notify_reports_filtered_out_notifications(self) -> None:
        with patch(
            "dockwatch.main.discover_containers",
            new=AsyncMock(return_value=SourceDiscoveryResult()),
        ), patch(
            "dockwatch.main.build_notifiers", return_value=[object()]
        ), patch(
            "dockwatch.main.send_configured_notifications", return_value=[]
        ) as notify_mock:
            result = self._run("check", "--notify")

        self.assertEqual(result.exit_code, 0)
        self.assertIn("No notifications matched configured filters.", result.stdout)
        notify_mock.assert_not_called()

    def test_version_command_prints_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["version"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(dockwatch_version, result.stdout)

    def test_serve_command_calls_web_runner(self) -> None:
        runner = CliRunner()
        with patch("uvicorn.run") as run_mock, patch(
            "dockwatch.api.app.create_app", return_value=object()
        ):
            result = runner.invoke(app, ["serve", "--host", "127.0.0.1", "--port", "9090"])

        self.assertEqual(result.exit_code, 0)
        run_mock.assert_called_once()
        self.assertEqual(run_mock.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(run_mock.call_args.kwargs["port"], 9090)

    def test_notify_test_command_uses_configured_notifiers(self) -> None:
        runner = CliRunner()
        config = DockwatchConfig(webhook_url="https://example.test/webhook")
        with patch("dockwatch.main.load_config", return_value=config), patch(
            "dockwatch.main.build_notifiers", return_value=[object()]
        ) as build_mock, patch(
            "dockwatch.main.send_configured_notifications", return_value=[]
        ) as notify_mock:
            result = runner.invoke(app, ["notify", "test"])

        self.assertEqual(result.exit_code, 0)
        build_mock.assert_called_once()
        notify_mock.assert_called_once()

    def test_list_source_portainer_uses_discovery(self) -> None:
        runner = CliRunner()
        portainer_container = ContainerInfo(
            name="web",
            container_id="1",
            image_ref="nginx:1.0.0",
            registry=RegistryType.DOCKERHUB,
            namespace="library",
            image_name="nginx",
            current_tag="1.0.0",
            source="portainer",
            environment_id="5",
            environment_name="prod",
        )
        with patch("dockwatch.main.load_config", return_value=DockwatchConfig()), patch(
            "dockwatch.main.discover_containers",
            new=AsyncMock(return_value=SourceDiscoveryResult(containers=[portainer_container])),
        ):
            result = runner.invoke(app, ["list", "--source", "portainer"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Portainer:prod", result.stdout)

    def test_check_source_portainer_handles_discovery_error(self) -> None:
        runner = CliRunner()
        with patch("dockwatch.main.load_config", return_value=DockwatchConfig()), patch(
            "dockwatch.main.discover_containers",
            new=AsyncMock(return_value=SourceDiscoveryResult(errors=["portainer environments request failed"])),
        ):
            result = runner.invoke(app, ["check", "--source", "portainer"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("portainer environments request failed", result.stderr)

    def test_environments_command_lists_portainer_environments(self) -> None:
        runner = CliRunner()

        class _Env:
            def __init__(self, id: int, name: str) -> None:
                self.id = id
                self.name = name

        with patch("dockwatch.main.load_config", return_value=DockwatchConfig()), patch(
            "dockwatch.main.discover_environments",
            new=AsyncMock(return_value=[_Env(1, "local"), _Env(2, "prod")]),
        ):
            result = runner.invoke(app, ["environments"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("1: local", result.stdout)
        self.assertIn("2: prod", result.stdout)

    def test_update_dry_run_prints_plan(self) -> None:
        runner = CliRunner()
        container = ContainerInfo(
            name="web",
            container_id="1",
            image_ref="nginx:1.0.0",
            registry=RegistryType.DOCKERHUB,
            namespace="library",
            image_name="nginx",
            current_tag="1.0.0",
        )
        check_result = UpdateResult(
            container_info=container,
            is_outdated=True,
            deployed_tag="1.0.0",
            remote_tag="1.1.0",
            comparison_basis="version",
        )
        with patch("dockwatch.main.load_config", return_value=DockwatchConfig()), patch(
            "dockwatch.main.discover_containers",
            new=AsyncMock(return_value=SourceDiscoveryResult(containers=[container])),
        ), patch(
            "dockwatch.main.check_all",
            new=AsyncMock(return_value=[check_result]),
        ):
            result = runner.invoke(app, ["update", "web", "--dry-run"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Mode: plain", result.stdout)
        self.assertIn("Dry run complete.", result.stdout)

    def test_update_blocked_for_portainer_source(self) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["update", "web", "--source", "portainer"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Only local Docker updates are supported", result.stderr)


class RegistryConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_all_skips_ignored_and_marks_pinned(self) -> None:
        from dockwatch.db import ManifestStore

        containers = [
            ContainerInfo(
                name="web",
                container_id="1",
                image_ref="nginx:1.0.0",
                registry=RegistryType.UNKNOWN,
                namespace="library",
                image_name="nginx",
                current_tag="1.0.0",
            ),
            ContainerInfo(
                name="db",
                container_id="2",
                image_ref="postgres:15",
                registry=RegistryType.UNKNOWN,
                namespace="library",
                image_name="postgres",
                current_tag="15",
            ),
            ContainerInfo(
                name="cache",
                container_id="3",
                image_ref="redis:7",
                registry=RegistryType.UNKNOWN,
                namespace="library",
                image_name="redis",
                current_tag="7",
            ),
        ]

        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(path=Path(tmp_dir) / "test.db")
            store.add_flag("web", "pinned")
            store.add_flag("db", "ignored")

            config = DockwatchConfig(notify_only=[])
            results = await check_all(containers, config, store=store)

        self.assertEqual(len(results), 2)
        by_name = {result.container_info.name: result for result in results}
        self.assertIn("web", by_name)
        self.assertIn("cache", by_name)
        self.assertEqual(by_name["web"].status, "PINNED")
        self.assertIsNone(by_name["web"].is_outdated)
        self.assertEqual(by_name["cache"].status, "LOCAL")

    async def test_check_all_respects_label_overrides(self) -> None:
        from dockwatch.db import ManifestStore

        containers = [
            ContainerInfo(
                name="web",
                container_id="1",
                image_ref="nginx:1.0.0",
                registry=RegistryType.UNKNOWN,
                namespace="library",
                image_name="nginx",
                current_tag="1.0.0",
                ignored_override=False,
                pinned_override=True,
            ),
            ContainerInfo(
                name="db",
                container_id="2",
                image_ref="postgres:15",
                registry=RegistryType.UNKNOWN,
                namespace="library",
                image_name="postgres",
                current_tag="15",
                watch_enabled=False,
            ),
        ]

        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(path=Path(tmp_dir) / "test.db")
            store.add_flag("web", "ignored")

            config = DockwatchConfig()
            results = await check_all(containers, config, store=store)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].container_info.name, "web")
        self.assertEqual(results[0].status, "PINNED")


class TestPinnedIgnoredMigration:
    def test_migrates_existing_toml_values_into_store(self, tmp_path):
        from dockwatch.config import migrate_pinned_ignored_to_db
        from dockwatch.db import ManifestStore

        config_path = tmp_path / "config.toml"
        config_path.write_text(
            'pinned = ["nginx", "redis"]\nignored = ["postgres"]\n',
            encoding="utf-8",
        )
        store = ManifestStore(path=tmp_path / "test.db")

        migrate_pinned_ignored_to_db(config_path, store)

        assert sorted(store.get_pinned()) == ["nginx", "redis"]
        assert store.get_ignored() == ["postgres"]

    def test_migration_is_idempotent(self, tmp_path):
        from dockwatch.config import migrate_pinned_ignored_to_db
        from dockwatch.db import ManifestStore

        config_path = tmp_path / "config.toml"
        config_path.write_text('pinned = ["nginx"]\n', encoding="utf-8")
        store = ManifestStore(path=tmp_path / "test.db")

        migrate_pinned_ignored_to_db(config_path, store)
        migrate_pinned_ignored_to_db(config_path, store)  # run twice

        assert store.get_pinned() == ["nginx"]

    def test_migration_skips_when_store_already_has_data(self, tmp_path):
        from dockwatch.config import migrate_pinned_ignored_to_db
        from dockwatch.db import ManifestStore

        config_path = tmp_path / "config.toml"
        config_path.write_text('pinned = ["nginx"]\n', encoding="utf-8")
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("already-here", "pinned")

        migrate_pinned_ignored_to_db(config_path, store)

        # Migration must not clobber flags a user already set post-migration
        # on a previous run -- it only imports when the store is empty.
        assert store.get_pinned() == ["already-here"]

    def test_migration_handles_missing_config_file(self, tmp_path):
        from dockwatch.config import migrate_pinned_ignored_to_db
        from dockwatch.db import ManifestStore

        config_path = tmp_path / "does-not-exist.toml"
        store = ManifestStore(path=tmp_path / "test.db")

        migrate_pinned_ignored_to_db(config_path, store)  # must not raise

        assert store.get_pinned() == []


class TestCLITriggersMigration(unittest.TestCase):
    """Regression test: the CLI must run the TOML->SQLite migration too.

    Previously `migrate_pinned_ignored_to_db` was only called from the web
    server's FastAPI lifespan hook. A user who ran a CLI command (e.g.
    `dockwatch config list`) before ever starting the server would see an
    empty store, and any subsequent CLI write would make the store
    non-empty -- permanently defeating the migration's empty-store guard
    once the server did start. The root Typer callback in main.py must
    call the migration before any subcommand runs.
    """

    def test_cli_invocation_imports_legacy_toml_pins_into_store(self) -> None:
        from dockwatch.db import ManifestStore

        runner = CliRunner()
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                'pinned = ["plex"]\nignored = ["db"]\n',
                encoding="utf-8",
            )
            db_path = Path(tmp) / "test.db"

            with patch("dockwatch.main.CONFIG_PATH", config_path), \
                 patch("dockwatch.main.ManifestStore", lambda: ManifestStore(path=db_path)):
                result = runner.invoke(app, ["config", "list"])

            self.assertEqual(result.exit_code, 0)
            store = ManifestStore(path=db_path)
            self.assertEqual(store.get_pinned(), ["plex"])
            self.assertEqual(store.get_ignored(), ["db"])


class TestCLIPinUsesStore(unittest.TestCase):
    def test_pin_command_writes_to_store(self) -> None:
        from dockwatch.db import ManifestStore

        runner = CliRunner()
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch("dockwatch.main.ManifestStore", lambda: ManifestStore(path=db_path)):
                result = runner.invoke(app, ["pin", "nginx"])
            self.assertEqual(result.exit_code, 0)
            store = ManifestStore(path=db_path)
            self.assertEqual(store.get_pinned(), ["nginx"])

    def test_ignore_command_writes_to_store(self) -> None:
        from dockwatch.db import ManifestStore

        runner = CliRunner()
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch("dockwatch.main.ManifestStore", lambda: ManifestStore(path=db_path)):
                result = runner.invoke(app, ["ignore", "redis"])
            self.assertEqual(result.exit_code, 0)
            store = ManifestStore(path=db_path)
            self.assertEqual(store.get_ignored(), ["redis"])

    def test_config_list_reads_pinned_and_ignored_from_store(self) -> None:
        from dockwatch.db import ManifestStore

        runner = CliRunner()
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            store = ManifestStore(path=db_path)
            store.add_flag("nginx", "pinned")
            store.add_flag("redis", "ignored")
            with patch("dockwatch.main.ManifestStore", lambda: ManifestStore(path=db_path)):
                result = runner.invoke(app, ["config", "list"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("nginx", result.stdout)
            self.assertIn("redis", result.stdout)


class AuthConfigTests(unittest.TestCase):
    def test_password_hash_round_trip(self) -> None:
        encoded = hash_password("correct-password")
        self.assertTrue(verify_password("correct-password", encoded))
        self.assertFalse(verify_password("wrong-password", encoded))

    def test_password_hash_uses_random_salt(self) -> None:
        first = hash_password("same-password")
        second = hash_password("same-password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("same-password", first))
        self.assertTrue(verify_password("same-password", second))

    def test_verify_password_rejects_malformed_hash(self) -> None:
        self.assertFalse(verify_password("anything", "not-a-valid-hash"))
        self.assertFalse(verify_password("anything", ""))

    def test_auth_config_toml_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            config = DockwatchConfig(
                auth=AuthConfig(
                    username="admin",
                    password_hash=hash_password("correct-password"),
                    secret_key="a" * 64,
                )
            )
            save_config(config, path)
            loaded = load_config(path)
            self.assertEqual(loaded.auth.username, "admin")
            self.assertTrue(verify_password("correct-password", loaded.auth.password_hash))
            self.assertEqual(loaded.auth.secret_key, "a" * 64)

    def test_load_config_generates_secret_key_when_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            config = load_config(path)
            self.assertTrue(config.auth.secret_key)
            self.assertEqual(len(config.auth.secret_key), 64)

    def test_secret_key_is_stable_across_loads(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            first = load_config(path)
            second = load_config(path)
            self.assertEqual(first.auth.secret_key, second.auth.secret_key)

    def test_bootstrap_sets_hash_when_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            config = load_config(path)
            with patch.dict("os.environ", {"DOCKWATCH_USERNAME": "admin", "DOCKWATCH_PASSWORD": "correct-password"}):
                updated = bootstrap_auth_from_env(config, path)
            self.assertEqual(updated.auth.username, "admin")
            self.assertTrue(verify_password("correct-password", updated.auth.password_hash))

    def test_bootstrap_does_not_overwrite_existing_hash(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            config = load_config(path)
            with patch.dict("os.environ", {"DOCKWATCH_USERNAME": "admin", "DOCKWATCH_PASSWORD": "first-password"}):
                bootstrap_auth_from_env(config, path)

            reloaded = load_config(path)
            with patch.dict("os.environ", {"DOCKWATCH_USERNAME": "someone-else", "DOCKWATCH_PASSWORD": "second-password"}):
                updated = bootstrap_auth_from_env(reloaded, path)

            self.assertEqual(updated.auth.username, "admin")
            self.assertTrue(verify_password("first-password", updated.auth.password_hash))
            self.assertFalse(verify_password("second-password", updated.auth.password_hash))

    def test_bootstrap_does_nothing_without_env_vars(self) -> None:
        import os

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            config = load_config(path)
            saved = {k: os.environ.pop(k) for k in ("DOCKWATCH_USERNAME", "DOCKWATCH_PASSWORD") if k in os.environ}
            try:
                updated = bootstrap_auth_from_env(config, path)
            finally:
                os.environ.update(saved)
            self.assertEqual(updated.auth.password_hash, "")


if __name__ == "__main__":
    unittest.main()
