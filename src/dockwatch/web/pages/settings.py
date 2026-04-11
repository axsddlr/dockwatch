"""Settings page for notification configuration."""

from __future__ import annotations

from dataclasses import dataclass

from nicegui import ui

from ... import __version__
from ...config import DockwatchConfig, PortainerConfig, load_config, save_config
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


@dataclass(slots=True)
class SettingsFormData:
    pinned: str
    ignored: str
    notify_only: str
    include_tags: str
    exclude_tags: str
    webhook_url: str
    discord_webhook: str
    ntfy_url: str
    notify_on_new: bool
    notify_on_update: bool
    first_check_notify: bool
    schedule_interval_seconds: int
    schedule_jitter_seconds: int
    run_on_startup: bool
    max_concurrent_checks: int
    portainer_enabled: bool
    portainer_url: str
    portainer_api_key: str
    portainer_environments: str


def _list_text(values: list[str]) -> str:
    return ", ".join(values)


def _parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_settings_form_data(config: DockwatchConfig) -> SettingsFormData:
    return SettingsFormData(
        pinned=_list_text(config.pinned),
        ignored=_list_text(config.ignored),
        notify_only=_list_text(config.notify_only),
        include_tags=_list_text(config.include_tags),
        exclude_tags=_list_text(config.exclude_tags),
        webhook_url=config.webhook_url,
        discord_webhook=config.discord_webhook,
        ntfy_url=config.ntfy_url,
        notify_on_new="new" in config.notify_on,
        notify_on_update="update" in config.notify_on,
        first_check_notify=config.first_check_notify,
        schedule_interval_seconds=config.schedule_interval_seconds,
        schedule_jitter_seconds=config.schedule_jitter_seconds,
        run_on_startup=config.run_on_startup,
        max_concurrent_checks=config.max_concurrent_checks,
        portainer_enabled=config.portainer.enabled,
        portainer_url=config.portainer.url,
        portainer_api_key=config.portainer.api_key,
        portainer_environments=_list_text(config.portainer.environments),
    )


def build_config_from_form(existing: DockwatchConfig, form: SettingsFormData) -> DockwatchConfig:
    notify_on: list[str] = []
    if form.notify_on_new:
        notify_on.append("new")
    if form.notify_on_update:
        notify_on.append("update")

    return DockwatchConfig(
        pinned=_parse_csv_list(form.pinned),
        ignored=_parse_csv_list(form.ignored),
        notify_only=_parse_csv_list(form.notify_only),
        include_tags=_parse_csv_list(form.include_tags),
        exclude_tags=_parse_csv_list(form.exclude_tags),
        notify_on=notify_on,
        first_check_notify=bool(form.first_check_notify),
        webhook_url=form.webhook_url,
        discord_webhook=form.discord_webhook,
        ntfy_url=form.ntfy_url,
        schedule_interval_seconds=int(form.schedule_interval_seconds),
        schedule_jitter_seconds=int(form.schedule_jitter_seconds),
        run_on_startup=bool(form.run_on_startup),
        max_concurrent_checks=int(form.max_concurrent_checks),
        portainer=PortainerConfig(
            enabled=bool(form.portainer_enabled),
            url=form.portainer_url,
            api_key=form.portainer_api_key,
            environments=_parse_csv_list(form.portainer_environments),
        ),
        compose_projects=existing.compose_projects,
    )


