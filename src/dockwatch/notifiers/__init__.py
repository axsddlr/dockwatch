"""Notification integrations for dockwatch."""

from __future__ import annotations

from .base import BaseNotifier
from .discord import DiscordNotifier
from .ntfy import NtfyNotifier
from .webhook import WebhookNotifier
from ..config import DockwatchConfig
from ..models import UpdateResult


def build_notifiers(config: DockwatchConfig) -> list[BaseNotifier]:
    notifiers: list[BaseNotifier] = []
    if config.webhook_url:
        notifiers.append(WebhookNotifier(config.webhook_url))
    if config.discord_webhook:
        notifiers.append(DiscordNotifier(config.discord_webhook))
    if config.ntfy_url:
        notifiers.append(NtfyNotifier(config.ntfy_url))
    return notifiers


async def send_configured_notifications(
    results: list[UpdateResult],
    config: DockwatchConfig,
    *,
    apply_filters: bool = True,
) -> list[str]:
    notify_only = set(config.notify_only)
    notify_on = set(config.notify_on)

    def _matches_container_filter(result: UpdateResult) -> bool:
        if result.container_info.notify_enabled is False:
            return False
        if result.container_info.notify_enabled is True:
            return True
        return not notify_only or result.container_info.name in notify_only

    def _matches_event_filter(result: UpdateResult) -> bool:
        if result.event is None:
            return False
        if result.event == "new" and not config.first_check_notify:
            return False
        return result.event in notify_on

    filtered = results
    if apply_filters:
        filtered = [
            result for result in results if _matches_container_filter(result) and _matches_event_filter(result)
        ]
    if not filtered:
        return []

    errors: list[str] = []
    for notifier in build_notifiers(config):
        try:
            await notifier.send(filtered)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{notifier.name}: {exc}")
    return errors
