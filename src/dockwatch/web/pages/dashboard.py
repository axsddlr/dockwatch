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
from ..theme import apply_theme
from ..theme import (
    ACCENT,
    BG_CARD,
    BG_DEEP,
    BG_SURFACE,
    BORDER,
    PRIMARY,
    STATUS_BLUE,
    STATUS_GREEN,
    STATUS_RED,
    STATUS_YELLOW,
    TEXT_MUTED,
    TEXT_PRIMARY,
)


def _stat_card(label: str, value_ref: list[str], color: str) -> ui.label:
    """Render a single stat card. Returns the value label for later updates."""
    with ui.card().classes("dw-stat-card flex-1 min-w-28").style(
        f"border-left: 3px solid {color} !important; padding: 14px 18px;"
    ):
        ui.label(label).style(
            f"font-size:11px; font-weight:600; letter-spacing:0.08em; "
            f"text-transform:uppercase; color:{TEXT_MUTED}; font-family:'Fira Code',monospace;"
        )
        val = ui.label(value_ref[0]).style(
            f"font-size:28px; font-weight:700; color:{color}; "
            f"font-family:'Fira Code',monospace; line-height:1.2; margin-top:4px;"
        )
    return val


class DashboardController:
    def __init__(self) -> None:
        self.results: list[UpdateResult] = []
        self.last_checked: str = "Never"
        self.config = load_config()
        self.store = ManifestStore()
        self._loading = False

        # ── Top nav bar ────────────────────────────────────────────────────────
        with ui.header().classes("dw-nav").style("padding: 0 24px; min-height: 56px;"):
            with ui.row().classes("w-full items-center justify-between").style("max-width:1200px; margin:0 auto; height:56px;"):
                # Brand
                with ui.row().classes("items-center gap-3"):
                    ui.label("dockwatch").classes("mono").style(
                        f"font-size:20px; font-weight:700; color:{TEXT_PRIMARY}; "
                        f"letter-spacing:-0.02em; text-shadow: 0 0 20px rgba(37,99,235,0.4);"
                    )
                    ui.badge(f"v{__version__}", color="blue-grey").props("outline").style(
                        "font-family:'Fira Code',monospace; font-size:10px;"
                    )

                # Right side: connection status + last checked
                with ui.row().classes("items-center gap-4"):
                    with ui.row().classes("items-center gap-2"):
                        self.conn_dot = ui.html('<span class="status-dot dot-green"></span>')
                        self.conn_label = ui.label("connected").style(
                            f"font-size:12px; color:{TEXT_MUTED};"
                        )
                    self.last_checked_label = ui.label("last check: never").style(
                        f"font-size:12px; color:{TEXT_MUTED}; font-family:'Fira Code',monospace;"
                    )

        # ── Page body ──────────────────────────────────────────────────────────
        with ui.column().classes("w-full mx-auto gap-6").style(
            f"max-width:1200px; padding: 24px 24px 48px; background:{BG_DEEP};"
        ):
            # ── Stats summary row ──────────────────────────────────────────────
            with ui.row().classes("w-full gap-3 flex-wrap"):
                self._stat_total_val = _stat_card("Containers", ["0"], TEXT_MUTED)
                self._stat_ok_val = _stat_card("Up to Date", ["0"], STATUS_GREEN)
                self._stat_outdated_val = _stat_card("Outdated", ["0"], STATUS_RED)
                self._stat_pinned_val = _stat_card("Pinned", ["0"], STATUS_BLUE)

            # ── Controls bar ───────────────────────────────────────────────────
            with ui.card().classes("dw-card w-full").style("padding: 14px 18px;"):
                with ui.row().classes("w-full items-center gap-4 flex-wrap"):
                    self.refresh_btn = ui.button(
                        "Refresh",
                        on_click=self.refresh_all,
                        icon="refresh",
                    ).props("unelevated").style(
                        f"background:{ACCENT} !important; color:#fff !important; "
                        f"font-family:'Fira Sans',sans-serif; font-weight:600;"
                    )
                    with ui.row().classes("items-center gap-2"):
                        self.auto_refresh_switch = ui.switch("Auto refresh", value=False).style(
                            f"color:{TEXT_MUTED};"
                        )
                        self.auto_refresh_icon = ui.icon("sync", size="18px").style(
                            f"color:{STATUS_GREEN}; display:none;"
                        )
                    self.interval_seconds = ui.number(
                        "Interval (s)", value=30, min=10, max=3600, step=5
                    ).style("width:130px;").props("dark dense outlined")

            # ── Error / info banner ────────────────────────────────────────────
            self.error_banner = ui.card().classes("dw-card w-full").style(
                f"border-left: 3px solid {STATUS_RED} !important; padding: 14px 18px; display:none;"
            )
            with self.error_banner:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("error_outline", size="20px").style(f"color:{STATUS_RED};")
                    self.message_label = ui.label("").style(f"color:{STATUS_RED}; font-weight:500;")
                self.error_help = ui.markdown("").style(f"color:{TEXT_MUTED}; margin-top:6px;")

            # ── Containers section ─────────────────────────────────────────────
            with ui.column().classes("w-full gap-3"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Containers").classes("section-label")
                    self.container_count_label = ui.label("").style(
                        f"font-size:12px; color:{TEXT_MUTED}; font-family:'Fira Code',monospace;"
                    )

                # Loading indicator
                self.loading_row = ui.row().classes("w-full justify-center").style("padding:40px 0;")
                with self.loading_row:
                    ui.spinner("dots", size="40px", color="primary")

                self.table = ContainerStatusTable()

            # ── Notification settings (collapsible) ────────────────────────────
            with ui.expansion("Notification Settings", icon="notifications").classes(
                "dw-expansion w-full"
            ).props("dark"):
                with ui.column().classes("w-full gap-3").style("padding: 8px 0;"):
                    self.webhook_input = ui.input(
                        "Webhook URL", value=self.config.webhook_url
                    ).classes("w-full").props("dark dense outlined")
                    self.discord_input = ui.input(
                        "Discord Webhook", value=self.config.discord_webhook
                    ).classes("w-full").props("dark dense outlined")
                    self.ntfy_input = ui.input(
                        "ntfy Topic URL", value=self.config.ntfy_url
                    ).classes("w-full").props("dark dense outlined")
                    with ui.row().classes("gap-3"):
                        ui.button("Save Settings", on_click=self.save_notification_settings).props(
                            "unelevated"
                        ).style(
                            f"background:{PRIMARY} !important; color:#fff !important;"
                        )
                        ui.button(
                            "Send Test Notification", on_click=self.send_test_notification
                        ).props("outline").style(f"color:{TEXT_MUTED};")

            # ── Footer ─────────────────────────────────────────────────────────
            with ui.row().classes("dw-footer w-full justify-center").style("padding:16px 0;"):
                ui.label(f"dockwatch {__version__}  ·  docker image update monitor").classes("mono-sm")

        self.loading_row.set_visibility(False)
        self.table.container.set_visibility(False)

        self.timer = ui.timer(
            interval=float(self.config.schedule_interval_seconds),
            callback=self._timer_refresh,
            active=False,
        )
        self.auto_refresh_switch.on_value_change(self._on_toggle_auto_refresh)
        self.interval_seconds.on_value_change(self._on_interval_change)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _update_stats(self) -> None:
        total = len(self.results)
        ok = sum(1 for r in self.results if r.is_outdated is False and r.status != "PINNED")
        outdated = sum(1 for r in self.results if r.is_outdated is True)
        pinned = sum(1 for r in self.results if r.status == "PINNED")

        self._stat_total_val.set_text(str(total))
        self._stat_ok_val.set_text(str(ok))
        self._stat_outdated_val.set_text(str(outdated))
        self._stat_pinned_val.set_text(str(pinned))

        plural = "container" if total == 1 else "containers"
        self.container_count_label.set_text(f"{total} {plural}")

    def _set_loading(self, loading: bool) -> None:
        self._loading = loading
        self.loading_row.set_visibility(loading)
        if loading:
            self.refresh_btn.props(add="loading")
        else:
            self.refresh_btn.props(remove="loading")
        if not loading:
            self.table.container.set_visibility(True)

    def _update_last_checked(self) -> None:
        self.last_checked = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_checked_label.set_text(f"last check: {self.last_checked}")

    def _show_error(self, msg: str, detail: str = "") -> None:
        self.error_banner.style(
            f"border-left: 3px solid {STATUS_RED} !important; padding: 14px 18px;"
        )
        self.message_label.set_text(msg)
        self.error_help.set_content(detail)

    def _clear_error(self) -> None:
        self.error_banner.style(
            f"border-left: 3px solid {STATUS_RED} !important; padding: 14px 18px; display:none;"
        )
        self.message_label.set_text("")
        self.error_help.set_content("")

    def _on_toggle_auto_refresh(self, event) -> None:
        active = bool(event.value)
        self.timer.active = active
        self.auto_refresh_icon.style(
            f"color:{STATUS_GREEN}; display:{'inline' if active else 'none'};"
        )

    def _on_interval_change(self, event) -> None:
        new_value = float(event.value or self.config.schedule_interval_seconds)
        if new_value < 10:
            new_value = 10
        self.timer.interval = new_value

    async def _timer_refresh(self) -> None:
        await self.refresh_all()

    # ── Public actions ─────────────────────────────────────────────────────────

    async def refresh_all(self) -> None:
        self._set_loading(True)
        try:
            containers = get_running_containers()
            self.conn_dot.set_content('<span class="status-dot dot-green"></span>')
            self.conn_label.set_text("connected")
            self._clear_error()
            self.config = load_config()
            self.results = await check_all(
                containers,
                self.config,
                store=self.store,
                max_concurrency=self.config.max_concurrent_checks,
            )
            self._update_last_checked()
            self._update_stats()
            self.table.render(self.results, self.check_one, self.toggle_pin)
        except DockerConnectionError as exc:
            self.conn_dot.set_content('<span class="status-dot dot-red"></span>')
            self.conn_label.set_text("disconnected")
            self._show_error(
                str(exc),
                "**Fixes to try:**\n"
                "- Ensure Docker Desktop/daemon is running\n"
                "- Verify access to Docker socket/pipe\n"
                "- Re-open dashboard after Docker is healthy",
            )
            self.results = []
            self._update_stats()
            self.table.render(self.results, self.check_one, self.toggle_pin)
        finally:
            self._set_loading(False)

    async def check_one(self, container_name: str) -> None:
        if not container_name:
            return

        try:
            containers = get_running_containers()
        except DockerConnectionError as exc:
            self._show_error(str(exc))
            return

        target = next((c for c in containers if c.name == container_name), None)
        if target is None:
            ui.notify(f"Container '{container_name}' is no longer running.", type="warning")
            await self.refresh_all()
            return

        self.config = load_config()
        updated_results = await check_all([target], self.config, store=self.store, max_concurrency=1)
        if not updated_results:
            ui.notify(f"Container '{container_name}' is currently ignored.", type="info")
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
        self._update_stats()
        self.table.render(self.results, self.check_one, self.toggle_pin)

    async def toggle_pin(self, container_name: str) -> None:
        if not container_name:
            return

        self.config = load_config()
        if container_name in self.config.pinned:
            self.config.pinned = [n for n in self.config.pinned if n != container_name]
            ui.notify(f"Unpinned '{container_name}'.", type="info")
        else:
            self.config.pinned.append(container_name)
            ui.notify(f"Pinned '{container_name}'.", type="positive")
        save_config(self.config)
        await self.refresh_all()

    async def save_notification_settings(self) -> None:
        self.config = load_config()
        self.config.webhook_url = (self.webhook_input.value or "").strip()
        self.config.discord_webhook = (self.discord_input.value or "").strip()
        self.config.ntfy_url = (self.ntfy_input.value or "").strip()
        save_config(self.config)
        ui.notify("Notification settings saved.", type="positive")

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
                    deployed_tag="1.0.0",
                    remote_tag="1.1.0",
                    comparison_basis="version",
                    comparison_reason="remote version 1.1.0 is newer than deployed 1.0.0",
                )
            ]
        errors = await send_configured_notifications(sample_results, self.config, apply_filters=False)
        if errors:
            ui.notify("Test notification failed: " + "; ".join(errors), type="negative")
        else:
            ui.notify("Test notification sent.", type="positive")


def register_dashboard_page() -> None:
    @ui.page("/")
    async def _dashboard() -> None:
        apply_theme()
        controller = DashboardController()
        await controller.refresh_all()
