"""Notification integrations for dockwatch."""

from __future__ import annotations

import asyncio

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


def filter_notification_results(results: list[UpdateResult], config: DockwatchConfig) -> list[UpdateResult]:
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

    return [result for result in results if _matches_container_filter(result) and _matches_event_filter(result)]


async def _send_with_retry(notifier: BaseNotifier, results: list[UpdateResult]) -> None:
    delay = 0.25
    for attempt in range(1, 4):
        try:
            await notifier.send(results)
            return
        except Exception:  # noqa: BLE001
            if attempt >= 3:
                raise
            await asyncio.sleep(delay)
            delay *= 2


async def send_configured_notifications(
    results: list[UpdateResult],
    config: DockwatchConfig,
    *,
    apply_filters: bool = True,
) -> list[str]:
    filtered = filter_notification_results(results, config) if apply_filters else results
    if not filtered:
        return []

    errors: list[str] = []
    for notifier in build_notifiers(config):
        try:
            await _send_with_retry(notifier, filtered)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{notifier.name}: {exc}")
    return errors
