from __future__ import annotations

import unittest
from unittest.mock import patch

from dockwatch.config import ComposeProjectConfig, DockwatchConfig
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.semver import compare_versions
from dockwatch.updater import UpdatePlan
from dockwatch.web.pages.settings import (
    SettingsFormData,
    build_config_from_form,
    build_sample_notification_results,
    build_settings_form_data,
)
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

    def tooltip(self, _value: str):
        return self


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

    def test_build_settings_form_data_reflects_config_values(self) -> None:
        config = DockwatchConfig(
            pinned=["plex"],
            ignored=["db"],
            notify_only=["web"],
            include_tags=[r"^1\."],
            exclude_tags=[r"-rc$"],
            notify_on=["new", "update"],
            first_check_notify=True,
            webhook_url="https://example.test/webhook",
            discord_webhook="https://discord.test/hook",
            ntfy_url="https://ntfy.test/topic",
            schedule_interval_seconds=300,
            schedule_jitter_seconds=30,
            run_on_startup=False,
            max_concurrent_checks=7,
            compose_projects={"media": ComposeProjectConfig(workdir="/srv/media")},
        )
        config.portainer.enabled = True
        config.portainer.url = "https://portainer.example.test"
        config.portainer.api_key = "secret"
        config.portainer.environments = ["1", "2"]

        form = build_settings_form_data(config)

        self.assertEqual(form.pinned, "plex")
        self.assertEqual(form.ignored, "db")
        self.assertEqual(form.notify_only, "web")
        self.assertEqual(form.include_tags, r"^1\.")
        self.assertEqual(form.exclude_tags, r"-rc$")
        self.assertTrue(form.notify_on_new)
        self.assertTrue(form.notify_on_update)
        self.assertTrue(form.first_check_notify)
        self.assertEqual(form.schedule_interval_seconds, 300)
        self.assertEqual(form.schedule_jitter_seconds, 30)
        self.assertFalse(form.run_on_startup)
        self.assertEqual(form.max_concurrent_checks, 7)
        self.assertTrue(form.portainer_enabled)
        self.assertEqual(form.portainer_environments, "1, 2")

    def test_build_config_from_form_maps_all_fields_and_preserves_compose_projects(self) -> None:
        existing = DockwatchConfig(
            compose_projects={"media": ComposeProjectConfig(workdir="/srv/media", files=["compose.yml"])}
        )
        form = SettingsFormData(
            pinned="plex, plex, jellyfin",
            ignored="db",
            notify_only="api",
            include_tags=r"^1\., ^2\.",
            exclude_tags=r"-rc$, -beta$",
            webhook_url=" https://example.test/webhook ",
            discord_webhook=" https://discord.test/hook ",
            ntfy_url=" https://ntfy.test/topic ",
            notify_on_new=False,
            notify_on_update=False,
            first_check_notify=True,
            schedule_interval_seconds=5,
            schedule_jitter_seconds=-10,
            run_on_startup=True,
            max_concurrent_checks=0,
            portainer_enabled=True,
            portainer_url=" https://portainer.example.test ",
            portainer_api_key=" secret-token ",
            portainer_environments="1, 2, 2",
        )

        config = build_config_from_form(existing, form)

        self.assertEqual(config.pinned, ["plex", "plex", "jellyfin"])
        self.assertEqual(config.ignored, ["db"])
        self.assertEqual(config.notify_only, ["api"])
        self.assertEqual(config.include_tags, [r"^1\.", r"^2\."])
        self.assertEqual(config.exclude_tags, [r"-rc$", r"-beta$"])
        self.assertEqual(config.notify_on, [])
        self.assertTrue(config.first_check_notify)
        self.assertEqual(config.webhook_url, " https://example.test/webhook ")
        self.assertEqual(config.discord_webhook, " https://discord.test/hook ")
        self.assertEqual(config.ntfy_url, " https://ntfy.test/topic ")
        self.assertEqual(config.schedule_interval_seconds, 5)
        self.assertEqual(config.schedule_jitter_seconds, -10)
        self.assertTrue(config.run_on_startup)
        self.assertEqual(config.max_concurrent_checks, 0)
        self.assertTrue(config.portainer.enabled)
        self.assertEqual(config.portainer.url, " https://portainer.example.test ")
        self.assertEqual(config.portainer.api_key, " secret-token ")
        self.assertEqual(config.portainer.environments, ["1", "2", "2"])
        self.assertIn("media", config.compose_projects)

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
                        version_diff=compare_versions("1.0.0", "1.1.0"),
                    )
                ],
                on_check=lambda _name: None,
                on_pin_toggle=lambda _name: None,
                on_update=lambda _name: None,
                update_plans={
                    "web": UpdatePlan(
                        container_name="web",
                        container_id="1",
                        source="local",
                        mode="plain",
                        allowed=True,
                        image_ref="nginx:1.0.0",
                        deployed_display="1.0.0",
                        remote_display="1.1.0",
                    )
                },
            )

        self.assertEqual(ui.links[0], ("Docker Hub", "https://hub.docker.com/_/nginx"))
        self.assertIn("web", ui.labels)
        self.assertIn("version", ui.labels)
        self.assertIn("1.0.0", ui.labels)
        self.assertIn("1.1.0 (sha256:abcdef123456)", ui.labels)
        self.assertIn("Check", ui.buttons)
        self.assertIn("Update", ui.buttons)
        self.assertIn("Pin", ui.buttons)
        self.assertTrue(any("MINOR" in block for block in ui.html_blocks))

    def test_container_status_table_renders_filter_empty_message(self) -> None:
        ui = _TableUI()
        with patch("dockwatch.web.components.container_table.ui", ui):
            table = ContainerStatusTable()
            table.render(
                [],
                on_check=lambda _name: None,
                on_pin_toggle=lambda _name: None,
                on_update=lambda _name: None,
                update_plans={},
                empty_message="No containers match the selected status filters.",
            )

        self.assertIn("No containers to display.", ui.labels)
        self.assertIn("No containers match the selected status filters.", ui.labels)


if __name__ == "__main__":
    unittest.main()
