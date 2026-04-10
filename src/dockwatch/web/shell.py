"""Shared application shell for dockwatch web pages."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from nicegui import ui

from .. import __version__
from .theme import TEXT_MUTED, TEXT_PRIMARY

NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("Dashboard", "/", "dashboard"),
    ("Settings", "/settings", "settings"),
)


@contextmanager
def page_shell(*, active_route: str) -> Iterator[None]:
    """Render the shared top bar and hamburger drawer, then yield page content."""
    menu_button = None
    shell_container = None

    with ui.header().classes("dw-nav").style("padding: 0 16px;"):
        with ui.row().classes("w-full items-center justify-between").style(
            "max-width:1260px; margin:0 auto; min-height:58px;"
        ):
            with ui.row().classes("items-center gap-3"):
                menu_button = ui.button(icon="menu").props("flat round dense").style(
                    f"color:{TEXT_MUTED};"
                )
                ui.label("dockwatch").style(
                    f"font-size:22px; font-weight:700; color:{TEXT_PRIMARY}; "
                    "letter-spacing:-0.03em;"
                )

            ui.label(f"v{__version__}").classes("mono-sm").style(
                "padding:4px 8px; background:#F5F7F8; color:#111315; border-radius:6px;"
            )

    drawer = ui.left_drawer(value=False)
    drawer.props("show-if-above bordered")
    drawer.classes("dw-drawer")
    with drawer:
        ui.label("Navigation").classes("section-label").style("padding: 16px 16px 8px;")
        with ui.column().classes("w-full gap-2").style("padding: 0 10px 16px;"):
            for label, route, icon in NAV_ITEMS:
                classes = "dw-drawer-link active" if route == active_route else "dw-drawer-link"
                ui.button(
                    label,
                    icon=icon,
                    on_click=lambda _=None, path=route: ui.navigate.to(path),
                ).props("flat no-caps align=left").classes(classes)

    def sync_shell_layout(*_args) -> None:
        if shell_container is None:
            return
        if drawer.value:
            shell_container.classes(add="dw-shell--anchored")
            shell_container.classes(remove="dw-shell--centered")
        else:
            shell_container.classes(add="dw-shell--centered")
            shell_container.classes(remove="dw-shell--anchored")

    if menu_button is not None:
        menu_button.on("click", lambda: (drawer.toggle(), sync_shell_layout()))

    shell_container = ui.column().classes("dw-shell")
    with shell_container:
        sync_shell_layout()
        drawer.on_value_change(lambda _event: sync_shell_layout())
        yield
