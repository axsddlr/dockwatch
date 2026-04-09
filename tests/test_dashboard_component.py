from __future__ import annotations

import unittest
from unittest.mock import patch

from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.web.components.container_table import ContainerStatusTable


class _Ctx:
    def __init__(self, owner) -> None:  # noqa: ANN001
        self.owner = owner

    def __enter__(self):
        return self.owner

    def __exit__(self, exc_type, exc, tb):
        return False

    def classes(self, _value: str):
        return self


class _Label(_Ctx):
    def __init__(self, owner, text: str) -> None:  # noqa: ANN001
        super().__init__(owner)
        self.text = text


class _TableUI:
    def __init__(self) -> None:
        self.links: list[tuple[str, str]] = []
        self.labels: list[str] = []
        self.badges: list[tuple[str, str]] = []
        self.buttons: list[str] = []
        self.cards: int = 0
        self.rows: int = 0
        self.cleared: int = 0

    def column(self):
        return _Ctx(self)

    def row(self):
        return _Ctx(self)

    def card(self):
        self.cards += 1
        return _Ctx(self)

    def label(self, text: str):
        self.labels.append(text)
        return _Label(self, text)

    def badge(self, text: str, color: str):
        self.badges.append((text, color))
        return _Ctx(self)

    def link(self, label: str, url: str):
        self.links.append((label, url))
        return _Ctx(self)

    def button(self, text: str, **kwargs):  # noqa: ANN003
        self.buttons.append(text)
        return _Ctx(self)


class DashboardComponentTests(unittest.TestCase):
    def test_container_status_table_renders_registry_link(self) -> None:
        ui = _TableUI()
        with patch("dockwatch.web.components.container_table.ui", ui):
            table = ContainerStatusTable()
            table.rows_container = ui
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


if __name__ == "__main__":
    unittest.main()
