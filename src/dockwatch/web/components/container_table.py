"""Reusable table-style container status component for the dockwatch dashboard."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from nicegui import ui

from ...links import build_registry_link
from ...models import UpdateResult, deployed_display_result, remote_display
from ...updater import UpdatePlan
from ..theme import PRIMARY, STATUS_BG, STATUS_COLOR, TEXT_MUTED, TEXT_PRIMARY

CheckHandler = Callable[[str], Awaitable[None]]
PinHandler = Callable[[str], Awaitable[None]]
UpdateHandler = Callable[[str], Awaitable[None]]


def _status_label(result: UpdateResult) -> str:
    if result.status == "PINNED":
        return "PINNED"
    if result.check_error:
        return "UNKNOWN"
    if result.is_outdated is True:
        return "OUTDATED"
    if result.is_outdated is False:
        return "UP-TO-DATE"
    return "UNKNOWN"


def _bump_meta(result: UpdateResult) -> tuple[str, str] | None:
    if result.version_diff is None:
        return None
    bump_type = result.version_diff.bump_type
    if bump_type == "UNKNOWN":
        return None
    color = {
        "MAJOR": "#F87171",
        "MINOR": "#FBBF24",
        "PATCH": "#3FE17F",
        "PRE-RELEASE": PRIMARY,
    }.get(bump_type, PRIMARY)
    return bump_type, color


def _should_hide_update_button(plan: UpdatePlan | None) -> bool:
    if plan is None or plan.allowed or not plan.reason:
        return False
    return "missing from config.compose_projects" in plan.reason


class ContainerStatusTable:
    def __init__(self) -> None:
        self.container = ui.column().classes("w-full")

    def render(
        self,
        results: list[UpdateResult],
        on_check: CheckHandler,
        on_pin_toggle: PinHandler,
        on_update: UpdateHandler,
        update_plans: dict[str, UpdatePlan],
        *,
        empty_message: str = "No containers to display.",
    ) -> None:
        self.container.clear()

        with self.container:
            if not results:
                with ui.card().classes("dw-panel w-full").style("padding:28px; text-align:center;"):
                    ui.icon("inbox", size="34px").style(f"color:{TEXT_MUTED};")
                    ui.label("No containers to display.").style(
                        f"color:{TEXT_MUTED}; margin-top:8px; font-size:13px;"
                    )
                    if empty_message != "No containers to display.":
                        ui.label(empty_message).style(
                            f"color:{TEXT_MUTED}; margin-top:4px; font-size:12px;"
                        )
                return

            with ui.element("div").classes("dw-table-wrap w-full"):
                with ui.element("div").classes("dw-table-head"):
                    _head("Name")
                    _head("Status")
                    _head("Basis")
                    _head("Deployed")
                    _head("Remote")
                    _head("Actions")

                for result in results:
                    self._render_row(result, on_check, on_pin_toggle, on_update, update_plans)

    def _render_row(
        self,
        result: UpdateResult,
        on_check: CheckHandler,
        on_pin_toggle: PinHandler,
        on_update: UpdateHandler,
        update_plans: dict[str, UpdatePlan],
    ) -> None:
        status = _status_label(result)
        pill_bg = STATUS_BG.get(status, "rgba(255,255,255,0.05)")
        pill_color = STATUS_COLOR.get(status, TEXT_PRIMARY)
        name = result.container_info.name or "-"
        image_ref = result.container_info.image_ref or "-"
        deployed_value = deployed_display_result(result) or "-"
        remote_value = remote_display(result) or "-"
        registry_link = build_registry_link(result.container_info)
        pin_label = "Unpin" if result.status == "PINNED" else "Pin"
        update_plan = update_plans.get(name)
        dot_class = {
            "UP-TO-DATE": "dot-green",
            "OUTDATED": "dot-red",
            "UNKNOWN": "dot-yellow",
            "PINNED": "dot-blue",
        }[status]

        with ui.element("div").classes("dw-table-row"):
            with ui.element("div").classes("dw-name-cell"):
                ui.html(f'<span class="status-dot {dot_class}"></span>')
                with ui.element("div").classes("dw-name-stack"):
                    ui.label(name).classes("dw-name-title")
                    with ui.row().classes("dw-meta-row"):
                        if result.container_info.source == "portainer":
                            ui.label(result.container_info.environment_name or "Portainer").classes("dw-source-pill")
                        if registry_link:
                            label, url = registry_link
                            with ui.row().classes("items-center gap-1 no-wrap"):
                                ui.link(label, url).props("target=_blank").classes("dw-registry-link")
                                ui.icon("open_in_new", size="11px").classes("dw-registry-link-icon")
                    ui.label(image_ref).classes("dw-name-subtitle")

            _status_cell(status, pill_bg, pill_color)
            _cell(result.comparison_basis or "-", label="Basis")
            _cell(deployed_value, label="Deployed", mono=True)
            _remote_cell(remote_value, result)

            with ui.row().classes("dw-actions"):
                ui.button(
                    "Check",
                    icon="refresh",
                    on_click=lambda _=None, n=name: on_check(n),
                ).props("unelevated size=sm").classes("dw-btn-secondary")
                if not _should_hide_update_button(update_plan):
                    update_button = ui.button(
                        "Update",
                        icon="upgrade",
                        on_click=lambda _=None, n=name: on_update(n),
                    ).props("unelevated size=sm").classes("dw-btn-ghost")
                    if update_plan is not None and not update_plan.allowed:
                        update_button.props("disable")
                        if update_plan.reason:
                            update_button.tooltip(update_plan.reason)
                ui.button(
                    pin_label,
                    icon="push_pin",
                    on_click=lambda _=None, n=name: on_pin_toggle(n),
                ).props("outline size=sm").classes("dw-btn-ghost")


def _head(label: str) -> None:
    ui.label(label).classes("dw-col-label")


def _status_cell(text: str, bg: str, color: str) -> None:
    with ui.element("div").classes("dw-data-cell").props('data-label="Status"'):
        ui.html(
            f'<span class="status-pill" style="background:{bg}; color:{color};">{text}</span>'
        )


def _cell(value: str, *, label: str, mono: bool = False) -> None:
    classes = "dw-data-cell mono" if mono else "dw-data-cell"
    ui.label(value).classes(classes).props(f'data-label="{label}"')


def _remote_cell(value: str, result: UpdateResult) -> None:
    with ui.element("div").classes("dw-data-cell").props('data-label="Remote"'):
        with ui.row().classes("items-center gap-2 no-wrap"):
            remote_label = ui.label(value).classes("dw-data-cell mono")
            if result.version_diff is not None:
                remote_label.tooltip(f"{result.version_diff.current_raw} -> {result.version_diff.latest_raw} ({result.version_diff.bump_type})")
            bump_meta = _bump_meta(result)
            if bump_meta and result.is_outdated:
                bump_type, color = bump_meta
                ui.html(
                    f'<span class="dw-bump-badge" style="background:{color}1F; color:{color}; border-color:{color}55;">{bump_type}</span>'
                )
