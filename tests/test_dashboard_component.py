from __future__ import annotations

import unittest
from unittest.mock import patch

from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.web.pages.settings import build_sample_notification_results
from dockwatch.web.shell import NAV_ITEMS
from dockwatch.web.components.container_table import ContainerStatusTable


class _Ctx:
    def __init__(self, owner) -> None:  # noqa: ANN001
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def classes(self, _value: str):
        return self

    def style(self, _value: str):
        return self

    def props(self, _value: str | None = None, **_kwargs):
        return self

    def set_visibility(self, _value: bool):
        return self

    def clear(self):
        return None


class _Label(_Ctx):
    def __init__(self, owner, text: str) -> None:  # noqa: ANN001
        super().__init__(owner)
        self.text = text


class _TableUI:
    def __init__(self) -> None:
        self.links: list[tuple[str, str]] = []
        self.labels: list[str] = []
        self.buttons: list[str] = []
        self.html_blocks: list[str] = []

    def column(self):
        return _Ctx(self)

    def row(self):
        return _Ctx(self)

    def card(self):
        return _Ctx(self)

    def element(self, _tag: str):
        return _Ctx(self)

    def label(self, text: str):
        self.labels.append(text)
        return _Label(self, text)

    def link(self, label: str, url: str):
        self.links.append((label, url))
        return _Ctx(self)

    def button(self, text: str, **kwargs):  # noqa: ANN003
        self.buttons.append(text)
        return _Ctx(self)

    def html(self, markup: str):
        self.html_blocks.append(markup)
        return _Ctx(self)

    def icon(self, *_args, **_kwargs):
        return _Ctx(self)


class DashboardComponentTests(unittest.TestCase):
    def test_navigation_items_include_dashboard_and_settings(self) -> None:
        self.assertEqual(NAV_ITEMS[0][:2], ("Dashboard", "/"))
        self.assertEqual(NAV_ITEMS[1][:2], ("Settings", "/settings"))

    def test_settings_page_uses_sample_notification_result(self) -> None:
        sample = build_sample_notification_results()

        self.assertEqual(len(sample), 1)
        self.assertEqual(sample[0].container_info.name, "sample")
        self.assertEqual(sample[0].comparison_basis, "version")
        self.assertEqual(sample[0].remote_tag, "1.1.0")

    def test_container_status_table_renders_registry_link(self) -> None:
        ui = _TableUI()
        with patch("dockwatch.web.components.container_table.ui", ui):
            table = ContainerStatusTable()
            table.render(
                [
                    UpdateResult(
                        container_info=ContainerInfo(
                            name="web",
                            container_id="1",
                            image_ref="nginx:1.0.0",
                            registry=RegistryType.DOCKERHUB,
                            namespace="library",
                            image_name="nginx",
                            current_tag="1.0.0",
                        ),
                        latest_tag="1.1.0",
                        is_outdated=True,
                        status=None,
                        event="update",
                        deployed_tag="1.0.0",
                        remote_tag="1.1.0",
                        remote_digest="sha256:abcdef1234567890",
                        comparison_basis="version",
                        comparison_reason="remote version 1.1.0 is newer than deployed 1.0.0",
                    )
                ],
                on_check=lambda _name: None,
                on_pin_toggle=lambda _name: None,
            )

        self.assertEqual(ui.links[0], ("Hub", "https://hub.docker.com/_/nginx"))
        self.assertIn("web", ui.labels)
        self.assertIn("version", ui.labels)
        self.assertIn("1.0.0", ui.labels)
        self.assertIn("1.1.0 (sha256:abcdef123456)", ui.labels)
        self.assertIn("Check", ui.buttons)
        self.assertIn("Pin", ui.buttons)

    def test_container_status_table_renders_filter_empty_message(self) -> None:
        ui = _TableUI()
        with patch("dockwatch.web.components.container_table.ui", ui):
            table = ContainerStatusTable()
            table.render(
                [],
                on_check=lambda _name: None,
                on_pin_toggle=lambda _name: None,
                empty_message="No containers match the selected status filters.",
            )

        self.assertIn("No containers to display.", ui.labels)
        self.assertIn("No containers match the selected status filters.", ui.labels)


if __name__ == "__main__":
    unittest.main()
