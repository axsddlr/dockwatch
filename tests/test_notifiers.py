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
                event="update",
                deployed_tag="1.0.0",
                remote_tag="1.1.0",
                comparison_basis="version",
                comparison_reason="remote version 1.1.0 is newer than deployed 1.0.0",
            )
        ]

    async def test_build_notifiers_respects_config(self) -> None:
        config = DockwatchConfig(
            webhook_url="https://example.test/webhook",
            discord_webhook="https://discord.test/hook",
            ntfy_url="https://ntfy.test/topic",
        )
        notifiers = build_notifiers(config)
        self.assertEqual(len(notifiers), 3)

    async def test_webhook_payload_includes_registry_url(self) -> None:
        config = DockwatchConfig(webhook_url="https://example.test/webhook")
        captured: list[dict] = []

        class CaptureResponse:
            def raise_for_status(self) -> None:
                return None

        class CaptureClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url: str, json=None, **kwargs):  # noqa: ANN001
                captured.append({"url": url, "json": json, "kwargs": kwargs})
                return CaptureResponse()

        with patch("dockwatch.notifiers.webhook.httpx.AsyncClient", return_value=CaptureClient()):
            await send_configured_notifications(self._sample_results(), config, apply_filters=False)

        self.assertEqual(len(captured), 1)
        result_entry = captured[0]["json"]["results"][0]
        self.assertEqual(result_entry["registry_url"], "https://hub.docker.com/_/nginx")
        self.assertEqual(result_entry["deployed_display"], "1.0.0")
        self.assertEqual(result_entry["remote_display"], "1.1.0")
        self.assertEqual(result_entry["comparison_reason"], "remote version 1.1.0 is newer than deployed 1.0.0")

    async def test_notify_only_filters_results(self) -> None:
        sent: list[list[UpdateResult]] = []
        config = DockwatchConfig(
            webhook_url="https://example.test/webhook",
            notify_only=["web"],
        )
        results = self._sample_results() + [
            UpdateResult(
                container_info=ContainerInfo(
                    name="db",
                    container_id="2",
                    image_ref="postgres:15",
                    registry=RegistryType.DOCKERHUB,
                    namespace="library",
                    image_name="postgres",
                    current_tag="15",
                ),
                latest_tag="16",
                is_outdated=True,
                event="update",
            )
        ]

        async def capture_send(self_inner, r):  # noqa: ANN001
            sent.append(r)

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", capture_send):
            await send_configured_notifications(results, config)

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0].container_info.name, "web")

    async def test_notify_only_empty_sends_all(self) -> None:
        sent: list[list[UpdateResult]] = []

        async def capture_send(self_inner, r):  # noqa: ANN001
            sent.append(r)

        config = DockwatchConfig(webhook_url="https://example.test/webhook")
        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", capture_send):
            await send_configured_notifications(self._sample_results(), config)

        self.assertEqual(len(sent[0]), 1)

    async def test_notify_on_filters_new_events_by_default(self) -> None:
        sent: list[list[UpdateResult]] = []
        config = DockwatchConfig(webhook_url="https://example.test/webhook")
        results = [
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
                event="new",
            ),
            UpdateResult(
                container_info=ContainerInfo(
                    name="db",
                    container_id="2",
                    image_ref="postgres:15",
                    registry=RegistryType.DOCKERHUB,
                    namespace="library",
                    image_name="postgres",
                    current_tag="15",
                ),
                latest_tag="16",
                is_outdated=True,
                event="update",
            ),
        ]

        async def capture_send(self_inner, r):  # noqa: ANN001
            sent.append(r)

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", capture_send):
            await send_configured_notifications(results, config)

        self.assertEqual(len(sent), 1)
        self.assertEqual([item.event for item in sent[0]], ["update"])

    async def test_first_check_notify_allows_new_events_when_enabled(self) -> None:
        sent: list[list[UpdateResult]] = []
        config = DockwatchConfig(
            webhook_url="https://example.test/webhook",
            notify_on=["new", "update"],
            first_check_notify=True,
        )
        results = [
            UpdateResult(
                container_info=ContainerInfo(
                    name="web",
                    container_id="1",
                    image_ref="nginx:1.0.0",
                    registry=RegistryType.DOCKERHUB,
                    namespace="library",
                    image_name="nginx",
                    current_tag="1.0.0",
                    notify_enabled=True,
                ),
                latest_tag="1.1.0",
                is_outdated=True,
                event="new",
            )
        ]

        async def capture_send(self_inner, r):  # noqa: ANN001
            sent.append(r)

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", capture_send):
            await send_configured_notifications(results, config)

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0].event, "new")

    async def test_notify_label_false_suppresses_notification(self) -> None:
        config = DockwatchConfig(webhook_url="https://example.test/webhook")
        results = [
            UpdateResult(
                container_info=ContainerInfo(
                    name="web",
                    container_id="1",
                    image_ref="nginx:1.0.0",
                    registry=RegistryType.DOCKERHUB,
                    namespace="library",
                    image_name="nginx",
                    current_tag="1.0.0",
                    notify_enabled=False,
                ),
                latest_tag="1.1.0",
                is_outdated=True,
                event="update",
            )
        ]

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send") as send_mock:
            errors = await send_configured_notifications(results, config)

        self.assertEqual(errors, [])
        send_mock.assert_not_called()

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

    async def test_send_configured_notifications_retries_transient_failures(self) -> None:
        config = DockwatchConfig(webhook_url="https://example.test/webhook")
        calls = {"count": 0}

        async def flaky_send(self, _results):  # noqa: ANN001
            calls["count"] += 1
            if calls["count"] < 3:
                raise RuntimeError("temporary")

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", flaky_send):
            errors = await send_configured_notifications(self._sample_results(), config, apply_filters=False)

        self.assertEqual(errors, [])
        self.assertEqual(calls["count"], 3)


if __name__ == "__main__":
    unittest.main()
