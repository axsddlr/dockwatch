from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dockwatch.db import ManifestStore
from dockwatch.models import ContainerInfo, RegistryType


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


if __name__ == "__main__":
    unittest.main()
