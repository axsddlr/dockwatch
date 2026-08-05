"""Tests for container discovery and deduplication."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from dockwatch.config import DockwatchConfig
from dockwatch.docker_client import DockerConnectionError
from dockwatch.integrations import PortainerClient, PortainerEnvironment
from dockwatch.models import ContainerInfo, RegistryType
from dockwatch.sources import discover_containers


def _local_container(name: str) -> ContainerInfo:
    return ContainerInfo(
        name=name,
        container_id=f"local-{name}",
        image_ref=f"{name}:latest",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name=name,
        current_tag="latest",
        source="local",
    )


def _portainer_container(name: str, env_id: str = "1") -> ContainerInfo:
    return ContainerInfo(
        name=name,
        container_id=f"portainer-{name}",
        image_ref=f"{name}:latest",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name=name,
        current_tag="latest",
        source="portainer",
        environment_id=env_id,
        environment_name="prod",
    )


def _mock_portainer_result(containers: list[ContainerInfo]) -> AsyncMock:
    discovery = AsyncMock()
    discovery.containers = containers
    discovery.environments = [PortainerEnvironment(id=1, name="prod")]
    discovery.errors = []
    return discovery


class DiscoverContainersTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_all_dedupes_duplicate_names_preferring_portainer(self) -> None:
        with patch(
            "dockwatch.sources.get_running_containers",
            return_value=[_local_container("web")],
        ), patch(
            "dockwatch.sources.discover_portainer",
            return_value=_mock_portainer_result([_portainer_container("web")]),
        ):
            result = await discover_containers(DockwatchConfig(), source="all")

        self.assertEqual(len(result.containers), 1)
        self.assertEqual(result.containers[0].source, "portainer")
        self.assertEqual(result.containers[0].environment_id, "1")

    async def test_source_all_keeps_distinct_names_from_both_sources(self) -> None:
        with patch(
            "dockwatch.sources.get_running_containers",
            return_value=[_local_container("local-only")],
        ), patch(
            "dockwatch.sources.discover_portainer",
            return_value=_mock_portainer_result([_portainer_container("portainer-only")]),
        ):
            result = await discover_containers(DockwatchConfig(), source="all")

        names = {c.name for c in result.containers}
        sources = {c.source for c in result.containers}
        self.assertSetEqual(names, {"local-only", "portainer-only"})
        self.assertSetEqual(sources, {"local", "portainer"})

    async def test_source_all_keeps_local_when_portainer_disabled(self) -> None:
        with patch(
            "dockwatch.sources.get_running_containers",
            return_value=[_local_container("web")],
        ), patch(
            "dockwatch.sources.discover_portainer",
            return_value=_mock_portainer_result([]),
        ):
            result = await discover_containers(DockwatchConfig(), source="all")

        self.assertEqual(len(result.containers), 1)
        self.assertEqual(result.containers[0].source, "local")

    async def test_source_all_handles_local_error_and_proceeds(self) -> None:
        with patch(
            "dockwatch.sources.get_running_containers",
            side_effect=DockerConnectionError("no docker"),
        ), patch(
            "dockwatch.sources.discover_portainer",
            return_value=_mock_portainer_result([_portainer_container("web")]),
        ):
            result = await discover_containers(DockwatchConfig(), source="all")

        self.assertEqual(len(result.containers), 1)
        self.assertEqual(result.containers[0].source, "portainer")

    async def test_source_all_handles_portainer_error_and_proceeds(self) -> None:
        with patch(
            "dockwatch.sources.get_running_containers",
            return_value=[_local_container("web")],
        ), patch(
            "dockwatch.sources.discover_portainer",
            return_value=_mock_portainer_result([]),
        ):
            result = await discover_containers(DockwatchConfig(), source="all")

        self.assertEqual(len(result.containers), 1)
        self.assertEqual(result.containers[0].source, "local")


if __name__ == "__main__":
    unittest.main()
