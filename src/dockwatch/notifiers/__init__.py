"""Notification integrations for dockwatch."""

from __future__ import annotations

from .base import BaseNotifier
from .discord import DiscordNotifier
from .webhook import WebhookNotifier
from ..config import DockwatchConfig
from ..models import UpdateResult


def build_notifiers(config: DockwatchConfig) -> list[BaseNotifier]:
    notifiers: list[BaseNotifier] = []
    if config.webhook_url:
        notifiers.append(WebhookNotifier(config.webhook_url))
    if config.discord_webhook:
        notifiers.append(DiscordNotifier(config.discord_webhook))
    return notifiers


async def send_configured_notifications(results: list[UpdateResult], config: DockwatchConfig) -> list[str]:
    errors: list[str] = []
    for notifier in build_notifiers(config):
        try:
            await notifier.send(results)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{notifier.name}: {exc}")
    return errors