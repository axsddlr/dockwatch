"""Background scheduler for periodic checks."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable

from .config import DockwatchConfig
from .db import ManifestStore
from .docker_client import DockerConnectionError, get_running_containers
from .models import ContainerInfo
from .notifiers import send_configured_notifications
from .registry import check_all, record_digest_drift_events


class ScheduledCheckRunner:
    def __init__(
        self,
        *,
        config: DockwatchConfig,
        store: ManifestStore,
        notify: bool = True,
        container_loader: Callable[[], list[ContainerInfo]] = get_running_containers,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.notify = notify
        self.container_loader = container_loader
        self.emit = emit or (lambda _message: None)
        self._run_lock = asyncio.Lock()

    def next_delay(self) -> float:
        return float(self.config.schedule_interval_seconds) + random.uniform(0, self.config.schedule_jitter_seconds)

    async def run_once(self) -> bool:
        if self._run_lock.locked():
            self.emit("Skipped scheduled run: previous check still in progress.")
            return False

        async with self._run_lock:
            try:
                containers = self.container_loader()
            except DockerConnectionError as exc:
                self.emit(f"Scheduled check failed: {exc}")
                return True

            results = await check_all(
                containers,
                self.config,
                store=self.store,
                max_concurrency=self.config.max_concurrent_checks,
            )
            record_digest_drift_events(results, self.store)
            outdated = sum(1 for result in results if result.is_outdated is True and not result.check_error)
            up_to_date = sum(1 for result in results if result.is_outdated is False and not result.check_error)
            unknown = len(results) - outdated - up_to_date
            self.emit(f"Scheduled check complete: {outdated} outdated, {up_to_date} up-to-date, {unknown} unknown.")

            if self.notify:
                errors = await send_configured_notifications(results, self.config)
                for error in errors:
                    self.emit(f"Notifier error: {error}")

            return True

    async def serve_forever(self) -> None:
        if self.config.run_on_startup:
            await self.run_once()

        while True:
            await asyncio.sleep(self.next_delay())
            await self.run_once()
