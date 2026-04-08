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


if __name__ == "__main__":
    unittest.main()
