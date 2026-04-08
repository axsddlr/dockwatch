from __future__ import annotations

import unittest

from dockwatch.links import build_registry_url
from dockwatch.links import build_registry_link
from dockwatch.models import ContainerInfo, RegistryType


class RegistryLinkTests(unittest.TestCase):
    def test_dockerhub_official_image_link(self) -> None:
        info = ContainerInfo(
            name="nginx",
            container_id="1",
            image_ref="nginx:1.0.0",
            registry=RegistryType.DOCKERHUB,
            namespace="library",
            image_name="nginx",
            current_tag="1.0.0",
        )

        self.assertEqual(build_registry_url(info), "https://hub.docker.com/_/nginx")

    def test_dockerhub_namespace_image_link(self) -> None:
        info = ContainerInfo(
            name="app",
            container_id="1",
            image_ref="example/app:1.0.0",
            registry=RegistryType.DOCKERHUB,
            namespace="example",
            image_name="app",
            current_tag="1.0.0",
        )

        self.assertEqual(build_registry_url(info), "https://hub.docker.com/r/example/app")

    def test_ghcr_link(self) -> None:
        info = ContainerInfo(
            name="app",
            container_id="1",
            image_ref="ghcr.io/example/app:1.0.0",
            registry=RegistryType.GHCR,
            namespace="example",
            image_name="app",
            current_tag="1.0.0",
        )

        self.assertEqual(build_registry_url(info), "https://github.com/example/app")

    def test_source_label_wins(self) -> None:
        info = ContainerInfo(
            name="app",
            container_id="1",
            image_ref="ghcr.io/example/app:1.0.0",
            registry=RegistryType.GHCR,
            namespace="example",
            image_name="app",
            current_tag="1.0.0",
            labels={"org.opencontainers.image.source": "https://github.com/example/source"},
        )

        self.assertEqual(build_registry_url(info), "https://github.com/example/source")

    def test_registry_link_label_matches_source(self) -> None:
        info = ContainerInfo(
            name="app",
            container_id="1",
            image_ref="ghcr.io/example/app:1.0.0",
            registry=RegistryType.GHCR,
            namespace="example",
            image_name="app",
            current_tag="1.0.0",
        )

        self.assertEqual(build_registry_link(info), ("Repo", "https://github.com/example/app"))


if __name__ == "__main__":
    unittest.main()
