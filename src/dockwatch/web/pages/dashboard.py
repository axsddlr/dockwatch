"""Dashboard page for dockwatch NiceGUI frontend."""

from __future__ import annotations

from datetime import datetime

from nicegui import ui

from ... import __version__
from ...config import load_config, save_config
from ...db import ManifestStore
from ...docker_client import DockerConnectionError, get_running_containers
from ...models import ContainerInfo, RegistryType, UpdateResult
from ...notifiers import send_configured_notifications
from ...registry import check_all
from ..components.container_table import ContainerStatusTable


class DashboardController:
    def __init__(self) -> None:
        self.results: list[UpdateResult] = []
        self.last_checked: str = "Never"
        self.config = load_config()
        self.store = ManifestStore()

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
            self.error_help = ui.markdown("").classes("text-red-7")
            self.table = ContainerStatusTable()

            with ui.card().classes("w-full"):
                ui.label("Notification Settings").classes("text-lg font-medium")
                self.webhook_input = ui.input("Webhook URL", value=self.config.webhook_url).classes("w-full")
                self.discord_input = ui.input("Discord Webhook", value=self.config.discord_webhook).classes("w-full")
                self.ntfy_input = ui.input("ntfy Topic URL", value=self.config.ntfy_url).classes("w-full")
                with ui.row().classes("gap-2"):
                    ui.button("Save Settings", on_click=self.save_notification_settings)
                    ui.button("Send Test Notification", on_click=self.send_test_notification)

        self.timer = ui.timer(interval=float(self.config.schedule_interval_seconds), callback=self._timer_refresh, active=False)
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
        new_value = float(event.value or self.config.schedule_interval_seconds)
        if new_value < 10:
            new_value = 10
        self.timer.interval = new_value

    async def refresh_all(self) -> None:
        try:
            containers = get_running_containers()
        except DockerConnectionError as exc:
            self.message_label.set_text(str(exc))
            self.error_help.set_content(
                "Docker is unavailable.\\n\\n"
                "Fixes to try:\\n"
                "- Ensure Docker Desktop/daemon is running\\n"
                "- Verify access to Docker socket/pipe\\n"
                "- Re-open dashboard after Docker is healthy"
            )
            self.results = []
            self.table.render(self.results, self.check_one, self.toggle_pin)
            return

        self.config = load_config()
        self.message_label.set_text("")
        self.error_help.set_content("")
        self.results = await check_all(
            containers,
            self.config,
            store=self.store,
            max_concurrency=self.config.max_concurrent_checks,
        )
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

        self.config = load_config()
        updated_results = await check_all([target], self.config, store=self.store, max_concurrency=1)
        if not updated_results:
            self.message_label.set_text(f"Container '{container_name}' is currently ignored.")
            await self.refresh_all()
            return
        updated = updated_results[0]
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

    async def save_notification_settings(self) -> None:
        self.config = load_config()
        self.config.webhook_url = (self.webhook_input.value or "").strip()
        self.config.discord_webhook = (self.discord_input.value or "").strip()
        self.config.ntfy_url = (self.ntfy_input.value or "").strip()
        save_config(self.config)
        self.message_label.set_text("Notification settings saved.")

    async def send_test_notification(self) -> None:
        self.config = load_config()
        sample_results = self.results
        if not sample_results:
            sample_results = [
                UpdateResult(
                    container_info=ContainerInfo(
                        name="sample",
                        container_id="sample",
                        image_ref="library/sample:1.0.0",
                        registry=RegistryType.DOCKERHUB,
                        namespace="library",
                        image_name="sample",
                        current_tag="1.0.0",
                    ),
                    latest_tag="1.1.0",
                    is_outdated=True,
                    check_error=None,
                    status=None,
                    event="update",
                )
            ]
        errors = await send_configured_notifications(sample_results, self.config, apply_filters=False)
        if errors:
            self.message_label.set_text("Test notification failed: " + "; ".join(errors))
        else:
            self.message_label.set_text("Test notification sent.")


def register_dashboard_page() -> None:
    @ui.page("/")
    async def _dashboard() -> None:
        controller = DashboardController()
        await controller.refresh_all()
