"""Background scheduler for periodic checks."""

from __future__ import annotations

import asyncio
import inspect
import random
from collections.abc import Awaitable, Callable

from .config import DockwatchConfig
from .db import ManifestStore
from .docker_client import DockerConnectionError
from .models import ContainerInfo, UpdateResult
from .notifiers import send_configured_notifications
from .registry import check_all, record_digest_drift_events
from .sources import discover_containers
from .updater import (
    build_update_plan,
    execute_agent_update,
    execute_portainer_compose_update,
    execute_update,
)

AUTO_UPDATE_USERNAME = "scheduler (auto-update)"


class ScheduledCheckRunner:
    def __init__(
        self,
        *,
        config: DockwatchConfig,
        store: ManifestStore,
        notify: bool = True,
        container_loader: Callable[[], list[ContainerInfo] | Awaitable[list[ContainerInfo]]] | None = None,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.notify = notify
        # Default: discover every configured source (local Docker, Portainer,
        # agents) so scheduled checks + auto-updates cover all of them.
        self.container_loader = container_loader or self._discover_all
        self.emit = emit or (lambda _message: None)
        self._run_lock = asyncio.Lock()

    async def _discover_all(self) -> list[ContainerInfo]:
        discovery = await discover_containers(self.config, source="all")
        return discovery.containers

    def next_delay(self) -> float:
        return float(self.config.schedule_interval_seconds) + random.uniform(0, self.config.schedule_jitter_seconds)

    async def run_once(self) -> bool:
        if self._run_lock.locked():
            self.emit("Skipped scheduled run: previous check still in progress.")
            return False

        async with self._run_lock:
            try:
                containers = self.container_loader()
                if inspect.isawaitable(containers):
                    containers = await containers
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

            await self._run_auto_updates(results)

            return True

    async def _run_auto_updates(self, results: list[UpdateResult]) -> None:
        auto_update_names = set(self.store.get_auto_update())
        if not auto_update_names:
            return

        for result in results:
            if result.container_info.name not in auto_update_names:
                continue
            if result.is_outdated is not True:
                continue

            plan = build_update_plan(result, self.config)
            if not plan.allowed:
                self.emit(f"Auto-update skipped for '{plan.container_name}': {plan.reason}")
                continue

            if plan.mode == "portainer-compose":
                execution = await execute_portainer_compose_update(plan, self.config)
            elif plan.mode == "agent-update":
                execution = await execute_agent_update(plan, self.config)
            else:
                execution = await asyncio.to_thread(execute_update, plan, self.config)

            self.store.record_update_event(
                container_name=plan.container_name,
                action="update",
                source=plan.source,
                status="success" if execution.success else "failed",
                error=None if execution.success else execution.message,
                username=AUTO_UPDATE_USERNAME,
                old_tag=plan.current_tag,
                new_tag=plan.remote_tag,
                environment_id=plan.environment_id,
            )
            self.emit(
                f"Auto-update {'succeeded' if execution.success else 'failed'} for "
                f"'{plan.container_name}': {execution.message}"
            )

    async def serve_forever(self) -> None:
        if self.config.run_on_startup:
            await self.run_once()

        while True:
            await asyncio.sleep(self.next_delay())
            await self.run_once()
