"""NiceGUI app entrypoint for dockwatch."""

from __future__ import annotations

from nicegui import ui

from .pages.dashboard import register_dashboard_page


def create_app() -> None:
    register_dashboard_page()


def run_web_app(*, host: str = "0.0.0.0", port: int = 8080) -> None:
    create_app()
    ui.run(host=host, port=port, title="dockwatch", reload=False, show=False)
