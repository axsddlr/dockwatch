"""Reusable container status table component for the NiceGUI dashboard."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from nicegui import ui

from ...links import build_registry_link
from ...models import UpdateResult

CheckHandler = Callable[[str], Awaitable[None]]
PinHandler = Callable[[str], Awaitable[None]]


class ContainerStatusTable:
    def __init__(self) -> None:
        with ui.column().classes("w-full gap-2"):
            with ui.row().classes("w-full text-bold text-grey-7 hidden md:flex"):
                ui.label("Name").classes("w-2/12")
                ui.label("Image").classes("w-3/12")
                ui.label("Current Tag").classes("w-2/12")
                ui.label("Latest Tag").classes("w-2/12")
                ui.label("Status").classes("w-2/12")
                ui.label("Registry").classes("w-1/12")
                ui.label("Actions").classes("w-1/12")
            self.rows_container = ui.column().classes("w-full gap-1")

    def _status(self, result: UpdateResult) -> tuple[str, str]:
        if result.status == "PINNED":
            return "PINNED", "primary"
        if result.check_error:
            return "UNKNOWN", "yellow"
        if result.is_outdated is True:
            return "OUTDATED", "red"
        if result.is_outdated is False:
            return "UP-TO-DATE", "green"
        return "UNKNOWN", "yellow"

    def _current_display(self, result: UpdateResult) -> str:
        container = result.container_info
        if container.current_tag.lower() == "latest":
            hint = container.version_label or container.labels.get("build_version")
            if hint:
                return f"latest ({hint})"
        return container.current_tag or "-"

    def render(self, results: list[UpdateResult], on_check: CheckHandler, on_pin_toggle: PinHandler) -> None:
        self.rows_container.clear()

        if not results:
            with self.rows_container:
                with ui.card().classes("w-full"):
                    ui.label("No containers available.")
            return

        with self.rows_container:
            for result in results:
                status_text, badge_color = self._status(result)
                latest_value = result.latest_tag or "-"
                if result.check_error:
                    latest_value = result.check_error

                with ui.card().classes("w-full"):
                    with ui.row().classes("w-full items-center gap-2 flex-wrap md:flex-nowrap"):
                        ui.label(result.container_info.name or "-").classes("w-full md:w-2/12")
                        ui.label(result.container_info.image_ref or "-").classes("w-full md:w-3/12 break-all")
                        ui.label(self._current_display(result)).classes("w-full md:w-2/12")
                        ui.label(latest_value).classes("w-full md:w-2/12 break-all")
                        with ui.row().classes("w-full md:w-2/12"):
                            ui.badge(status_text, color=badge_color)
                        with ui.row().classes("w-full md:w-1/12"):
                            registry_link = build_registry_link(result.container_info)
                            if registry_link:
                                label, registry_url = registry_link
                                ui.link(label, registry_url).props("target=_blank")
                            else:
                                ui.label("-")
                        with ui.row().classes("w-full md:w-1/12 gap-1"):
                            ui.button(
                                "Check",
                                on_click=lambda _=None, name=result.container_info.name: on_check(name),
                            ).props("size=sm")
                            pin_label = "Unpin" if result.status == "PINNED" else "Pin"
                            ui.button(
                                pin_label,
                                on_click=lambda _=None, name=result.container_info.name: on_pin_toggle(name),
                            ).props("size=sm flat")
