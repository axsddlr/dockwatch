"""ntfy.sh notifier."""

from __future__ import annotations

import httpx

from .base import BaseNotifier
from ..links import build_registry_url
from ..models import UpdateResult, comparison_summary, deployed_display_result, remote_display


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
            title = f"{result.container_info.name}: {result.event or 'check'}"
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
                    f"- {result.container_info.name} [{result.event or 'check'}]: "
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
                    "Title": title,
                    "Priority": "default",
                    "Tags": "whale,arrow_up",
                },
            )
            response.raise_for_status()
