from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from typer.testing import CliRunner

from dockwatch.config import DockwatchConfig, load_config, save_config
from dockwatch.main import app
from dockwatch.models import ContainerInfo, RegistryType
from dockwatch.registry import check_all


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
                webhook_url="https://example.test/webhook",
                discord_webhook="https://discord.test/hook",
            )
            save_config(source, config_path)
            loaded = load_config(config_path)
            self.assertEqual(loaded.pinned, ["plex", "jellyfin"])
            self.assertEqual(loaded.ignored, ["db"])
            self.assertEqual(loaded.notify_only, ["nginx"])
            self.assertEqual(loaded.webhook_url, "https://example.test/webhook")
            self.assertEqual(loaded.discord_webhook, "https://discord.test/hook")


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
        from unittest.mock import patch
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


if __name__ == "__main__":
    unittest.main()
