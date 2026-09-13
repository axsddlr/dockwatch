from __future__ import annotations

import asyncio
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, call, patch

from docker.errors import DockerException

from dockwatch.config import AgentConfig, DockwatchConfig
from dockwatch.db import ManifestStore
from dockwatch.docker_client import ImageInfo
from dockwatch.prune import (
    PRUNE_USERNAME,
    PruneScheduler,
    execute_prune,
    plan_prune,
    prune_all,
)


def _image(
    image_id: str,
    repo_tags: list[str],
    *,
    created: int,
    size_bytes: int,
) -> ImageInfo:
    return ImageInfo(
        image_id=image_id,
        repo_tags=repo_tags,
        created=created,
        size_bytes=size_bytes,
    )


class PlanPruneTests(unittest.TestCase):
    def test_retains_newest_keep_recent_per_repository(self) -> None:
        images = [
            _image("a1", ["repo:1"], created=100, size_bytes=10),
            _image("a2", ["repo:2"], created=300, size_bytes=30),
            _image("a3", ["repo:3"], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, set(), mode="unused", keep_recent=1)

        self.assertEqual([c.image_id for c in preview.retained], ["a2"])
        self.assertEqual({c.image_id for c in preview.candidates}, {"a1", "a3"})
        self.assertEqual(preview.estimated_bytes, 30)
        self.assertEqual(preview.mode, "unused")
        self.assertEqual(preview.keep_recent, 1)

    def test_retention_is_per_repository(self) -> None:
        images = [
            _image("repoA-old", ["repoA:1"], created=100, size_bytes=10),
            _image("repoA-new", ["repoA:2"], created=200, size_bytes=20),
            _image("repoB-old", ["repoB:1"], created=100, size_bytes=10),
            _image("repoB-new", ["repoB:2"], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, set(), mode="unused", keep_recent=1)

        self.assertEqual({c.image_id for c in preview.retained}, {"repoA-new", "repoB-new"})
        self.assertEqual({c.image_id for c in preview.candidates}, {"repoA-old", "repoB-old"})

    def test_multi_repo_image_is_retained_in_every_repository(self) -> None:
        images = [
            _image("X", ["app:1", "other:1"], created=100, size_bytes=10),
            _image("Y", ["app:2"], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, set(), mode="unused", keep_recent=1)

        self.assertEqual(preview.candidates, [])
        self.assertEqual({c.image_id for c in preview.retained}, {"X", "Y"})

    def test_multi_repo_image_old_in_one_repo_but_newest_in_another_not_deleted(self) -> None:
        images = [
            _image("X", ["app:1", "other:1"], created=100, size_bytes=10),
            _image("Y", ["app:2"], created=200, size_bytes=20),
            _image("Z", ["app:3"], created=300, size_bytes=30),
        ]

        preview = plan_prune(images, set(), mode="unused", keep_recent=1)

        self.assertNotIn("X", {c.image_id for c in preview.candidates})
        self.assertEqual({c.image_id for c in preview.candidates}, {"Y"})
        self.assertEqual({c.image_id for c in preview.retained}, {"X", "Z"})

    def test_result_is_independent_of_repo_tags_ordering(self) -> None:
        images_forward = [
            _image("X", ["app:1", "other:1"], created=100, size_bytes=10),
            _image("Y", ["app:2"], created=200, size_bytes=20),
        ]
        images_reversed = [
            _image("X", ["other:1", "app:1"], created=100, size_bytes=10),
            _image("Y", ["app:2"], created=200, size_bytes=20),
        ]

        forward = plan_prune(images_forward, set(), mode="unused", keep_recent=1)
        reversed_preview = plan_prune(images_reversed, set(), mode="unused", keep_recent=1)

        self.assertEqual(
            {c.image_id for c in forward.candidates},
            {c.image_id for c in reversed_preview.candidates},
        )
        self.assertEqual(
            {c.image_id for c in forward.retained},
            {c.image_id for c in reversed_preview.retained},
        )
        self.assertEqual(forward.estimated_bytes, reversed_preview.estimated_bytes)

    def test_multi_tag_image_in_use_is_never_candidate(self) -> None:
        images = [
            _image("X", ["app:1", "other:1"], created=100, size_bytes=10),
            _image("Y", ["app:2"], created=200, size_bytes=20),
            _image("W", ["other:2"], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, {"X"}, mode="unused", keep_recent=1)

        self.assertNotIn("X", {c.image_id for c in preview.candidates})
        self.assertNotIn("X", {c.image_id for c in preview.retained})
        self.assertEqual({c.image_id for c in preview.retained}, {"Y", "W"})

    def test_dangling_mode_multi_tag_image_is_not_a_candidate(self) -> None:
        images = [
            _image("X", ["app:1", "other:1"], created=100, size_bytes=10),
            _image("D", [], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, set(), mode="dangling", keep_recent=1)

        self.assertEqual({c.image_id for c in preview.candidates}, {"D"})
        self.assertEqual(preview.retained, [])

    def test_in_use_images_never_candidates_in_unused_mode(self) -> None:
        images = [
            _image("used", ["repo:1"], created=100, size_bytes=10),
            _image("free", ["repo:2"], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, {"used"}, mode="unused", keep_recent=0)

        self.assertEqual({c.image_id for c in preview.candidates}, {"free"})

    def test_in_use_dangling_image_never_candidate(self) -> None:
        images = [
            _image("used-dangling", [], created=100, size_bytes=10),
            _image("free-dangling", [], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, {"used-dangling"}, mode="dangling", keep_recent=0)

        self.assertEqual({c.image_id for c in preview.candidates}, {"free-dangling"})

    def test_dangling_mode_ignores_tagged_images(self) -> None:
        images = [
            _image("tagged", ["repo:1"], created=100, size_bytes=10),
            _image("dangling", [], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, set(), mode="dangling", keep_recent=0)

        self.assertEqual({c.image_id for c in preview.candidates}, {"dangling"})
        self.assertEqual(preview.retained, [])

    def test_unused_mode_includes_tagged_images(self) -> None:
        images = [
            _image("tagged", ["repo:1"], created=100, size_bytes=10),
            _image("dangling", [], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, set(), mode="unused", keep_recent=0)

        self.assertEqual({c.image_id for c in preview.candidates}, {"tagged", "dangling"})

    def test_keep_recent_zero_disables_the_guard(self) -> None:
        images = [
            _image("a", ["repo:1"], created=100, size_bytes=10),
            _image("b", ["repo:2"], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, set(), mode="unused", keep_recent=0)

        self.assertEqual(preview.retained, [])
        self.assertEqual({c.image_id for c in preview.candidates}, {"a", "b"})

    def test_dangling_group_is_not_retained_by_keep_n(self) -> None:
        images = [
            _image("d1", [], created=100, size_bytes=10),
            _image("d2", [], created=200, size_bytes=20),
        ]

        preview = plan_prune(images, set(), mode="unused", keep_recent=5)

        self.assertEqual(preview.retained, [])
        self.assertEqual({c.image_id for c in preview.candidates}, {"d1", "d2"})

    def test_empty_image_list_degrades_to_empty_preview(self) -> None:
        preview = plan_prune([], set(), mode="unused", keep_recent=3)

        self.assertEqual(preview.candidates, [])
        self.assertEqual(preview.retained, [])
        self.assertEqual(preview.estimated_bytes, 0)

    def test_all_in_use_degrades_to_empty_preview(self) -> None:
        images = [_image("used", ["repo:1"], created=100, size_bytes=10)]

        preview = plan_prune(images, {"used"}, mode="unused", keep_recent=3)

        self.assertEqual(preview.candidates, [])
        self.assertEqual(preview.retained, [])

    def test_reason_is_nonempty_for_every_candidate(self) -> None:
        images = [
            _image("a", ["repo:1"], created=100, size_bytes=10),
            _image("b", ["repo:2"], created=200, size_bytes=20),
            _image("c", ["repo:3"], created=300, size_bytes=30),
            _image("d", [], created=400, size_bytes=40),
        ]

        preview = plan_prune(images, set(), mode="unused", keep_recent=1)

        self.assertTrue(preview.candidates)
        for candidate in preview.candidates:
            self.assertTrue(candidate.reason)

    def test_repo_field_strips_tag_and_uses_none_for_dangling(self) -> None:
        tagged = _image("t", ["ghcr.io/org/name:1.0"], created=100, size_bytes=10)
        dangling = _image("d", [], created=200, size_bytes=20)

        preview = plan_prune([tagged, dangling], set(), mode="unused", keep_recent=0)

        repos = {c.image_id: c.repo for c in preview.candidates}
        self.assertEqual(repos["t"], "ghcr.io/org/name")
        self.assertEqual(repos["d"], "<none>")


class ExecutePruneTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_removes_only_candidates_without_force(self) -> None:
        config = DockwatchConfig()
        config.prune.notify = False
        images = [
            _image("new", ["repo:2"], created=200, size_bytes=20),
            _image("old", ["repo:1"], created=100, size_bytes=10),
        ]
        preview = plan_prune(images, set(), mode="unused", keep_recent=1)

        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            with patch("dockwatch.docker_client.remove_image") as mock_remove:
                result = await execute_prune(preview, config=config, store=store, source="local")

            self.assertEqual(result.removed, ["old"])
            self.assertEqual(result.failed, [])
            self.assertEqual(result.reclaimed_bytes, 10)
            self.assertEqual(mock_remove.call_args_list, [call("old")])
            self.assertEqual(mock_remove.call_args_list[0].kwargs, {})
            history = store.list_update_history("(images)")
            self.assertEqual([row.old_digest for row in history], ["old"])
            self.assertEqual(history[0].action, "prune_images")
            self.assertEqual(history[0].status, "success")
            self.assertEqual(history[0].username, PRUNE_USERNAME)
            self.assertEqual(history[0].container_name, "(images)")
            self.assertEqual(history[0].new_tag, "repo:1")

    async def test_continues_after_one_removal_fails(self) -> None:
        config = DockwatchConfig()
        config.prune.notify = False
        images = [
            _image("a", ["repoA:1"], created=100, size_bytes=10),
            _image("b", ["repoB:1"], created=200, size_bytes=20),
            _image("c", ["repoC:1"], created=300, size_bytes=30),
        ]
        preview = plan_prune(images, set(), mode="unused", keep_recent=0)

        def fail_a(image_id: str) -> None:
            if image_id == "a":
                raise DockerException("image is in use")

        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            with patch("dockwatch.docker_client.remove_image", side_effect=fail_a) as mock_remove:
                result = await execute_prune(preview, config=config, store=store, source="local")

            self.assertEqual(mock_remove.call_args_list, [call("a"), call("b"), call("c")])
            self.assertEqual(result.removed, ["b", "c"])
            self.assertEqual([failed_id for failed_id, _ in result.failed], ["a"])
            self.assertIn("image is in use", result.failed[0][1])
            self.assertEqual(result.reclaimed_bytes, 50)
            history = store.list_update_history("(images)")
            statuses = {row.old_digest: row.status for row in history}
            self.assertEqual(statuses, {"a": "failed", "b": "success", "c": "success"})
            errors = {row.old_digest: row.error for row in history}
            self.assertIsNone(errors["b"])
            self.assertIn("image is in use", errors["a"])

    async def test_non_docker_exception_is_recorded_and_remaining_attempted(self) -> None:
        config = DockwatchConfig()
        config.prune.notify = False
        images = [
            _image("a", ["repoA:1"], created=100, size_bytes=10),
            _image("b", ["repoB:1"], created=200, size_bytes=20),
            _image("c", ["repoC:1"], created=300, size_bytes=30),
        ]
        preview = plan_prune(images, set(), mode="unused", keep_recent=0)

        def fail_a(image_id: str) -> None:
            if image_id == "a":
                raise RuntimeError("connection dropped")

        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            with patch("dockwatch.docker_client.remove_image", side_effect=fail_a) as mock_remove:
                result = await execute_prune(preview, config=config, store=store, source="local")

            self.assertEqual(mock_remove.call_args_list, [call("a"), call("b"), call("c")])
            self.assertEqual(result.removed, ["b", "c"])
            self.assertEqual([failed_id for failed_id, _ in result.failed], ["a"])
            self.assertIn("connection dropped", result.failed[0][1])

    async def test_notification_sent_once_when_notify_on(self) -> None:
        config = DockwatchConfig()
        config.prune.notify = True
        preview = plan_prune(
            [_image("a", ["repoA:1"], created=100, size_bytes=10)],
            set(),
            mode="unused",
            keep_recent=0,
        )

        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            with patch("dockwatch.docker_client.remove_image"), patch(
                "dockwatch.prune.send_configured_events", new=AsyncMock(return_value=[])
            ) as mock_send:
                await execute_prune(preview, config=config, store=store, source="local")

        self.assertEqual(mock_send.await_count, 1)
        events = mock_send.call_args[0][0]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "prune")
        self.assertEqual(events[0].severity, "info")

    async def test_notification_not_sent_when_notify_off(self) -> None:
        config = DockwatchConfig()  # prune.notify defaults False
        preview = plan_prune(
            [_image("a", ["repoA:1"], created=100, size_bytes=10)],
            set(),
            mode="unused",
            keep_recent=0,
        )

        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            with patch("dockwatch.docker_client.remove_image"), patch(
                "dockwatch.prune.send_configured_events", new=AsyncMock(return_value=[])
            ) as mock_send:
                await execute_prune(preview, config=config, store=store, source="local")

        mock_send.assert_not_called()

    async def test_notification_is_warning_when_some_removals_failed(self) -> None:
        config = DockwatchConfig()
        config.prune.notify = True
        preview = plan_prune(
            [_image("a", ["repoA:1"], created=100, size_bytes=10)],
            set(),
            mode="unused",
            keep_recent=0,
        )

        def fail(image_id: str) -> None:
            raise DockerException("nope")

        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            with patch("dockwatch.docker_client.remove_image", side_effect=fail), patch(
                "dockwatch.prune.send_configured_events", new=AsyncMock(return_value=[])
            ) as mock_send:
                await execute_prune(preview, config=config, store=store, source="local")

        events = mock_send.call_args[0][0]
        self.assertEqual(events[0].severity, "warning")

    async def test_prune_all_reaches_agent_hosts_with_resolved_params(self) -> None:
        config = DockwatchConfig()
        config.prune.notify = False
        config.agents = [AgentConfig(name="media-pc", url="http://agent", token="tok", enabled=True)]

        fake_client = MagicMock()
        fake_client.prune_images = AsyncMock(return_value={"removed": ["x"], "failed": [], "reclaimed_bytes": 100})
        with patch("dockwatch.docker_client.list_images", return_value=[]), patch(
            "dockwatch.docker_client.in_use_image_ids", return_value=set()
        ), patch("dockwatch.prune.AgentClient", return_value=fake_client):
            result = await prune_all(config, mode="dangling", keep_recent=5, store=None)

        self.assertEqual(result.removed, ["x"])
        self.assertEqual(result.failed, [])
        self.assertEqual(result.reclaimed_bytes, 100)
        fake_client.prune_images.assert_awaited_once_with(mode="dangling", keep_recent=5)

    async def test_prune_all_notification_reflects_combined_counts(self) -> None:
        config = DockwatchConfig()
        config.prune.notify = True
        config.agents = [AgentConfig(name="media-pc", url="http://agent", token="tok", enabled=True)]

        fake_client = MagicMock()
        fake_client.prune_images = AsyncMock(return_value={"removed": ["agent-img"], "failed": [], "reclaimed_bytes": 100})

        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            with patch(
                "dockwatch.docker_client.list_images",
                return_value=[_image("local-img", ["repo:1"], created=100, size_bytes=10)],
            ), patch("dockwatch.docker_client.in_use_image_ids", return_value=set()), patch(
                "dockwatch.docker_client.remove_image"
            ), patch("dockwatch.prune.AgentClient", return_value=fake_client), patch(
                "dockwatch.prune.send_configured_events", new=AsyncMock(return_value=[])
            ) as mock_send:
                result = await prune_all(config, mode="unused", keep_recent=0, store=store)

        self.assertEqual(sorted(result.removed), ["agent-img", "local-img"])
        self.assertEqual(mock_send.await_count, 1)
        events = mock_send.call_args[0][0]
        self.assertEqual(events[0].kind, "prune")
        self.assertEqual(events[0].fields["removed"], "2")
        self.assertIn("Removed 2 image(s)", events[0].message)

    async def test_portainer_source_reports_unsupported(self) -> None:
        config = DockwatchConfig()
        config.prune.notify = False
        preview = plan_prune(
            [_image("a", ["repoA:1"], created=100, size_bytes=10)],
            set(),
            mode="unused",
            keep_recent=0,
        )

        with patch("dockwatch.docker_client.remove_image") as mock_remove:
            result = await execute_prune(preview, config=config, store=None, source="portainer")

        self.assertEqual(result.removed, [])
        self.assertEqual([failed_id for failed_id, _ in result.failed], ["a"])
        self.assertIn("not supported", result.failed[0][1])
        mock_remove.assert_not_called()


class PruneSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def _config(self, *, enabled: bool = False, mode: str = "unused", keep_recent: int = 0) -> DockwatchConfig:
        config = DockwatchConfig()
        config.prune.enabled = enabled
        config.prune.mode = mode
        config.prune.keep_recent_per_repository = keep_recent
        return config

    async def test_run_once_inert_when_disabled(self) -> None:
        config = self._config(enabled=False)
        emitted: list[str] = []
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            scheduler = PruneScheduler(config=config, store=store, emit=emitted.append)
            with patch("dockwatch.prune.docker_client.list_images") as mock_list, patch(
                "dockwatch.prune.docker_client.in_use_image_ids"
            ) as mock_in_use, patch("dockwatch.prune.docker_client.remove_image") as mock_remove:
                result = await scheduler.run_once()

            self.assertTrue(result)
            mock_list.assert_not_called()
            mock_in_use.assert_not_called()
            mock_remove.assert_not_called()
            self.assertEqual(store.list_update_history("(images)"), [])
            self.assertTrue(any("disabled" in message for message in emitted))

    async def test_run_once_force_works_when_disabled(self) -> None:
        config = self._config(enabled=False)
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            scheduler = PruneScheduler(config=config, store=store)
            with patch(
                "dockwatch.prune.docker_client.list_images",
                return_value=[_image("a", ["repoA:1"], created=100, size_bytes=10)],
            ), patch("dockwatch.prune.docker_client.in_use_image_ids", return_value=set()), patch(
                "dockwatch.prune.docker_client.remove_image"
            ) as mock_remove:
                result = await scheduler.run_once(force=True)

            self.assertTrue(result)
            mock_remove.assert_called_once_with("a")
            self.assertEqual(store.list_update_history("(images)")[0].action, "prune_images")

    async def test_run_once_skipped_when_in_flight(self) -> None:
        config = self._config(enabled=True)
        emitted: list[str] = []
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            scheduler = PruneScheduler(config=config, store=store, emit=emitted.append)

            def slow_list() -> list[ImageInfo]:
                time.sleep(0.05)
                return []

            with patch("dockwatch.prune.docker_client.list_images", side_effect=slow_list), patch(
                "dockwatch.prune.docker_client.in_use_image_ids", return_value=set()
            ):
                first = asyncio.create_task(scheduler.run_once())
                await asyncio.sleep(0)
                second = await scheduler.run_once()
                first_result = await first

        self.assertTrue(first_result)
        self.assertFalse(second)
        self.assertTrue(any("still in progress" in message for message in emitted))

    async def test_no_broadcast_callback_no_crash(self) -> None:
        config = self._config(enabled=True)
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            scheduler = PruneScheduler(config=config, store=store)  # broadcast=None
            with patch(
                "dockwatch.prune.docker_client.list_images",
                return_value=[_image("a", ["repoA:1"], created=100, size_bytes=10)],
            ), patch("dockwatch.prune.docker_client.in_use_image_ids", return_value=set()), patch(
                "dockwatch.prune.docker_client.remove_image"
            ):
                result = await scheduler.run_once()

        self.assertTrue(result)

    async def test_run_once_broadcasts_started_and_complete(self) -> None:
        config = self._config(enabled=True)
        broadcast = AsyncMock()
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            scheduler = PruneScheduler(config=config, store=store, broadcast=broadcast)
            with patch(
                "dockwatch.prune.docker_client.list_images",
                return_value=[_image("a", ["repoA:1"], created=100, size_bytes=10)],
            ), patch("dockwatch.prune.docker_client.in_use_image_ids", return_value=set()), patch(
                "dockwatch.prune.docker_client.remove_image"
            ):
                await scheduler.run_once()

        names = [call.args[0] for call in broadcast.await_args_list]
        self.assertEqual(names, ["prune_started", "prune_complete"])

    async def test_listing_failure_broadcasts_balanced_started_and_complete(self) -> None:
        config = self._config(enabled=True)
        broadcast = AsyncMock()
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            scheduler = PruneScheduler(config=config, store=store, broadcast=broadcast)
            with patch(
                "dockwatch.prune.docker_client.list_images",
                side_effect=RuntimeError("daemon connection dropped"),
            ), patch("dockwatch.prune.docker_client.in_use_image_ids", return_value=set()):
                result = await scheduler.run_once()

        self.assertTrue(result)
        names = [call.args[0] for call in broadcast.await_args_list]
        self.assertEqual(names, ["prune_started", "prune_complete"])
        self.assertIn("daemon connection dropped", broadcast.await_args_list[1].args[1]["error"])


class PruneSchedulerNextDelayTests(unittest.TestCase):
    def test_next_delay_uses_interval_hours_plus_jitter(self) -> None:
        config = DockwatchConfig()
        config.prune.interval_hours = 2
        config.schedule_jitter_seconds = 0
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            scheduler = PruneScheduler(config=config, store=store)

        self.assertEqual(scheduler.next_delay(), 7200.0)


if __name__ == "__main__":
    unittest.main()
