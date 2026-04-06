"""Generic webhook notifier."""

from __future__ import annotations

import httpx

from .base import BaseNotifier
from ..models import UpdateResult


class WebhookNotifier(BaseNotifier):
    name = "webhook"

    def __init__(self, url: str) -> None:
        self.url = url

    async def send(self, results: list[UpdateResult]) -> None:
        payload = {
            "summary": {
                "outdated": sum(1 for result in results if result.is_outdated is True),
                "up_to_date": sum(1 for result in results if result.is_outdated is False),
                "unknown": sum(1 for result in results if result.is_outdated is None),
            },
            "results": [
                {
                    "name": result.container_info.name,
                    "image": result.container_info.image_ref,
                    "current": result.container_info.current_tag,
                    "latest": result.latest_tag,
                    "status": result.status,
                    "error": result.check_error,
                    "is_outdated": result.is_outdated,
                }
                for result in results
            ],
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(self.url, json=payload)
            response.raise_for_status()