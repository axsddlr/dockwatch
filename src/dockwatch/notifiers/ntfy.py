"""ntfy.sh notifier."""

from __future__ import annotations

import httpx

from .base import BaseNotifier, NotificationEvent, render_event_text
from ..links import build_registry_url
from ..models import UpdateResult, comparison_summary, deployed_display_result, remote_display

# ntfy priorities: 3 = default, 4 = high, 5 = urgent.
SEVERITY_PRIORITIES: dict[str, str] = {"info": "3", "warning": "4", "error": "5"}
DEFAULT_PRIORITY = SEVERITY_PRIORITIES["info"]

EVENT_KIND_TAGS: dict[str, str] = {
    "health": "whale,heartbeat",
    "prune": "whale,broom",
    "hook": "whale,warning",
}
DEFAULT_TAGS = "whale"


def event_priority(severity: str) -> str:
    """Deterministically map an event severity to an ntfy priority header."""
    return SEVERITY_PRIORITIES.get(severity, DEFAULT_PRIORITY)


def event_tags(kind: str) -> str:
    """Deterministically derive the ntfy tags header from an event kind."""
    return EVENT_KIND_TAGS.get(kind, DEFAULT_TAGS)


class NtfyNotifier(BaseNotifier):
    name = "ntfy"

    def __init__(self, url: str) -> None:
        # url is the full topic URL, e.g. https://ntfy.sh/my-topic
        self.url = url.rstrip("/")

    async def send(self, results: list[UpdateResult]) -> None:
        if not results:
            return

        if len(results) == 1:
            result = results[0]
            registry_url = build_registry_url(result.container_info)
            label = "digest drift" if result.digest_drift else (result.event or "check")
            title = f"{result.container_info.name}: {label}"
            message = (
                f"{deployed_display_result(result)} -> {remote_display(result)}\n"
                f"{comparison_summary(result)}"
            )
            if registry_url:
                message = f"{message}\n{registry_url}"
        else:
            new_count = sum(1 for result in results if result.event == "new")
            update_count = sum(1 for result in results if result.event == "update")
            title = f"dockwatch: {len(results)} notification events"
            lines = [
                (
                    f"- {result.container_info.name} "
                    f"[{'digest drift' if result.digest_drift else (result.event or 'check')}]: "
                    f"{deployed_display_result(result)} -> {remote_display(result)} "
                    f"({comparison_summary(result)})"
                )
                for result in results
            ]
            for idx, result in enumerate(results):
                registry_url = build_registry_url(result.container_info)
                if registry_url:
                    lines[idx] = f"{lines[idx]}\n  {registry_url}"
            summary = f"new={new_count}, update={update_count}"
            message = "\n".join([summary, *lines])

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self.url,
                content=message.encode(),
                headers={
                    "X-Title": title,
                    "X-Priority": "3",
                    "X-Tags": "whale,arrow_up",
                    "Content-Type": "text/plain; charset=utf-8",
                },
            )
            response.raise_for_status()

    async def send_event(self, event: NotificationEvent) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self.url,
                content=render_event_text(event).encode(),
                headers={
                    "X-Title": event.title,
                    "X-Priority": event_priority(event.severity),
                    "X-Tags": event_tags(event.kind),
                    "Content-Type": "text/plain; charset=utf-8",
                },
            )
            response.raise_for_status()