class SettingsController:
    def __init__(self) -> None:
        self.config = load_config()
        self.form = build_settings_form_data(self.config)

        with ui.column().classes("dw-settings-wrap"):
            with ui.row().classes("dw-page-meta w-full"):
                with ui.column().classes("gap-0"):
                    ui.label("Settings").classes("section-label")
                    ui.label("Configuration").style(
                        f"font-size:18px; font-weight:700; color:{TEXT_PRIMARY};"
                    )
                ui.label(f"dockwatch {__version__}").classes("mono-sm").style(f"color:{TEXT_MUTED};")

            with ui.element("div").classes("dw-settings-grid w-full"):
                with ui.card().classes("dw-panel dw-settings-side").style("padding: 16px;"):
                    ui.label("Sections").classes("section-label")
                    ui.label("Monitoring scope, tag filters, notification rules, scheduler, and delivery.").style(
                        f"color:{TEXT_MUTED}; font-size:13px; line-height:1.45;"
                    )
                    ui.label("List fields accept comma-separated values. Empty fields stay disabled or unrestricted.").style(
                        f"color:{TEXT_DIM}; font-size:12px; line-height:1.45;"
                    )
                    ui.separator()
                    ui.label("Notifications").classes("section-label")
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
                            ui.label("Monitoring Scope").classes("section-label")
                            self.pinned_input = (
                                ui.input("Pinned Containers", value=self.form.pinned, placeholder="plex, jellyfin")
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.ignored_input = (
                                ui.input("Ignored Containers", value=self.form.ignored, placeholder="db, redis")
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.notify_only_input = (
                                ui.input(
                                    "Notify Only",
                                    value=self.form.notify_only,
                                    placeholder="empty = all matching containers",
                                )
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                    with ui.card().classes("dw-panel w-full").style("padding: 16px;"):
                        with ui.column().classes("w-full gap-3"):
                            ui.label("Tag Filters").classes("section-label")
                            self.include_tags_input = (
                                ui.input(
                                    "Include Tags",
                                    value=self.form.include_tags,
                                    placeholder="^1\\., ^2\\.",
                                )
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.exclude_tags_input = (
                                ui.input(
                                    "Exclude Tags",
                                    value=self.form.exclude_tags,
                                    placeholder="-rc$, -beta$",
                                )
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                    with ui.card().classes("dw-panel w-full").style("padding: 16px;"):
                        with ui.column().classes("w-full gap-3"):
                            ui.label("Notification Delivery").classes("section-label")
                            self.webhook_input = (
                                ui.input("Webhook URL", value=self.form.webhook_url)
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.discord_input = (
                                ui.input("Discord Webhook", value=self.form.discord_webhook)
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.ntfy_input = (
                                ui.input("ntfy Topic URL", value=self.form.ntfy_url)
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                    with ui.card().classes("dw-panel w-full").style("padding: 16px;"):
                        with ui.column().classes("w-full gap-3"):
                            ui.label("Notification Rules").classes("section-label")
                            self.notify_on_new = ui.switch(
                                "Notify on new containers",
                                value=self.form.notify_on_new,
                            )
                            self.notify_on_update = ui.switch(
                                "Notify on updates",
                                value=self.form.notify_on_update,
                            )
                            self.first_check_notify = ui.switch(
                                "Notify on first check",
                                value=self.form.first_check_notify,
                            )
                    with ui.card().classes("dw-panel w-full").style("padding: 16px;"):
                        with ui.column().classes("w-full gap-3"):
                            ui.label("Scheduler").classes("section-label")
                            self.schedule_interval_input = (
                                ui.number(
                                    "Check Interval (seconds)",
                                    value=self.form.schedule_interval_seconds,
                                    min=10,
                                    step=5,
                                )
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.schedule_jitter_input = (
                                ui.number(
                                    "Jitter (seconds)",
                                    value=self.form.schedule_jitter_seconds,
                                    min=0,
                                    step=1,
                                )
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.max_concurrent_checks_input = (
                                ui.number(
                                    "Max Concurrent Checks",
                                    value=self.form.max_concurrent_checks,
                                    min=1,
                                    step=1,
                                )
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.run_on_startup = ui.switch(
                                "Run checks on startup",
                                value=self.form.run_on_startup,
                            )
                    with ui.card().classes("dw-panel w-full").style("padding: 16px;"):
                        with ui.column().classes("w-full gap-3"):
                            ui.label("Portainer").classes("section-label")
                            self.portainer_enabled = ui.switch(
                                "Enable Portainer", value=self.form.portainer_enabled
                            )
                            self.portainer_url = (
                                ui.input("Portainer URL", value=self.form.portainer_url)
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.portainer_api_key = (
                                ui.input(
                                    "Portainer API Key",
                                    value=self.form.portainer_api_key,
                                    password=True,
                                )
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                            self.portainer_environments = (
                                ui.input(
                                    "Portainer Environments",
                                    value=self.form.portainer_environments,
                                    placeholder="empty = all, or comma-separated environment IDs",
                                )
                                .classes("w-full dw-input-shell")
                                .props("dark dense borderless")
                            )
                    with ui.card().classes("dw-panel w-full").style("padding: 14px 16px;"):
                        with ui.row().classes("items-center gap-3"):
                            ui.button("Save Settings", on_click=self.save_settings).props(
                                "unelevated"
                            ).classes("dw-btn-secondary")
                            ui.button(
                                "Send Test Notification", on_click=self.send_test_notification
                            ).props("outline").classes("dw-btn-ghost")
                            ui.button(
                                "Test Portainer Connection", on_click=self.test_portainer_connection
                            ).props("outline").classes("dw-btn-ghost")

            with ui.row().classes("dw-footer w-full justify-center").style("padding:16px 0;"):
                ui.label("Configuration settings").classes("mono-sm")

    def _read_form(self) -> SettingsFormData:
        return SettingsFormData(
            pinned=str(self.pinned_input.value or ""),
            ignored=str(self.ignored_input.value or ""),
            notify_only=str(self.notify_only_input.value or ""),
            include_tags=str(self.include_tags_input.value or ""),
            exclude_tags=str(self.exclude_tags_input.value or ""),
            webhook_url=str(self.webhook_input.value or "").strip(),
            discord_webhook=str(self.discord_input.value or "").strip(),
            ntfy_url=str(self.ntfy_input.value or "").strip(),
            notify_on_new=bool(self.notify_on_new.value),
            notify_on_update=bool(self.notify_on_update.value),
            first_check_notify=bool(self.first_check_notify.value),
            schedule_interval_seconds=int(self.schedule_interval_input.value or 0),
            schedule_jitter_seconds=int(self.schedule_jitter_input.value or 0),
            run_on_startup=bool(self.run_on_startup.value),
            max_concurrent_checks=int(self.max_concurrent_checks_input.value or 0),
            portainer_enabled=bool(self.portainer_enabled.value),
            portainer_url=str(self.portainer_url.value or "").strip(),
            portainer_api_key=str(self.portainer_api_key.value or "").strip(),
            portainer_environments=str(self.portainer_environments.value or ""),
        )

    async def save_settings(self) -> None:
        self.config = build_config_from_form(load_config(), self._read_form())
        save_config(self.config)
        ui.notify("Settings saved.", type="positive")

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
