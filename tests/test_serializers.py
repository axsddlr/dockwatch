from __future__ import annotations

import unittest

from dockwatch.api.serializers import serialize_update_result
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult


class SerializeUpdateResultTests(unittest.TestCase):
    def test_includes_display_ready_fields(self) -> None:
        info = ContainerInfo(
            name="bazarr",
            container_id="1",
            image_ref="lscr.io/linuxserver/bazarr:latest",
            registry=RegistryType.LSCR,
            namespace="linuxserver",
            image_name="bazarr",
            current_tag="latest",
            version_label="v1.5.4-ls334",
        )
        result = UpdateResult(
            container_info=info,
            latest_tag="v1.5.5-ls335",
            latest_version="v1.5.5-ls335",
            is_outdated=True,
            deployed_tag="latest",
            deployed_version="v1.5.4-ls334",
            deployed_digest="sha256:local",
            remote_tag="latest",
            remote_digest="sha256:remote",
            comparison_basis="digest",
        )

        data = serialize_update_result(result)

        self.assertEqual(data["deployed_display"], "latest (v1.5.4-ls334)")
        self.assertEqual(data["remote_display"], "v1.5.5-ls335 (sha256:remote)")


if __name__ == "__main__":
    unittest.main()
