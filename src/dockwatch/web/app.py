"""NiceGUI app entrypoint for dockwatch."""

from __future__ import annotations

from nicegui import ui

from .pages.dashboard import register_dashboard_page
from .theme import apply_theme


def create_app() -> None:
    apply_theme()
    register_dashboard_page()


def run_web_app(*, host: str = "0.0.0.0", port: int = 8080) -> None:
    create_app()
    ui.run(host=host, port=port, title="dockwatch", dark=True, reload=False, show=False)
