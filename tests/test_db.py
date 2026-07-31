from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dockwatch.db import ManifestStore
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.registry import record_digest_drift_events


def make_container(image_ref: str = "nginx:1.0.0", current_tag: str = "1.0.0") -> ContainerInfo:
    return ContainerInfo(
        name="web",
        container_id="1",
        image_ref=image_ref,
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name="nginx",
        current_tag=current_tag,
    )


class ManifestStoreTests(unittest.TestCase):
    def test_record_observation_classifies_new_then_update(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            container = make_container()

            first_event = store.record_observation(
                container,
                latest_tag="1.1.0",
                remote_digest="sha256:first",
            )
            second_event = store.record_observation(
                container,
                latest_tag="1.1.0",
                remote_digest="sha256:first",
            )
            third_event = store.record_observation(
                container,
                latest_tag="1.2.0",
                remote_digest="sha256:second",
            )

        self.assertEqual(first_event, "new")
        self.assertIsNone(second_event)
        self.assertEqual(third_event, "update")

    def test_record_observation_persists_latest_tag_without_digest_change(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            container = make_container()
            store.record_observation(container, latest_tag="1.1.0", remote_digest="sha256:same")

            event = store.record_observation(container, latest_tag="1.1.1", remote_digest="sha256:same")

        self.assertEqual(event, "update")

    def test_equivalent_image_refs_share_the_same_identity(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            first = make_container(image_ref="nginx:1.0.0")
            second = make_container(image_ref="docker.io/library/nginx:1.0.0")

            first_event = store.record_observation(first, latest_tag="1.1.0", remote_digest="sha256:first")
            second_event = store.record_observation(second, latest_tag="1.1.0", remote_digest="sha256:first")

        self.assertEqual(first_event, "new")
        self.assertIsNone(second_event)


class TestContainerFlags:
    def test_add_pin_returns_true_when_new(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        added = store.add_flag("nginx", "pinned")
        assert added is True
        assert store.get_pinned() == ["nginx"]

    def test_add_pin_returns_false_when_already_present(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        added_again = store.add_flag("nginx", "pinned")
        assert added_again is False
        assert store.get_pinned() == ["nginx"]

    def test_remove_flag_returns_true_when_present(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        removed = store.remove_flag("nginx", "pinned")
        assert removed is True
        assert store.get_pinned() == []

    def test_remove_flag_returns_false_when_absent(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        removed = store.remove_flag("nginx", "pinned")
        assert removed is False

    def test_pinned_and_ignored_are_independent(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        store.add_flag("redis", "ignored")
        assert store.get_pinned() == ["nginx"]
        assert store.get_ignored() == ["redis"]

    def test_set_pinned_bulk_replace(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "pinned")
        store.set_pinned(["redis", "postgres"])
        assert sorted(store.get_pinned()) == ["postgres", "redis"]

    def test_set_ignored_bulk_replace_empty_list_clears(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("nginx", "ignored")
        store.set_ignored([])
        assert store.get_ignored() == []

    def test_flags_persist_across_store_instances(self, tmp_path):
        path = tmp_path / "test.db"
        store1 = ManifestStore(path=path)
        store1.add_flag("nginx", "pinned")
        store2 = ManifestStore(path=path)
        assert store2.get_pinned() == ["nginx"]

    def test_get_pinned_preserves_insertion_order(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.add_flag("zebra", "pinned")
        store.add_flag("apple", "pinned")
        assert store.get_pinned() == ["zebra", "apple"]


class TestUpdateHistory:
    def test_record_and_list_update_event(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.record_update_event(
            container_name="web",
            action="update",
            source="local",
            status="success",
            old_tag="1.0.0",
            new_tag="1.1.0",
            user_id=1,
            username="admin",
        )
        records = store.list_update_history(container_name="web")
        assert len(records) == 1
        assert records[0].old_tag == "1.0.0"
        assert records[0].new_tag == "1.1.0"
        assert records[0].username == "admin"
        assert records[0].status == "success"

    def test_list_update_history_orders_newest_first(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.record_update_event(
            container_name="web", action="update", source="local",
            status="success", old_tag="1.0.0", new_tag="1.1.0",
        )
        store.record_update_event(
            container_name="web", action="update", source="local",
            status="success", old_tag="1.1.0", new_tag="1.2.0",
        )
        records = store.list_update_history(container_name="web")
        assert [r.new_tag for r in records] == ["1.2.0", "1.1.0"]

    def test_update_history_prunes_beyond_max_per_container(self, tmp_path):
        from dockwatch.db import UPDATE_HISTORY_MAX_PER_CONTAINER

        store = ManifestStore(path=tmp_path / "test.db")
        for i in range(UPDATE_HISTORY_MAX_PER_CONTAINER + 5):
            store.record_update_event(
                container_name="web", action="update", source="local",
                status="success", old_tag=str(i), new_tag=str(i + 1),
            )
        records = store.list_update_history(container_name="web", limit=100)
        assert len(records) == UPDATE_HISTORY_MAX_PER_CONTAINER

    def test_get_last_successful_update_ignores_failed(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.record_update_event(
            container_name="web", action="update", source="local",
            status="success", old_tag="1.0.0", new_tag="1.1.0",
        )
        store.record_update_event(
            container_name="web", action="update", source="local",
            status="failed", old_tag="1.1.0", new_tag="1.2.0", error="boom",
        )
        last = store.get_last_successful_update("web")
        assert last is not None
        assert last.new_tag == "1.1.0"

    def test_update_history_scoped_per_container(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        store.record_update_event(
            container_name="web", action="update", source="local",
            status="success", old_tag="1.0.0", new_tag="1.1.0",
        )
        store.record_update_event(
            container_name="db", action="update", source="local",
            status="success", old_tag="2.0.0", new_tag="2.1.0",
        )
        assert len(store.list_update_history(container_name="web")) == 1
        assert len(store.list_update_history(container_name="db")) == 1


class TestDigestDriftRecording:
    def test_record_digest_drift_events_writes_history_row(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        container = make_container(image_ref="qmcgaw/gluetun:latest", current_tag="latest")
        result = UpdateResult(
            container_info=container,
            is_outdated=True,
            digest_drift=True,
            deployed_digest="sha256:old",
            remote_digest="sha256:new",
        )

        record_digest_drift_events([result], store)

        history = store.list_update_history(container_name="web")
        assert len(history) == 1
        assert history[0].action == "digest_drift_detected"
        assert history[0].old_digest == "sha256:old"
        assert history[0].new_digest == "sha256:new"

    def test_record_digest_drift_events_skips_non_drift_results(self, tmp_path):
        store = ManifestStore(path=tmp_path / "test.db")
        container = make_container()
        result = UpdateResult(container_info=container, is_outdated=True, digest_drift=False)

        record_digest_drift_events([result], store)

        assert store.list_update_history(container_name="web") == []

    def test_record_digest_drift_events_noop_without_store(self) -> None:
        container = make_container()
        result = UpdateResult(container_info=container, is_outdated=True, digest_drift=True)
        record_digest_drift_events([result], None)


if __name__ == "__main__":
    unittest.main()
