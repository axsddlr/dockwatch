"""execute_portainer_compose_update must refuse to act when Portainer is disabled."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from dockwatch.config import DockwatchConfig, PortainerConfig
from dockwatch.updater import UpdatePlan, execute_portainer_compose_update


def _plan(**overrides) -> UpdatePlan:
    defaults = dict(
        container_name="svc",
        container_id="container-svc",
        source="portainer",
        mode="portainer-compose",
        allowed=True,
        image_ref="repo/svc:1.0",
        deployed_display="1.0",
        remote_display="1.1",
        compose_project="stack",
        compose_service="svc",
        current_tag="1.0",
        remote_tag="1.1",
        environment_id="5",
    )
    defaults.update(overrides)
    return UpdatePlan(**defaults)


class ExecutePortainerComposeUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_when_portainer_disabled(self) -> None:
        config = DockwatchConfig()
        config.portainer = PortainerConfig(url="http://portainer:9000", api_key="key", enabled=False)

        # If the guard didn't short-circuit, this would hit the network (no client mocked).
        result = await execute_portainer_compose_update(_plan(), config)

        self.assertFalse(result.success)
        self.assertIn("disabled", result.message.lower())

    async def test_resolves_environment_id_from_stack_endpoint(self) -> None:
        config = DockwatchConfig()
        config.portainer = PortainerConfig(url="http://portainer:9000", api_key="key", enabled=True)

        client = MagicMock()
        client.find_stack_by_name = AsyncMock(return_value={"Id": 3, "EndpointId": 7, "Env": []})
        client.get_stack_file = AsyncMock(return_value="services:\n  svc:\n    image: repo/svc:1.0\n")
        client.update_stack = AsyncMock(return_value=None)

        with patch("dockwatch.updater.PortainerClient", return_value=client):
            result = await execute_portainer_compose_update(_plan(environment_id=None), config)

        self.assertTrue(result.success)
        client.update_stack.assert_awaited_once()
        args, kwargs = client.update_stack.await_args
        self.assertEqual(args[0], 3)
        self.assertEqual(args[1], 7)


if __name__ == "__main__":
    unittest.main()
