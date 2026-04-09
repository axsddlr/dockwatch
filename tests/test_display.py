from __future__ import annotations

import unittest
from unittest.mock import patch

from rich.console import Console

from dockwatch.display import render_update_table
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult


class DisplayTests(unittest.TestCase):
    def test_render_update_table_shows_comparison_reason(self) -> None:
        result = UpdateResult(
            container_info=ContainerInfo(
                name="gluetun",
                container_id="1",
                image_ref="qmcgaw/gluetun:latest",
                registry=RegistryType.DOCKERHUB,
                namespace="qmcgaw",
                image_name="gluetun",
                current_tag="latest",
                version_label="v3.39.0",
                compose_image_digest="sha256:local-digest",
            ),
            latest_tag="latest",
            latest_version="v3.39.0",
            remote_tag="latest",
            remote_digest="sha256:remote-digest",
            is_outdated=True,
            event="update",
            comparison_basis="digest",
            comparison_reason="digest changed behind same tag",
        )
        console = Console(record=True, width=160)

        with patch("dockwatch.display.console", console):
            render_update_table([result])

        output = console.export_text()
        self.assertIn("latest (v3.39.0)", output)
        self.assertIn("digest", output)
        self.assertIn("digest changed behind same tag", output)
        self.assertIn("OUTDATED", output)


if __name__ == "__main__":
    unittest.main()
