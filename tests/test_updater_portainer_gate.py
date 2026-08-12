"""execute_portainer_compose_update must refuse to act when Portainer is disabled."""

from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
