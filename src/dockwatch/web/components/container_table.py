"""Reusable container status table component for the dockwatch NiceGUI dashboard."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from nicegui import ui

from ...links import build_registry_link
from ...models import UpdateResult, comparison_summary, deployed_display, remote_display
from ..theme import (
    STATUS_BG,
    STATUS_COLOR,
    TEXT_MUTED,
    TEXT_PRIMARY,
)

CheckHandler = Callable[[str], Awaitable[None]]
PinHandler = Callable[[str], Awaitable[None]]

_DOT_CLASS: dict[str, str] = {
    "UP-TO-DATE": "dot-green",
    "OUTDATED": "dot-red",
    "UNKNOWN": "dot-yellow",
    "PINNED": "dot-blue",
}

_BORDER_CLASS: dict[str, str] = {
    "UP-TO-DATE": "border-l-green",
    "OUTDATED": "border-l-red",
    "UNKNOWN": "border-l-yellow",
    "PINNED": "border-l-blue",
}


def _status_info(result: UpdateResult) -> tuple[str, str, str, str]:
    """Return (status_text, dot_class, border_class, pill_color)."""
    if result.status == "PINNED":
        s = "PINNED"
    elif result.check_error:
        s = "UNKNOWN"
    elif result.is_outdated is True:
        s = "OUTDATED"
    elif result.is_outdated is False:
        s = "UP-TO-DATE"
    else:
        s = "UNKNOWN"
    return s, _DOT_CLASS[s], _BORDER_CLASS[s], STATUS_COLOR[s]


class ContainerStatusTable:
    def __init__(self) -> None:
        self.container = ui.column().classes("w-full gap-2")

    def render(
        self,
        results: list[UpdateResult],
        on_check: CheckHandler,
        on_pin_toggle: PinHandler,
    ) -> None:
        self.container.clear()

        if not results:
            with self.container:
                with ui.card().classes("dw-card w-full").style("padding:32px; text-align:center;"):
                    ui.icon("inbox", size="40px").style(f"color:{TEXT_MUTED};")
                    ui.label("No containers to display.").style(f"color:{TEXT_MUTED}; margin-top:8px;")
            return

        with self.container:
            for result in results:
                status_text, dot_cls, border_cls, pill_color = _status_info(result)
                pill_bg = STATUS_BG.get(status_text, "rgba(255,255,255,0.06)")
                remote_value = remote_display(result)
                reason_value = comparison_summary(result)
                deployed_value = deployed_display(result.container_info)
                registry_link = build_registry_link(result.container_info)
                pin_label = "Unpin" if result.status == "PINNED" else "Pin"
                name = result.container_info.name or "-"

                with ui.card().classes(f"dw-card {border_cls} w-full").style("padding:16px 20px;"):

                    # ── Row 1: name + status pill ──────────────────────────────
                    with ui.row().classes("w-full items-center justify-between gap-2"):
                        with ui.row().classes("items-center gap-2 min-w-0"):
                            ui.html(f'<span class="status-dot {dot_cls}"></span>')
                            ui.label(name).classes("mono").style(
                                f"font-size:15px; font-weight:600; color:{TEXT_PRIMARY}; "
                                "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                            )

                        # Status pill
                        ui.html(
                            f'<span class="status-pill" style="'
                            f'background:{pill_bg}; color:{pill_color};">'
                            f'{status_text}</span>'
                        )

                    # ── Row 2: data fields (2-col grid on md+) ─────────────────
                    with ui.element("div").style(
                        "display:grid; grid-template-columns:1fr 1fr; gap:8px 24px; margin-top:12px;"
                    ):
                        _field("Image", result.container_info.image_ref or "-", mono=True)
                        _field("Reason", reason_value or "-")
                        _field("Deployed", deployed_value or "-", mono=True)
                        _field("Remote", remote_value or "-", mono=True)

                    # ── Row 3: actions ─────────────────────────────────────────
                    with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap").style(
                        "margin-top:12px; padding-top:12px; border-top:1px solid rgba(255,255,255,0.06);"
                    ):
                        # Registry link (left)
                        if registry_link:
                            label_text, registry_url = registry_link
                            ui.link(label_text, registry_url).props("target=_blank").style(
                                f"font-size:12px; color:{TEXT_MUTED}; "
                                "text-decoration:none; font-family:'Fira Code',monospace;"
                                "transition:color 0.15s;"
                            ).classes("hover:text-white")
                        else:
                            ui.element("div")  # spacer

                        # Action buttons (right)
                        with ui.row().classes("items-center gap-2"):
                            ui.button(
                                "Check",
                                icon="sync",
                                on_click=lambda _=None, n=name: on_check(n),
                            ).props("size=sm outline").style(
                                f"color:{TEXT_MUTED}; border-color:rgba(255,255,255,0.15);"
                            )
                            ui.button(
                                pin_label,
                                icon="push_pin",
                                on_click=lambda _=None, n=name: on_pin_toggle(n),
                            ).props("size=sm flat").style(f"color:{TEXT_MUTED};")


def _field(label: str, value: str, *, mono: bool = False) -> None:
    """Render a label+value data field pair."""
    with ui.column().classes("gap-0 min-w-0"):
        ui.label(label).style(
            f"font-size:11px; font-weight:500; color:{TEXT_MUTED}; "
            "text-transform:uppercase; letter-spacing:0.06em;"
        )
        font = "font-family:'Fira Code',monospace; font-size:13px;" if mono else "font-size:13px;"
        ui.label(value).style(
            f"color:{TEXT_PRIMARY}; {font} "
            "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
        )
