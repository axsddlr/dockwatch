"""Settings page for notification configuration."""

from __future__ import annotations

from nicegui import ui

from ... import __version__
from ...config import PortainerConfig, load_config, save_config
from ...integrations import PortainerClient, PortainerError
from ...models import ContainerInfo, RegistryType, UpdateResult
from ...notifiers import send_configured_notifications
from ..shell import page_shell
from ..theme import TEXT_DIM, TEXT_MUTED, TEXT_PRIMARY, apply_theme


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

        with ui.column().classes("dw-settings-wrap"):
            with ui.row().classes("dw-page-meta w-full"):
                with ui.column().classes("gap-0"):
                    ui.label("Settings").classes("section-label")
                    ui.label("Notification Delivery").style(
                        f"font-size:18px; font-weight:700; color:{TEXT_PRIMARY};"
                    )
                ui.label(f"dockwatch {__version__}").classes("mono-sm").style(f"color:{TEXT_MUTED};")

            with ui.element("div").classes("dw-settings-grid w-full"):
                with ui.card().classes("dw-panel dw-settings-side").style("padding: 16px;"):
                    ui.label("Channels").classes("section-label")
                    ui.label("Webhook, Discord, and ntfy delivery settings.").style(
                        f"color:{TEXT_MUTED}; font-size:13px; line-height:1.45;"
                    )
                    ui.label("Test sends use a sample outdated container event.").style(
                        f"color:{TEXT_DIM}; font-size:12px; line-height:1.45;"
                    )
                    ui.separator()
                    ui.label("Portainer").classes("section-label")
                    ui.label("Optional read-only source for Portainer-managed environments.").style(
                        f"color:{TEXT_DIM}; font-size:12px; line-height:1.45;"
                    )

                with ui.column().classes("dw-settings-main"):
                    with ui.card().classes("dw-panel w-full").style("padding: 16px;"):
                        with ui.column().classes("w-full gap-3"):
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
                    with ui.card().classes("dw-panel w-full").style("padding: 16px;"):
                        with ui.column().classes("w-full gap-3"):
                            self.portainer_enabled = ui.switch(
                                "Enable Portainer", value=self.config.portainer.enabled
                            )
                            self.portainer_url = (
                                ui.input("Portainer URL", value=self.config.portainer.url)
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.portainer_api_key = (
                                ui.input(
                                    "Portainer API Key",
                                    value=self.config.portainer.api_key,
                                    password=True,
                                )
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.portainer_environments = (
                                ui.input(
                                    "Portainer Environments",
                                    value=", ".join(self.config.portainer.environments),
                                    placeholder="empty = all, or comma-separated environment IDs",
                                )
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                    with ui.card().classes("dw-panel w-full").style("padding: 14px 16px;"):
                        with ui.row().classes("items-center gap-3"):
                            ui.button("Save Settings", on_click=self.save_notification_settings).props(
                                "unelevated"
                            ).classes("dw-btn-secondary")
                            ui.button(
                                "Send Test Notification", on_click=self.send_test_notification
                            ).props("outline").classes("dw-btn-ghost")
                            ui.button(
                                "Test Portainer Connection", on_click=self.test_portainer_connection
                            ).props("outline").classes("dw-btn-ghost")

            with ui.row().classes("dw-footer w-full justify-center").style("padding:16px 0;"):
                ui.label("Notification settings").classes("mono-sm")

    async def save_notification_settings(self) -> None:
        self.config = load_config()
        self.config.webhook_url = (self.webhook_input.value or "").strip()
        self.config.discord_webhook = (self.discord_input.value or "").strip()
        self.config.ntfy_url = (self.ntfy_input.value or "").strip()
        self.config.portainer = PortainerConfig(
            enabled=bool(self.portainer_enabled.value),
            url=(self.portainer_url.value or "").strip(),
            api_key=(self.portainer_api_key.value or "").strip(),
            environments=[
                item.strip()
                for item in str(self.portainer_environments.value or "").split(",")
                if item.strip()
            ],
        )
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

    async def test_portainer_connection(self) -> None:
        try:
            client = PortainerClient(
                base_url=(self.portainer_url.value or "").strip(),
                api_key=(self.portainer_api_key.value or "").strip(),
            )
            environments = await client.test_connection()
        except (PortainerError, Exception) as exc:  # noqa: BLE001
            ui.notify(f"Portainer connection failed: {exc}", type="negative")
            return
        ui.notify(f"Connected to Portainer ({len(environments)} environment(s)).", type="positive")


def register_settings_page() -> None:
    @ui.page("/settings")
    async def _settings() -> None:
        apply_theme()
        with page_shell(active_route="/settings"):
            SettingsController()
