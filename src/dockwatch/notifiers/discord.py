"""Discord webhook notifier."""

from __future__ import annotations

import httpx

from .base import BaseNotifier
from ..models import UpdateResult


class DiscordNotifier(BaseNotifier):
    name = "discord"

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    async def send(self, results: list[UpdateResult]) -> None:
        outdated = [result for result in results if result.is_outdated is True]
        unknown = [result for result in results if result.is_outdated is None]

        description = [
            f"Outdated: {len(outdated)}",
            f"Unknown: {len(unknown)}",
            f"Total checked: {len(results)}",
        ]
        fields = []
        for result in outdated[:10]:
            fields.append(
                {
                    "name": result.container_info.name or "unknown",
                    "value": f"{result.container_info.current_tag} -> {result.latest_tag or '?'}",
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