from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from dockwatch.config import ComposeProjectConfig, DockwatchConfig
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.updater import build_update_plan, execute_update


def _result(**kwargs) -> UpdateResult:
    container_kwargs = dict(
        name="web",
        container_id="abcdef123456",
        image_ref="nginx:1.0.0",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name="nginx",
        current_tag="1.0.0",
    )
    container_kwargs.update(kwargs.pop("container_overrides", {}))
    container = ContainerInfo(**container_kwargs)
    return UpdateResult(
        container_info=container,
        is_outdated=True,
        deployed_tag="1.0.0",
        remote_tag="1.1.0",
        comparison_basis="version",
        **kwargs,
    )


class UpdatePlannerTests(unittest.TestCase):
    def test_plain_local_container_is_allowed(self) -> None:
        plan = build_update_plan(_result(), DockwatchConfig())

        self.assertTrue(plan.allowed)
        self.assertEqual(plan.mode, "plain")

    def test_pinned_container_is_blocked(self) -> None:
        plan = build_update_plan(_result(status="PINNED"), DockwatchConfig())

        self.assertFalse(plan.allowed)
        self.assertIn("pinned", plan.reason or "")

    def test_local_only_image_is_blocked(self) -> None:
        plan = build_update_plan(
            _result(
                container_overrides={
                    "image_ref": "dockwatch-local:dev",
                    "registry": RegistryType.UNKNOWN,
                    "image_name": "dockwatch-local",
                    "current_tag": "dev",
                }
            ),
            DockwatchConfig(),
        )

        self.assertFalse(plan.allowed)
        self.assertIn("unsupported", plan.reason or "")

    def test_compose_container_requires_mapping(self) -> None:
        plan = build_update_plan(
            _result(
                container_overrides={
                    "compose_project": "media",
                    "compose_service": "web",
                }
            ),
            DockwatchConfig(),
        )

        self.assertFalse(plan.allowed)
        self.assertEqual(plan.mode, "compose")

    def test_compose_container_with_mapping_is_allowed(self) -> None:
        config = DockwatchConfig(
            compose_projects={"media": ComposeProjectConfig(workdir="/srv/media")}
        )
        plan = build_update_plan(
            _result(
                container_overrides={
                    "compose_project": "media",
                    "compose_service": "web",
                }
            ),
            config,
        )

        self.assertTrue(plan.allowed)
        self.assertEqual(plan.mode, "compose")


class UpdateExecutionTests(unittest.TestCase):
    def test_execute_update_returns_block_reason(self) -> None:
        result = execute_update(
            build_update_plan(_result(status="PINNED"), DockwatchConfig()),
            DockwatchConfig(),
        )

        self.assertFalse(result.success)
        self.assertIn("pinned", result.message)

    def test_compose_update_uses_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            compose_file = workdir / "compose.yml"
            compose_file.write_text("services:\n  web:\n    image: nginx:1.0.0\n")

            config = DockwatchConfig(
                compose_projects={"media": ComposeProjectConfig(workdir=str(workdir), files=["compose.yml"])}
            )
            plan = build_update_plan(
                _result(
                    container_overrides={
                        "compose_project": "media",
                        "compose_service": "web",
                    }
                ),
                config,
            )

            success_proc = MagicMock(returncode=0, stdout="", stderr="")
            with patch(
                "dockwatch.updater.subprocess.run",
                side_effect=[success_proc, success_proc],
            ) as run_mock:
                result = execute_update(plan, config)

            self.assertTrue(result.success)
            self.assertEqual(run_mock.call_count, 2)
            pull_cmd = run_mock.call_args_list[0].args[0]
            self.assertEqual(pull_cmd[pull_cmd.index("-f") + 1], compose_file.as_posix())
            self.assertIn("image: nginx:1.1.0", compose_file.read_text())

    def test_compose_update_translates_absolute_file_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hostroot = Path(tmp)
            workdir = hostroot / "root" / "jackett"
            workdir.mkdir(parents=True)
            compose_file = workdir / "docker-compose.yml"
            compose_file.write_text("services:\n  jackett:\n    image: nginx:1.0.0\n")

            config = DockwatchConfig(
                compose_projects={
                    "jackett": ComposeProjectConfig(
                        workdir="/root/jackett",
                        files=["/root/jackett/docker-compose.yml"],
                        project_name="jackett",
                    )
                }
            )
            plan = build_update_plan(
                _result(
                    container_overrides={
                        "compose_project": "jackett",
                        "compose_service": "jackett",
                    }
                ),
                config,
            )

            success_proc = MagicMock(returncode=0, stdout="", stderr="")
            with patch.dict("os.environ", {"HOST_MOUNT_PREFIX": str(hostroot)}), patch(
                "dockwatch.updater.subprocess.run",
                side_effect=[success_proc, success_proc],
            ) as run_mock:
                result = execute_update(plan, config)

            self.assertTrue(result.success)
            pull_cmd = run_mock.call_args_list[0].args[0]
            self.assertEqual(pull_cmd[pull_cmd.index("-f") + 1], compose_file.as_posix())
            self.assertEqual(run_mock.call_args_list[0].kwargs["cwd"], workdir)
            self.assertIn("image: nginx:1.1.0", compose_file.read_text())


if __name__ == "__main__":
    unittest.main()
