"""Generic webhook notifier."""

from __future__ import annotations

import httpx

from .base import BaseNotifier
from ..links import build_registry_url
from ..models import UpdateResult, comparison_summary, deployed_display_result, remote_display


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
                    "deployed_display": deployed_display_result(result),
                    "remote_display": remote_display(result),
                    "registry_url": build_registry_url(result.container_info),
                    "event": result.event,
                    "status": result.status,
                    "error": result.check_error,
                    "is_outdated": result.is_outdated,
                    "deployed_tag": result.deployed_tag,
                    "deployed_version": result.deployed_version,
                    "deployed_digest": result.deployed_digest,
                    "remote_tag": result.remote_tag,
                    "remote_digest": result.remote_digest,
                    "comparison_basis": result.comparison_basis,
                    "comparison_reason": comparison_summary(result),
                }
                for result in results
            ],
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(self.url, json=payload)
            response.raise_for_status()
