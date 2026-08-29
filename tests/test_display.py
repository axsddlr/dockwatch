from __future__ import annotations

import unittest
from unittest.mock import patch

from rich.console import Console

from dockwatch.display import render_update_table
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult, deployed_display_result
from dockwatch.semver import compare_versions


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
            version_diff=compare_versions("v3.39.0", "v4.0.0"),
        )
        console = Console(record=True, width=300)

        with patch("dockwatch.display.console", console):
            render_update_table([result])

        output = console.export_text()
        self.assertIn("latest (v3.39.0)", output)
        self.assertIn("MAJOR", output)
        self.assertIn("digest", output)
        self.assertIn("digest changed behind same tag", output)
        self.assertIn("v3.39.0 (sha256:remote-diges)", output)
        self.assertIn("OUTDATED", output)

    def test_render_update_table_hides_unknown_bump_for_equal_versions(self) -> None:
        result = UpdateResult(
            container_info=ContainerInfo(
                name="nginx",
                container_id="1",
                image_ref="nginx:1.31.3-trixie-perl",
                registry=RegistryType.DOCKERHUB,
                namespace="library",
                image_name="nginx",
                current_tag="1.31.3-trixie-perl",
            ),
            latest_tag="1.31.3-trixie-perl",
            latest_version="1.31.3-trixie-perl",
            remote_tag="1.31.3-trixie-perl",
            remote_digest="sha256:match",
            is_outdated=False,
            comparison_basis="digest",
            comparison_reason="digest matches (1.31.3-trixie-perl)",
            version_diff=compare_versions("1.31.3-trixie-perl", "1.31.3-trixie-perl"),
        )
        console = Console(record=True, width=300)

        with patch("dockwatch.display.console", console):
            render_update_table([result])

        output = console.export_text()
        self.assertIn("UP-TO-DATE", output)
        self.assertNotIn("UNKNOWN", output)


class DeployedDisplayResultTests(unittest.TestCase):
    @staticmethod
    def _result(**kwargs) -> UpdateResult:
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
        return UpdateResult(container_info=info, **kwargs)

    def test_digest_match_with_non_floating_remote_tag_confirms_version(self) -> None:
        result = self._result(
            deployed_digest="sha256:match",
            remote_digest="sha256:match",
            remote_tag="4.13.7",
        )
        self.assertEqual(deployed_display_result(result), "latest = 4.13.7")

    def test_digest_match_with_floating_remote_tag_falls_back_to_version_label(self) -> None:
        result = self._result(
            deployed_digest="sha256:match",
            remote_digest="sha256:match",
            remote_tag="latest",
        )
        self.assertEqual(deployed_display_result(result), "latest (v1.5.4-ls334)")


if __name__ == "__main__":
    unittest.main()
