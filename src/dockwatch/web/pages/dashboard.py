"""Dashboard page for dockwatch NiceGUI frontend."""

from __future__ import annotations

import asyncio
from datetime import datetime

from nicegui import ui

from ... import __version__
from ...config import load_config, save_config
from ...db import ManifestStore
from ...docker_client import DockerConnectionError, get_running_containers
from ...integrations import PortainerEnvironment
from ...models import UpdateResult
from ...registry import check_all
from ...sources import discover_containers
from ...updater import build_update_plan, describe_update_plan, execute_update
from ..components.container_table import ContainerStatusTable
from ..shell import page_shell
from ..theme import (
    BORDER,
    PRIMARY,
    STATUS_BLUE,
    STATUS_GREEN,
    STATUS_RED,
    STATUS_YELLOW,
    TEXT_MUTED,
    TEXT_PRIMARY,
    apply_theme,
)

_DASHBOARD_CACHE: dict[str, object] = {
    "results": [],
    "selected_statuses": set(),
    "last_checked": "Never",
    "selected_source": "local",
    "selected_environment": None,
}


def _summary_chip(label: str, value_ref: list[str], color: str) -> ui.label:
    with ui.card().classes("dw-summary-chip"):
        ui.label(label).classes("dw-summary-label")
        value = ui.label(value_ref[0]).style(
            f"font-size:24px; line-height:1.1; font-weight:700; color:{color}; margin-top:4px;"
            "font-family:'Fira Code', monospace;"
        )
    return value


