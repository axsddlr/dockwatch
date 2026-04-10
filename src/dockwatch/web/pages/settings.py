"""Settings page for notification configuration."""

from __future__ import annotations

from nicegui import ui

from ... import __version__
from ...config import load_config, save_config
from ...models import ContainerInfo, RegistryType, UpdateResult
from ...notifiers import send_configured_notifications
from ..shell import page_shell
from ..theme import TEXT_MUTED, TEXT_PRIMARY, apply_theme


def build_sample_notification_results() -> list[UpdateResult]:
    return [
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


class SettingsController:
    def __init__(self) -> None:
        self.config = load_config()

        with ui.column().classes("w-full").style("max-width: 760px; margin: 0; gap: 14px;"):
            with ui.row().classes("w-full items-center justify-between").style("padding: 2px 2px 0;"):
                with ui.column().classes("gap-0"):
                    ui.label("Settings").classes("section-label")
                    ui.label("Notification Delivery").style(
                        f"font-size:18px; font-weight:700; color:{TEXT_PRIMARY};"
                    )
                ui.label(f"dockwatch {__version__}").classes("mono-sm").style(
                    f"color:{TEXT_MUTED};"
                )

            with ui.card().classes("dw-panel w-full").style("padding: 18px 18px 16px;"):
                with ui.column().classes("w-full gap-3"):
                    ui.label("Configure outbound notifications for webhooks, Discord, or ntfy.").style(
                        f"color:{TEXT_MUTED}; font-size:13px;"
                    )
                    self.webhook_input = (
                        ui.input("Webhook URL", value=self.config.webhook_url)
                        .classes("w-full dw-input-shell")
                        .props("dark dense borderless")
                    )
                    self.discord_input = (
                        ui.input("Discord Webhook", value=self.config.discord_webhook)
                        .classes("w-full dw-input-shell")
                        .props("dark dense borderless")
                    )
                    self.ntfy_input = (
                        ui.input("ntfy Topic URL", value=self.config.ntfy_url)
                        .classes("w-full dw-input-shell")
                        .props("dark dense borderless")
                    )
                    with ui.row().classes("gap-3"):
                        ui.button("Save Settings", on_click=self.save_notification_settings).props(
                            "unelevated"
                        ).classes("dw-btn-secondary")
                        ui.button(
                            "Send Test Notification", on_click=self.send_test_notification
                        ).props("outline").classes("dw-btn-ghost")

            with ui.row().classes("dw-footer w-full justify-center").style("padding:16px 0;"):
                ui.label("Notification settings").classes("mono-sm")

    async def save_notification_settings(self) -> None:
        self.config = load_config()
        self.config.webhook_url = (self.webhook_input.value or "").strip()
        self.config.discord_webhook = (self.discord_input.value or "").strip()
        self.config.ntfy_url = (self.ntfy_input.value or "").strip()
        save_config(self.config)
        ui.notify("Notification settings saved.", type="positive")

    async def send_test_notification(self) -> None:
        self.config = load_config()
        errors = await send_configured_notifications(
            build_sample_notification_results(),
            self.config,
            apply_filters=False,
        )
        if errors:
            ui.notify("Test notification failed: " + "; ".join(errors), type="negative")
        else:
            ui.notify("Test notification sent.", type="positive")


def register_settings_page() -> None:
    @ui.page("/settings")
    async def _settings() -> None:
        apply_theme()
        with page_shell(active_route="/settings"):
            SettingsController()
