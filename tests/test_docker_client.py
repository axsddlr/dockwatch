from __future__ import annotations

import unittest
from unittest.mock import patch

from dockwatch.docker_client import get_running_containers, parse_image_ref
from dockwatch.models import RegistryType


class FakeImage:
    def __init__(self) -> None:
        self.attrs = {"RepoDigests": ["example@sha256:abc123"]}
        self.tags = ["docker.io/library/nginx:1.0.0"]


class FakeContainer:
    def __init__(self) -> None:
        self.name = "web"
        self.id = "abcdef1234567890"
        self.attrs = {
            "Config": {
                "Image": "docker.io/library/nginx:1.0.0",
                "Labels": {
                    "dockwatch.enable": "true",
                    "dockwatch.include_tags": "^1\\.;^2\\.",
                },
            }
        }
        self.image = FakeImage()


class FakeDockerClient:
    def __init__(self) -> None:
        self.containers = self

    def list(self) -> list[FakeContainer]:
        return [FakeContainer()]


class DockerClientTests(unittest.TestCase):
    def test_parse_image_ref_reads_label_list_overrides(self) -> None:
        info = parse_image_ref(
            "docker.io/library/nginx:1.0.0",
            labels={
                "dockwatch.include_tags": "^1\\.;^2\\.",
                "dockwatch.exclude_tags": "-rc$,-beta$",
            },
        )

        self.assertEqual(info.registry, RegistryType.DOCKERHUB)
        self.assertEqual(info.include_tags_override, [r"^1\.", r"^2\."])
        self.assertEqual(info.exclude_tags_override, [r"-rc$", r"-beta$"])

    def test_get_running_containers_uses_docker_metadata(self) -> None:
        with patch("dockwatch.docker_client.docker.from_env", return_value=FakeDockerClient()):
            containers = get_running_containers()

        self.assertEqual(len(containers), 1)
        container = containers[0]
        self.assertEqual(container.name, "web")
        self.assertEqual(container.container_id, "abcdef123456")
        self.assertEqual(container.registry, RegistryType.DOCKERHUB)
        self.assertTrue(container.watch_enabled)
        self.assertEqual(container.repo_digest, "example@sha256:abc123")


if __name__ == "__main__":
    unittest.main()
