from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from dockwatch.config import DockwatchConfig
from dockwatch.db import ManifestStore
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.scheduler import ScheduledCheckRunner
from dockwatch.updater import UpdateExecutionResult


def _outdated_result(name: str = "web") -> UpdateResult:
    container = ContainerInfo(
        name=name,
        container_id="abcdef123456",
        image_ref="nginx:1.0.0",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name="nginx",
        current_tag="1.0.0",
    )
    return UpdateResult(
        container_info=container,
        is_outdated=True,
        deployed_tag="1.0.0",
        remote_tag="1.1.0",
        comparison_basis="version",
    )


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_skips_overlap(self) -> None:
        emitted: list[str] = []
        config = DockwatchConfig(run_on_startup=False)
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            runner = ScheduledCheckRunner(
                config=config,
                store=store,
                emit=emitted.append,
                container_loader=lambda: [],
            )

            async def slow_check_all(*args, **kwargs):  # noqa: ANN002, ANN003
                await asyncio.sleep(0.05)
                return []

            with patch("dockwatch.scheduler.check_all", side_effect=slow_check_all), patch(
                "dockwatch.scheduler.send_configured_notifications",
                new=AsyncMock(return_value=[]),
            ):
                first = asyncio.create_task(runner.run_once())
                await asyncio.sleep(0)
                second = await runner.run_once()
                first_result = await first

        self.assertTrue(first_result)
        self.assertFalse(second)
        self.assertIn("Skipped scheduled run", emitted[0])

    async def test_auto_update_triggers_for_flagged_outdated_container(self) -> None:
        config = DockwatchConfig(run_on_startup=False)
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            store.set_auto_update(["web"])
            result = _outdated_result("web")
            runner = ScheduledCheckRunner(
                config=config,
                store=store,
                notify=False,
                container_loader=lambda: [],
            )

            with patch("dockwatch.scheduler.check_all", new=AsyncMock(return_value=[result])), patch(
                "dockwatch.scheduler.execute_update",
                return_value=UpdateExecutionResult(success=True, mode="plain", message="updated"),
            ) as mock_execute:
                await runner.run_once()

            mock_execute.assert_called_once()
            history = store.list_update_history("web")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].username, "scheduler (auto-update)")
            self.assertEqual(history[0].status, "success")

    async def test_auto_update_skips_container_not_flagged(self) -> None:
        config = DockwatchConfig(run_on_startup=False)
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            result = _outdated_result("web")
            runner = ScheduledCheckRunner(
                config=config,
                store=store,
                notify=False,
                container_loader=lambda: [],
            )

            with patch("dockwatch.scheduler.check_all", new=AsyncMock(return_value=[result])), patch(
                "dockwatch.scheduler.execute_update",
            ) as mock_execute:
                await runner.run_once()

        mock_execute.assert_not_called()

    async def test_auto_update_skips_blocked_plan(self) -> None:
        config = DockwatchConfig(run_on_startup=False)
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            store.set_auto_update(["web"])
            result = _outdated_result("web")
            result.status = "PINNED"
            runner = ScheduledCheckRunner(
                config=config,
                store=store,
                notify=False,
                container_loader=lambda: [],
            )

            with patch("dockwatch.scheduler.check_all", new=AsyncMock(return_value=[result])), patch(
                "dockwatch.scheduler.execute_update",
            ) as mock_execute:
                await runner.run_once()

        mock_execute.assert_not_called()

    def test_next_delay_stays_within_bounds(self) -> None:
        config = DockwatchConfig(
            schedule_interval_seconds=120,
            schedule_jitter_seconds=15,
            run_on_startup=False,
        )
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            runner = ScheduledCheckRunner(
                config=config,
                store=store,
                container_loader=lambda: [],
            )

            with patch("dockwatch.scheduler.random.uniform", return_value=7.5):
                delay = runner.next_delay()

        self.assertEqual(delay, 127.5)


if __name__ == "__main__":
    unittest.main()
