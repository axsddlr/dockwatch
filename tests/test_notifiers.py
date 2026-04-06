from __future__ import annotations

import unittest
from unittest.mock import patch

from dockwatch.config import DockwatchConfig
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.notifiers import build_notifiers, send_configured_notifications


class NotifierTests(unittest.IsolatedAsyncioTestCase):
    def _sample_results(self) -> list[UpdateResult]:
        return [
            UpdateResult(
                container_info=ContainerInfo(
                    name="web",
                    container_id="1",
                    image_ref="nginx:1.0.0",
                    registry=RegistryType.DOCKERHUB,
                    namespace="library",
                    image_name="nginx",
                    current_tag="1.0.0",
                ),
                latest_tag="1.1.0",
                is_outdated=True,
            )
        ]

    async def test_build_notifiers_respects_config(self) -> None:
        config = DockwatchConfig(
            webhook_url="https://example.test/webhook",
            discord_webhook="https://discord.test/hook",
        )
        notifiers = build_notifiers(config)
        self.assertEqual(len(notifiers), 2)

    async def test_send_configured_notifications_collects_errors(self) -> None:
        config = DockwatchConfig(
            webhook_url="https://example.test/webhook",
            discord_webhook="https://discord.test/hook",
        )

        async def fail_send(self, _results):  # noqa: ANN001
            raise RuntimeError("failed")

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", fail_send), patch(
            "dockwatch.notifiers.discord.DiscordNotifier.send", fail_send
        ):
            errors = await send_configured_notifications(self._sample_results(), config)

        self.assertEqual(len(errors), 2)


if __name__ == "__main__":
    unittest.main()