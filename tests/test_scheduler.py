from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from dockwatch.config import DockwatchConfig
from dockwatch.db import ManifestStore
from dockwatch.scheduler import ScheduledCheckRunner


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