class DashboardController:
    def __init__(self) -> None:
        self.results: list[UpdateResult] = list(_DASHBOARD_CACHE["results"])
        self.selected_statuses: set[str] = set(_DASHBOARD_CACHE["selected_statuses"])
        self.last_checked: str = str(_DASHBOARD_CACHE["last_checked"])
        self.selected_source: str = str(_DASHBOARD_CACHE["selected_source"])
        self.selected_environment: str | None = (
            str(_DASHBOARD_CACHE["selected_environment"])
            if _DASHBOARD_CACHE["selected_environment"] is not None
            else None
        )
        self.config = load_config()
        self.store = ManifestStore()
        self._loading = False
        self.available_environments: list[PortainerEnvironment] = []

        with ui.row().classes("dw-page-meta w-full"):
            with ui.column().classes("gap-0"):
                ui.label("Monitoring").classes("section-label")
                ui.label("Container Update Dashboard").style(
                    f"font-size:18px; font-weight:700; color:{TEXT_PRIMARY};"
                )
            with ui.row().classes("items-center gap-3"):
                self.conn_label = ui.label("connected").style(
                    f"font-size:12px; color:{TEXT_MUTED};"
                )
                ui.label(f"v{__version__}").classes("mono-sm").style(
                    "padding:4px 8px; background:#F5F7F8; color:#111315; border-radius:6px;"
                )

        with ui.row().classes("dw-summary-strip w-full"):
            self._stat_total_val = _summary_chip("Containers", ["0"], TEXT_PRIMARY)
            self._stat_ok_val = _summary_chip("Up To Date", ["0"], STATUS_GREEN)
            self._stat_outdated_val = _summary_chip("Outdated", ["0"], STATUS_RED)
            self._stat_pinned_val = _summary_chip("Pinned", ["0"], STATUS_BLUE)

        with ui.card().classes("dw-panel w-full"):
            with ui.column().classes("dw-toolbar-stack w-full"):
                with ui.row().classes("dw-toolbar-group"):
                    self.refresh_btn = (
                        ui.button("Refresh", on_click=self.refresh_all, icon="refresh")
                        .props("unelevated")
                        .classes("dw-btn-primary")
                    )
                    self.auto_refresh_switch = ui.switch("Auto refresh", value=False).style(
                        f"color:{TEXT_MUTED};"
                    )
                    self.interval_seconds = (
                        ui.number("Interval (s)", value=30, min=10, max=3600, step=5)
                        .classes("dw-input-shell")
                        .style("width:140px;")
                        .props("dark dense borderless")
                    )
                    self.source_toggle = ui.toggle(
                        {"local": "Local Docker", "portainer": "Portainer", "all": "All"},
                        value=self.selected_source,
                        on_change=self._on_source_change,
                    ).props("unelevated").classes("dw-source-toggle")
                    self.environment_select = (
                        ui.select({}, value=self.selected_environment)
                        .classes("dw-input-shell")
                        .style("min-width:180px;")
                        .props("dark dense borderless")
                    )
                    self.environment_select.on_value_change(self._on_environment_change)

                with ui.row().classes("dw-toolbar-row-secondary"):
                    self.filter_row = ui.row().classes("dw-filter-row")
                    with ui.row().classes("dw-toolbar-group dw-toolbar-meta"):
                        self.last_checked_label = ui.label("last check: never").classes("mono-sm").style(
                            f"color:{TEXT_MUTED};"
                        )
                        self.container_count_label = ui.label("0 containers").classes("mono-sm").style(
                            f"color:{TEXT_MUTED};"
                        )

        self.error_banner = ui.card().classes("dw-panel w-full").style(
            f"padding: 12px 14px; border-left: 3px solid {STATUS_RED} !important; display:none;"
        )
        with self.error_banner:
            with ui.row().classes("items-center gap-2"):
                ui.icon("error_outline", size="18px").style(f"color:{STATUS_RED};")
                self.message_label = ui.label("").style(f"color:{STATUS_RED}; font-weight:600;")
            self.error_help = ui.markdown("").style(f"color:{TEXT_MUTED}; margin-top:6px;")

        with ui.card().classes("dw-panel w-full").style("padding: 10px 10px 4px;"):
            with ui.row().classes("dw-section-head"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("inventory_2", size="18px").style(f"color:{PRIMARY};")
                    self.table_section_label = ui.label("Local Containers").classes("section-label")
                self.conn_meta = ui.label("docker host online").classes("mono-sm").style(
                    f"color:{TEXT_MUTED};"
                )

            self.loading_row = ui.row().classes("w-full justify-center").style("padding:26px 0;")
            with self.loading_row:
                ui.spinner("dots", size="34px", color="primary")

            self.table = ContainerStatusTable()

        with ui.row().classes("dw-footer w-full justify-center").style("padding:16px 0;"):
            ui.label(f"dockwatch {__version__} - image monitoring dashboard").classes("mono-sm")

        self.loading_row.set_visibility(False)
        self.table.container.set_visibility(False)

        self.timer = ui.timer(
            interval=float(self.config.schedule_interval_seconds),
            callback=self._timer_refresh,
            active=False,
        )
        self.auto_refresh_switch.on_value_change(self._on_toggle_auto_refresh)
        self.interval_seconds.on_value_change(self._on_interval_change)
        self._render_filter_controls()
        self._hydrate_view()

    def _persist_state(self) -> None:
        _DASHBOARD_CACHE["results"] = list(self.results)
        _DASHBOARD_CACHE["selected_statuses"] = set(self.selected_statuses)
        _DASHBOARD_CACHE["last_checked"] = self.last_checked
        _DASHBOARD_CACHE["selected_source"] = self.selected_source
        _DASHBOARD_CACHE["selected_environment"] = self.selected_environment

    def _hydrate_view(self) -> None:
        self._update_environment_selector()
        self._update_source_meta()
        if self.last_checked != "Never":
            self.last_checked_label.set_text(f"last check: {self.last_checked}")
        self._update_stats()
        self._render_table()
        if self.results:
            self.conn_label.set_text("connected")
            self._update_source_meta()
            self.table.container.set_visibility(True)
        else:
            self.table.container.set_visibility(False)

    def _update_environment_selector(self) -> None:
        options = {str(environment.id): environment.name for environment in self.available_environments}
        self.environment_select.options = options
        self.environment_select.value = self.selected_environment
        visible = self.selected_source in {"portainer", "all"} and bool(options)
        self.environment_select.set_visibility(visible)

    def _update_source_meta(self) -> None:
        if self.selected_source == "portainer":
            self.table_section_label.set_text("Portainer Containers")
            self.conn_meta.set_text("portainer source active")
            return
        if self.selected_source == "all":
            self.table_section_label.set_text("All Containers")
            self.conn_meta.set_text("local docker and portainer")
            return
        self.table_section_label.set_text("Local Containers")
        self.conn_meta.set_text("docker host online")

    def _status_text(self, result: UpdateResult) -> str:
        if result.status == "PINNED":
            return "PINNED"
        if result.check_error:
            return "UNKNOWN"
        if result.is_outdated is True:
            return "OUTDATED"
        if result.is_outdated is False:
            return "UP-TO-DATE"
        return "UNKNOWN"

    def _filtered_results(self) -> list[UpdateResult]:
        if not self.selected_statuses:
            return self.results
        return [result for result in self.results if self._status_text(result) in self.selected_statuses]

    def _status_count(self, status: str) -> int:
        return sum(1 for result in self.results if self._status_text(result) == status)

    def _render_table(self) -> None:
        filtered = self._filtered_results()
        plans = {
            result.container_info.name: build_update_plan(result, self.config)
            for result in filtered
        }
        if self.selected_statuses and not filtered:
            empty_message = "No containers match the selected status filters."
        else:
            empty_message = "No containers to display."
        self.table.render(
            filtered,
            self.check_one,
            self.toggle_pin,
            self.update_one,
            plans,
            empty_message=empty_message,
        )

    def _filter_button_style(self, active: bool, color: str) -> str:
        if active:
            return (
                f"background:{color}26; color:{TEXT_PRIMARY}; border:1px solid {color}59; "
                "border-radius:10px; min-height:34px; box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);"
            )
        return (
            f"background:transparent; color:{TEXT_MUTED}; border:1px solid {BORDER}; "
            "border-radius:10px; min-height:34px;"
        )

    def _render_filter_controls(self) -> None:
        self.filter_row.clear()
        statuses = [
            ("OUTDATED", STATUS_RED),
            ("UNKNOWN", STATUS_YELLOW),
            ("UP-TO-DATE", STATUS_GREEN),
            ("PINNED", STATUS_BLUE),
        ]
        with self.filter_row:
            ui.label("Filter").classes("section-label")
            with ui.row().classes("dw-filter-rail"):
                ui.button(
                    f"All {len(self.results)}",
                    on_click=self.clear_status_filters,
                ).props("unelevated dense no-caps").classes("dw-filter-segment").style(
                    self._filter_button_style(not self.selected_statuses, PRIMARY)
                )
                for status, color in statuses:
                    count = self._status_count(status)
                    ui.button(
                        f"{status} {count}",
                        on_click=lambda _=None, s=status: self.toggle_status_filter(s),
                    ).props("unelevated dense no-caps").classes("dw-filter-segment").style(
                        self._filter_button_style(status in self.selected_statuses, color)
                    )

    def _update_stats(self) -> None:
        total = len(self.results)
        ok = sum(1 for r in self.results if r.is_outdated is False and r.status != "PINNED")
        outdated = sum(1 for r in self.results if r.is_outdated is True)
        pinned = sum(1 for r in self.results if r.status == "PINNED")

        self._stat_total_val.set_text(str(total))
        self._stat_ok_val.set_text(str(ok))
        self._stat_outdated_val.set_text(str(outdated))
        self._stat_pinned_val.set_text(str(pinned))
        visible = len(self._filtered_results())
        if self.selected_statuses:
            self.container_count_label.set_text(f"{total} containers  {visible} shown")
        else:
            self.container_count_label.set_text(f"{total} containers")

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
            f"padding: 12px 14px; border-left: 3px solid {STATUS_RED} !important;"
        )
        self.message_label.set_text(msg)
        self.error_help.set_content(detail)

    def _clear_error(self) -> None:
        self.error_banner.style(
            f"padding: 12px 14px; border-left: 3px solid {STATUS_RED} !important; display:none;"
        )
        self.message_label.set_text("")
        self.error_help.set_content("")

    def _on_toggle_auto_refresh(self, event) -> None:
        self.timer.active = bool(event.value)

    def _on_interval_change(self, event) -> None:
        new_value = float(event.value or self.config.schedule_interval_seconds)
        self.timer.interval = max(10, new_value)

    async def _on_source_change(self, event) -> None:
        self.selected_source = str(event.value or "local")
        if self.selected_source == "local":
            self.selected_environment = None
        self._persist_state()
        await self.refresh_all()

    async def _on_environment_change(self, event) -> None:
        self.selected_environment = str(event.value) if event.value else None
        self._persist_state()
        await self.refresh_all()

    async def _timer_refresh(self) -> None:
        await self.refresh_all()

    def clear_status_filters(self) -> None:
        self.selected_statuses.clear()
        self._render_filter_controls()
        self._update_stats()
        self._render_table()
        self._persist_state()

    def toggle_status_filter(self, status: str) -> None:
        if status in self.selected_statuses:
            self.selected_statuses.remove(status)
        else:
            self.selected_statuses.add(status)
        self._render_filter_controls()
        self._update_stats()
        self._render_table()
        self._persist_state()

    async def refresh_all(self) -> None:
        self._set_loading(True)
        try:
            self.config = load_config()
            discovery = await discover_containers(
                self.config,
                source=self.selected_source,
                selected_environment=self.selected_environment,
            )
            self.available_environments = discovery.environments
            self._update_environment_selector()
            containers = discovery.containers
            if discovery.errors:
                self._show_error(discovery.errors[0])
            else:
                self._clear_error()
            self.conn_label.set_text("connected" if containers or not discovery.errors else "disconnected")
            self._update_source_meta()
            self.results = await check_all(
                containers,
                self.config,
                store=self.store,
                max_concurrency=self.config.max_concurrent_checks,
            )
            self._update_last_checked()
            self._update_stats()
            self._render_table()
            self._persist_state()
        except DockerConnectionError as exc:
            self.conn_label.set_text("disconnected")
            self.conn_meta.set_text("docker host offline")
            self._show_error(
                str(exc),
                "**Fixes to try:**\n"
                "- Ensure Docker Desktop/daemon is running\n"
                "- Verify access to Docker socket/pipe\n"
                "- Re-open dashboard after Docker is healthy",
            )
            self.results = []
            self._update_stats()
            self._render_table()
            self._persist_state()
        finally:
            self._set_loading(False)

    async def check_one(self, container_name: str) -> None:
        if not container_name:
            return

        existing = next((item for item in self.results if item.container_info.name == container_name), None)
        if existing is not None and existing.container_info.source != "local":
            await self.refresh_all()
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
        self._render_table()
        self._persist_state()

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

    async def update_one(self, container_name: str) -> None:
        target = next((item for item in self.results if item.container_info.name == container_name), None)
        if target is None:
            ui.notify(f"Container '{container_name}' is no longer available.", type="warning")
            return

        self.config = load_config()
        plan = build_update_plan(target, self.config)
        if not plan.allowed:
            ui.notify(plan.reason or "Update is blocked.", type="warning")
            return

        with ui.dialog() as dialog, ui.card().classes("dw-panel").style("padding:16px; min-width:460px;"):
            ui.label(f"Update {container_name}?").style(
                f"font-size:17px; font-weight:700; color:{TEXT_PRIMARY};"
            )
            ui.label("This will pull the newer image and replace the current container safely.").style(
                f"color:{TEXT_MUTED}; font-size:12px;"
            )
            with ui.column().classes("w-full").style("gap:6px; margin-top:8px;"):
                for line in describe_update_plan(plan):
                    ui.label(line).classes("mono-sm").style(f"color:{TEXT_PRIMARY};")
            with ui.row().classes("justify-end w-full").style("margin-top:12px; gap:8px;"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).classes("dw-btn-ghost")
                ui.button("Update", on_click=lambda: dialog.submit(True)).classes("dw-btn-secondary")

        confirmed = await dialog
        if not confirmed:
            return

        self._set_loading(True)
        try:
            result = await asyncio.to_thread(execute_update, plan, self.config)
            if result.success:
                ui.notify(result.message, type="positive")
            else:
                detail = result.rollback_message or (result.details[0] if result.details else "")
                ui.notify(f"{result.message}{': ' + detail if detail else ''}", type="negative")
        finally:
            self._set_loading(False)

        await self.refresh_all()

def register_dashboard_page() -> None:
    @ui.page("/")
    async def _dashboard() -> None:
        apply_theme()
        with page_shell(active_route="/"):
            controller = DashboardController()
            if not controller.results and controller.last_checked == "Never":
                await controller.refresh_all()
