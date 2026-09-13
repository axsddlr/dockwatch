from __future__ import annotations

import unittest
from typing import Self
from unittest.mock import patch

from dockwatch.config import DockwatchConfig, _parse_notify_events
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.notifiers import (
    build_notifiers,
    send_configured_events,
    send_configured_notifications,
)
from dockwatch.notifiers.base import BaseNotifier, NotificationEvent, render_event_text
from dockwatch.notifiers.discord import DiscordNotifier
from dockwatch.notifiers.ntfy import NtfyNotifier
from dockwatch.notifiers.webhook import WebhookNotifier


class _CaptureResponse:
    def raise_for_status(self) -> None:
        return None


class _CaptureClient:
    """Records every POST so tests can assert on the real wire payload."""

    def __init__(self, captured: list[dict]) -> None:
        self._captured = captured

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def post(
        self,
        url: str,
        json=None,
        content=None,
        headers=None,
        **kwargs,
    ) -> _CaptureResponse:
        self._captured.append(
            {"url": url, "json": json, "content": content, "headers": headers, "kwargs": kwargs}
        )
        return _CaptureResponse()


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

            async def post(self, url: str, json=None, **kwargs):
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

    async def test_ntfy_uses_publish_headers(self) -> None:
        config = DockwatchConfig(ntfy_url="https://ntfy.test/topic")
        captured: list[dict] = []

        class CaptureResponse:
            def raise_for_status(self) -> None:
                return None

        class CaptureClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url: str, content=None, headers=None, **kwargs):
                captured.append({"url": url, "content": content, "headers": headers, "kwargs": kwargs})
                return CaptureResponse()

        with patch("dockwatch.notifiers.ntfy.httpx.AsyncClient", return_value=CaptureClient()):
            await send_configured_notifications(self._sample_results(), config, apply_filters=False)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["url"], "https://ntfy.test/topic")
        self.assertEqual(captured[0]["headers"]["X-Title"], "web: update")
        self.assertEqual(captured[0]["headers"]["X-Priority"], "3")
        self.assertEqual(captured[0]["headers"]["X-Tags"], "whale,arrow_up")
        self.assertEqual(captured[0]["headers"]["Content-Type"], "text/plain; charset=utf-8")
        self.assertIsInstance(captured[0]["content"], bytes)

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

        async def capture_send(self_inner, r):
            sent.append(r)

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", capture_send):
            await send_configured_notifications(results, config)

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0].container_info.name, "web")

    async def test_notify_only_empty_sends_all(self) -> None:
        sent: list[list[UpdateResult]] = []

        async def capture_send(self_inner, r):
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

        async def capture_send(self_inner, r):
            sent.append(r)

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", capture_send):
            await send_configured_notifications(results, config)

        self.assertEqual(len(sent), 1)
        self.assertEqual([item.event for item in sent[0]], ["update"])

    async def test_digest_drift_bypasses_event_filter(self) -> None:
        sent: list[list[UpdateResult]] = []
        config = DockwatchConfig(webhook_url="https://example.test/webhook")
        results = [
            UpdateResult(
                container_info=ContainerInfo(
                    name="gluetun",
                    container_id="1",
                    image_ref="qmcgaw/gluetun:latest",
                    registry=RegistryType.DOCKERHUB,
                    namespace="qmcgaw",
                    image_name="gluetun",
                    current_tag="latest",
                ),
                is_outdated=True,
                event=None,
                comparison_basis="digest",
                comparison_reason="digest changed behind same tag",
                digest_drift=True,
            ),
        ]

        async def capture_send(self_inner, r):
            sent.append(r)

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", capture_send):
            await send_configured_notifications(results, config)

        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0][0].digest_drift)

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

        async def capture_send(self_inner, r):
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

        async def fail_send(self, _results):
            raise RuntimeError("failed")

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", fail_send), patch(
            "dockwatch.notifiers.discord.DiscordNotifier.send", fail_send
        ):
            errors = await send_configured_notifications(self._sample_results(), config)

        self.assertEqual(len(errors), 2)

    async def test_send_configured_notifications_retries_transient_failures(self) -> None:
        config = DockwatchConfig(webhook_url="https://example.test/webhook")
        calls = {"count": 0}

        async def flaky_send(self, _results):
            calls["count"] += 1
            if calls["count"] < 3:
                raise RuntimeError("temporary")

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send", flaky_send):
            errors = await send_configured_notifications(self._sample_results(), config, apply_filters=False)

        self.assertEqual(errors, [])
        self.assertEqual(calls["count"], 3)


    def _sample_event(self, *, severity: str = "warning", kind: str = "health") -> NotificationEvent:
        return NotificationEvent(
            kind=kind,
            title="web restarted",
            message="container web restarted after failing health check",
            fields={"container": "web", "restarts": "2"},
            severity=severity,
        )

    async def test_webhook_event_payload(self) -> None:
        captured: list[dict] = []
        event = self._sample_event(severity="error")

        with patch("dockwatch.notifiers.webhook.httpx.AsyncClient", return_value=_CaptureClient(captured)):
            await WebhookNotifier("https://example.test/webhook").send_event(event)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["url"], "https://example.test/webhook")
        self.assertEqual(
            captured[0]["json"],
            {
                "event": {
                    "kind": "health",
                    "title": "web restarted",
                    "message": "container web restarted after failing health check",
                    "severity": "error",
                    "fields": {"container": "web", "restarts": "2"},
                }
            },
        )

    async def test_ntfy_event_body_headers_and_tags(self) -> None:
        captured: list[dict] = []
        event = self._sample_event(severity="error", kind="prune")

        with patch("dockwatch.notifiers.ntfy.httpx.AsyncClient", return_value=_CaptureClient(captured)):
            await NtfyNotifier("https://ntfy.test/topic").send_event(event)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["url"], "https://ntfy.test/topic")
        self.assertEqual(
            captured[0]["headers"],
            {
                "X-Title": "web restarted",
                "X-Priority": "5",
                "X-Tags": "whale,broom",
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        self.assertEqual(
            captured[0]["content"],
            (
                b"web restarted\n\n"
                b"container web restarted after failing health check\n"
                b"container: web\n"
                b"restarts: 2"
            ),
        )

    async def test_ntfy_event_priority_maps_from_severity(self) -> None:
        expected = {"info": "3", "warning": "4", "error": "5"}
        for severity, priority in expected.items():
            with self.subTest(severity=severity):
                captured: list[dict] = []
                with patch(
                    "dockwatch.notifiers.ntfy.httpx.AsyncClient", return_value=_CaptureClient(captured)
                ):
                    await NtfyNotifier("https://ntfy.test/topic").send_event(
                        self._sample_event(severity=severity)
                    )
                self.assertEqual(captured[0]["headers"]["X-Priority"], priority)

    async def test_ntfy_event_tags_fall_back_for_unknown_kind(self) -> None:
        captured: list[dict] = []

        with patch("dockwatch.notifiers.ntfy.httpx.AsyncClient", return_value=_CaptureClient(captured)):
            await NtfyNotifier("https://ntfy.test/topic").send_event(self._sample_event(kind="mystery"))

        self.assertEqual(captured[0]["headers"]["X-Tags"], "whale")

    async def test_discord_event_posts_single_embed(self) -> None:
        captured: list[dict] = []
        event = self._sample_event(severity="warning")

        with patch("dockwatch.notifiers.discord.httpx.AsyncClient", return_value=_CaptureClient(captured)):
            await DiscordNotifier("https://discord.test/hook").send_event(event)

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["url"], "https://discord.test/hook")
        payload = captured[0]["json"]
        self.assertEqual(sorted(payload), ["embeds"])
        self.assertEqual(len(payload["embeds"]), 1)
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "web restarted")
        self.assertEqual(embed["description"], "container web restarted after failing health check")
        self.assertEqual(embed["color"], 16753920)
        self.assertEqual(
            embed["fields"],
            [
                {"name": "container", "value": "web", "inline": False},
                {"name": "restarts", "value": "2", "inline": False},
            ],
        )

    async def test_discord_event_color_maps_from_severity(self) -> None:
        expected = {"info": 3447003, "warning": 16753920, "error": 15158332}
        for severity, color in expected.items():
            with self.subTest(severity=severity):
                captured: list[dict] = []
                with patch(
                    "dockwatch.notifiers.discord.httpx.AsyncClient", return_value=_CaptureClient(captured)
                ):
                    await DiscordNotifier("https://discord.test/hook").send_event(
                        self._sample_event(severity=severity)
                    )
                self.assertEqual(captured[0]["json"]["embeds"][0]["color"], color)

    async def test_default_send_event_renders_and_does_not_raise(self) -> None:
        class MinimalNotifier(BaseNotifier):
            async def send(self, results: list[UpdateResult]) -> None:
                return None

        event = self._sample_event()

        with self.assertLogs("dockwatch.notifiers.base", level="INFO") as logs:
            await MinimalNotifier().send_event(event)

        self.assertIn(render_event_text(event), "\n".join(logs.output))

    async def test_render_event_text_lays_out_title_message_and_fields(self) -> None:
        self.assertEqual(
            render_event_text(self._sample_event()),
            (
                "web restarted\n\n"
                "container web restarted after failing health check\n"
                "container: web\n"
                "restarts: 2"
            ),
        )

    async def test_send_configured_events_returns_empty_without_notifiers(self) -> None:
        self.assertEqual(await send_configured_events([self._sample_event()], DockwatchConfig()), [])

    async def test_send_configured_events_returns_empty_without_events(self) -> None:
        config = DockwatchConfig(webhook_url="https://example.test/webhook")

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send_event") as send_event_mock:
            errors = await send_configured_events([], config)

        self.assertEqual(errors, [])
        send_event_mock.assert_not_called()

    async def test_send_configured_events_aggregates_errors_and_delivers_to_others(self) -> None:
        config = DockwatchConfig(
            webhook_url="https://example.test/webhook",
            discord_webhook="https://discord.test/hook",
        )
        delivered: list[NotificationEvent] = []

        async def fail_send_event(self, _event):
            raise RuntimeError("failed")

        async def capture_send_event(self, event):
            delivered.append(event)

        with patch("dockwatch.notifiers.webhook.WebhookNotifier.send_event", fail_send_event), patch(
            "dockwatch.notifiers.discord.DiscordNotifier.send_event", capture_send_event
        ):
            errors = await send_configured_events([self._sample_event()], config)

        self.assertEqual(errors, ["webhook: failed"])
        self.assertEqual([event.kind for event in delivered], ["health"])

    async def test_parse_notify_events_accepts_generic_event_kinds(self) -> None:
        self.assertEqual(
            _parse_notify_events(["health", "prune", "hook"]),
            ["health", "prune", "hook"],
        )
        self.assertEqual(_parse_notify_events(["update", "bogus"]), ["update"])
        self.assertEqual(_parse_notify_events(["HEALTH"]), ["health"])
        self.assertEqual(_parse_notify_events(["nonsense"]), ["update"])

    async def test_update_notification_payload_is_unchanged(self) -> None:
        captured: list[dict] = []

        with patch("dockwatch.notifiers.webhook.httpx.AsyncClient", return_value=_CaptureClient(captured)):
            await WebhookNotifier("https://example.test/webhook").send(self._sample_results())

        payload = captured[0]["json"]
        self.assertEqual(sorted(payload), ["results", "summary"])
        self.assertEqual(payload["summary"], {"outdated": 1, "up_to_date": 0, "unknown": 0})
        entry = payload["results"][0]
        self.assertEqual(entry["name"], "web")
        self.assertEqual(entry["current"], "1.0.0")
        self.assertEqual(entry["latest"], "1.1.0")
        self.assertEqual(entry["deployed_display"], "1.0.0")
        self.assertEqual(entry["remote_display"], "1.1.0")
        self.assertEqual(entry["registry_url"], "https://hub.docker.com/_/nginx")
        self.assertEqual(entry["event"], "update")
        self.assertEqual(entry["status"], None)
        self.assertEqual(entry["comparison_basis"], "version")
        self.assertFalse(entry["digest_drift"])


if __name__ == "__main__":
    unittest.main()
