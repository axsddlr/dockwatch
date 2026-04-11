from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from dockwatch.config import ComposeProjectConfig, DockwatchConfig, PortainerConfig, load_config, save_config
from dockwatch.main import app
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.registry import check_all
from dockwatch.sources import SourceDiscoveryResult


class ConfigTests(unittest.TestCase):
    def test_load_creates_default_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            config = load_config(config_path)
            self.assertEqual(config.pinned, [])
            self.assertTrue(config_path.exists())

    def test_save_and_reload_round_trip(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.toml"
            source = DockwatchConfig(
                pinned=["plex", "plex", "jellyfin"],
                ignored=["db"],
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
            self.assertEqual(loaded.pinned, ["plex", "jellyfin"])
            self.assertEqual(loaded.ignored, ["db"])
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
        # Pre-populate config with pinned + ignored entries
        cfg = DockwatchConfig(pinned=["web", "db"], ignored=["cache", "redis"])
        save_config(cfg, self._config_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *args: str):  # noqa: ANN202
        runner = CliRunner()
        with patch("dockwatch.main.load_config", lambda: load_config(self._config_path)), \
             patch("dockwatch.main.save_config", lambda cfg: save_config(cfg, self._config_path)):
            return runner.invoke(app, list(args))

    def test_unpin_removes_entry(self) -> None:
        result = self._run("unpin", "web")
        self.assertEqual(result.exit_code, 0)
        cfg = load_config(self._config_path)
        self.assertNotIn("web", cfg.pinned)
        self.assertIn("db", cfg.pinned)

    def test_unpin_unknown_errors(self) -> None:
        result = self._run("unpin", "nonexistent")
        self.assertNotEqual(result.exit_code, 0)

    def test_unignore_removes_entry(self) -> None:
        result = self._run("unignore", "cache")
        self.assertEqual(result.exit_code, 0)
        cfg = load_config(self._config_path)
        self.assertNotIn("cache", cfg.ignored)
        self.assertIn("redis", cfg.ignored)

    def test_unignore_unknown_errors(self) -> None:
        result = self._run("unignore", "nonexistent")
        self.assertNotEqual(result.exit_code, 0)

    def test_check_notify_reports_filtered_out_notifications(self) -> None:
        with patch(
            "dockwatch.main.discover_containers",
            new=AsyncMock(return_value=SourceDiscoveryResult()),
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
        self.assertIn("0.1.0", result.stdout)

    def test_serve_command_calls_web_runner(self) -> None:
        runner = CliRunner()
        with patch("dockwatch.main.run_web_app") as run_mock:
            result = runner.invoke(app, ["serve", "--host", "127.0.0.1", "--port", "9090"])

        self.assertEqual(result.exit_code, 0)
        run_mock.assert_called_once_with(host="127.0.0.1", port=9090)

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
        self.assertIn("portainer environments request failed", result.stdout)

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
        self.assertIn("Only local Docker updates are supported", result.stdout)


class RegistryConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_all_skips_ignored_and_marks_pinned(self) -> None:
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

        config = DockwatchConfig(pinned=["web"], ignored=["db"], notify_only=[])
        results = await check_all(containers, config)

        self.assertEqual(len(results), 2)
        by_name = {result.container_info.name: result for result in results}
        self.assertIn("web", by_name)
        self.assertIn("cache", by_name)
        self.assertEqual(by_name["web"].status, "PINNED")
        self.assertIsNone(by_name["web"].is_outdated)
        self.assertEqual(by_name["cache"].status, "UNKNOWN")

    async def test_check_all_respects_label_overrides(self) -> None:
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

        config = DockwatchConfig(pinned=[], ignored=["web"])
        results = await check_all(containers, config)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].container_info.name, "web")
        self.assertEqual(results[0].status, "PINNED")


if __name__ == "__main__":
    unittest.main()
