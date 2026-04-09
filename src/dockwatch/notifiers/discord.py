"""Discord webhook notifier."""

from __future__ import annotations

import httpx

from .base import BaseNotifier
from ..links import build_registry_url
from ..models import UpdateResult, comparison_summary, deployed_display_result, remote_display


class DiscordNotifier(BaseNotifier):
    name = "discord"

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    async def send(self, results: list[UpdateResult]) -> None:
        new_events = sum(1 for result in results if result.event == "new")
        update_events = sum(1 for result in results if result.event == "update")
        outdated = [result for result in results if result.is_outdated is True]
        unknown = [result for result in results if result.is_outdated is None]

        description = [
            f"New events: {new_events}",
            f"Update events: {update_events}",
            f"Outdated: {len(outdated)}",
            f"Unknown: {len(unknown)}",
            f"Total checked: {len(results)}",
        ]
        fields = []
        for result in outdated[:10]:
            registry_url = build_registry_url(result.container_info)
            link_text = f" [link]({registry_url})" if registry_url else ""
            fields.append(
                {
                    "name": result.container_info.name or "unknown",
                    "value": (
                        f"{deployed_display_result(result)} -> {remote_display(result)}"
                        f" ({comparison_summary(result)} / {result.event or 'check'}){link_text}"
                    ),
                    "inline": False,
                }
            )
        if not fields:
            for result in results[:10]:
                registry_url = build_registry_url(result.container_info)
                link_text = f" [link]({registry_url})" if registry_url else ""
                fields.append(
                    {
                        "name": result.container_info.name or "unknown",
                        "value": (
                            f"{deployed_display_result(result)} -> {remote_display(result)}"
                            f" ({comparison_summary(result)} / {result.event or 'check'}){link_text}"
                        ),
                        "inline": False,
                    }
                )

        payload = {
            "embeds": [
                {
                    "title": "dockwatch update summary",
                    "description": "\n".join(description),
                    "color": 0xF39C12 if outdated else 0x2ECC71,
                    "fields": fields,
                }
            ]
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(self.webhook_url, json=payload)
            response.raise_for_status()
