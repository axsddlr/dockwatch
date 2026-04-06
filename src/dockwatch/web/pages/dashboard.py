"""Dashboard page for dockwatch NiceGUI frontend."""

from __future__ import annotations

from datetime import datetime

from nicegui import ui

from ... import __version__
from ...config import load_config, save_config
from ...docker_client import DockerConnectionError, get_running_containers
from ...models import UpdateResult
from ...registry import check_all, check_container
from ..components.container_table import ContainerStatusTable


class DashboardController:
    def __init__(self) -> None:
        self.results: list[UpdateResult] = []
        self.last_checked: str = "Never"
        self.config = load_config()

        with ui.column().classes("w-full max-w-7xl mx-auto p-4 gap-4"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.column().classes("gap-0"):
                    ui.label("dockwatch Dashboard").classes("text-2xl font-bold")
                    ui.label(f"Version {__version__}").classes("text-sm text-grey-7")
                self.last_checked_label = ui.label("Last checked: Never").classes("text-sm text-grey-7")

            with ui.row().classes("w-full items-center gap-3"):
                ui.button("Refresh", on_click=self.refresh_all, color="primary")
                self.auto_refresh_switch = ui.switch("Auto refresh", value=False)
                self.interval_seconds = ui.number("Interval (seconds)", value=30, min=10, max=3600, step=5)

            self.message_label = ui.label("").classes("text-yellow-8")
            self.table = ContainerStatusTable()

        self.timer = ui.timer(interval=30.0, callback=self._timer_refresh, active=False)
        self.auto_refresh_switch.on_value_change(self._on_toggle_auto_refresh)
        self.interval_seconds.on_value_change(self._on_interval_change)

    async def _timer_refresh(self) -> None:
        await self.refresh_all()

    def _update_last_checked(self) -> None:
        self.last_checked = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_checked_label.set_text(f"Last checked: {self.last_checked}")

    def _on_toggle_auto_refresh(self, event) -> None:
        self.timer.active = bool(event.value)

    def _on_interval_change(self, event) -> None:
        new_value = float(event.value or 30)
        if new_value < 1:
            new_value = 1
        self.timer.interval = new_value

    async def refresh_all(self) -> None:
        try:
            containers = get_running_containers()
        except DockerConnectionError as exc:
            self.message_label.set_text(str(exc))
            self.results = []
            self.table.render(self.results, self.check_one, self.toggle_pin)
            return

        self.config = load_config()
        self.message_label.set_text("")
        self.results = await check_all(containers, self.config)
        self._update_last_checked()
        self.table.render(self.results, self.check_one, self.toggle_pin)

    async def check_one(self, container_name: str) -> None:
        if not container_name:
            return

        try:
            containers = get_running_containers()
        except DockerConnectionError as exc:
            self.message_label.set_text(str(exc))
            return

        target = next((item for item in containers if item.name == container_name), None)
        if target is None:
            self.message_label.set_text(f"Container '{container_name}' is no longer running.")
            await self.refresh_all()
            return

        updated = await check_container(target)
        replaced = False
        for idx, existing in enumerate(self.results):
            if existing.container_info.name == container_name:
                self.results[idx] = updated
                replaced = True
                break

        if not replaced:
            self.results.append(updated)

        self._update_last_checked()
        self.table.render(self.results, self.check_one, self.toggle_pin)

    async def toggle_pin(self, container_name: str) -> None:
        if not container_name:
            return

        self.config = load_config()
        if container_name in self.config.pinned:
            self.config.pinned = [name for name in self.config.pinned if name != container_name]
            self.message_label.set_text(f"Unpinned '{container_name}'.")
        else:
            self.config.pinned.append(container_name)
            self.message_label.set_text(f"Pinned '{container_name}'.")
        save_config(self.config)
        await self.refresh_all()


def register_dashboard_page() -> None:
    @ui.page("/")
    async def _dashboard() -> None:
        controller = DashboardController()
        await controller.refresh_all()
