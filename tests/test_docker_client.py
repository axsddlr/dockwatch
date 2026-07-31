from __future__ import annotations

import unittest
from unittest.mock import patch

import dockwatch.docker_client as docker_client_module
from dockwatch.docker_client import get_local_platform, get_running_containers, parse_image_ref
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
                    "com.docker.compose.project": "media",
                    "com.docker.compose.service": "web",
                },
            }
        }
        self.image = FakeImage()


class FakeDockerClient:
    def __init__(self) -> None:
        self.containers = self
        self.list_kwargs: dict[str, object] | None = None

    def list(self, **kwargs) -> list[FakeContainer]:
        self.list_kwargs = kwargs
        return [FakeContainer()]

    def close(self) -> None:
        pass


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

    def test_parse_image_ref_treats_single_segment_local_images_as_unknown(self) -> None:
        info = parse_image_ref("dockwatch-local:dev")

        self.assertEqual(info.registry, RegistryType.UNKNOWN)
        self.assertEqual(info.namespace, "library")
        self.assertEqual(info.image_name, "dockwatch-local")
        self.assertEqual(info.current_tag, "dev")

    def test_get_running_containers_uses_docker_metadata(self) -> None:
        fake_client = FakeDockerClient()
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            containers = get_running_containers()

        self.assertEqual(len(containers), 1)
        container = containers[0]
        self.assertEqual(container.name, "web")
        self.assertEqual(container.container_id, "abcdef123456")
        self.assertEqual(container.registry, RegistryType.DOCKERHUB)
        self.assertTrue(container.watch_enabled)
        self.assertEqual(container.repo_digest, "example@sha256:abc123")
        self.assertEqual(container.compose_project, "media")
        self.assertEqual(container.compose_service, "web")
        self.assertEqual(fake_client.list_kwargs, {"all": True})

    def test_parse_image_ref_detects_codeberg_registry(self) -> None:
        info = parse_image_ref("codeberg.org/readeck/readeck:latest")

        self.assertEqual(info.registry, RegistryType.CODEBERG)
        self.assertEqual(info.namespace, "readeck")
        self.assertEqual(info.image_name, "readeck")
        self.assertEqual(info.current_tag, "latest")


class LocalPlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        docker_client_module._local_platform_cached = False
        docker_client_module._local_platform_value = None
        self.addCleanup(self._reset_cache)

    def _reset_cache(self) -> None:
        docker_client_module._local_platform_cached = False
        docker_client_module._local_platform_value = None

    def test_returns_linux_arch_from_daemon_version(self) -> None:
        fake_client = FakeDockerClient()
        fake_client.version = lambda: {"Arch": "arm64"}
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            platform = get_local_platform()

        self.assertEqual(platform, ("linux", "arm64"))

    def test_returns_none_when_daemon_unreachable(self) -> None:
        from docker.errors import DockerException

        with patch("dockwatch.docker_client.docker.from_env", side_effect=DockerException("no daemon")):
            platform = get_local_platform()

        self.assertIsNone(platform)

    def test_result_is_cached_across_calls(self) -> None:
        fake_client = FakeDockerClient()
        fake_client.version = lambda: {"Arch": "amd64"}
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client) as mock_from_env:
            first = get_local_platform()
            second = get_local_platform()

        self.assertEqual(first, ("linux", "amd64"))
        self.assertEqual(second, ("linux", "amd64"))
        mock_from_env.assert_called_once()


if __name__ == "__main__":
    unittest.main()
