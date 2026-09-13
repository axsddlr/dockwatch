from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from docker.errors import DockerException, NotFound

from dockwatch.config import ComposeProjectConfig, DockwatchConfig, HookConfig
from dockwatch.db import ManifestStore
from dockwatch.docker_client import ExecResult
from dockwatch.hooks import HOOK_USERNAME, HookOutcome, HookPhase, HookResult
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult
from dockwatch.updater import (
    UpdateExecutionResult,
    UpdatePlan,
    _execute_compose_update,
    _execute_plain_update_with_client,
    build_rollback_plan,
    build_update_plan,
    execute_plan,
    execute_update,
)


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


def _replacement_attrs() -> dict:
    """Minimal inspect attrs for `_create_replacement_container`."""
    return {
        "Config": {
            "Labels": {},
            "Image": "busybox",
            "Cmd": ["sleep", "3600"],
            "Env": [],
            "ExposedPorts": {},
            "OpenStdin": True,
            "Tty": False,
            "Hostname": "web",
            "User": None,
            "WorkingDir": None,
            "Entrypoint": None,
        },
        "HostConfig": {"NetworkMode": "default"},
        "NetworkSettings": {"Networks": {}},
        "Mounts": [],
    }


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

    def test_portainer_compose_container_without_environment_is_allowed(self) -> None:
        plan = build_update_plan(
            _result(
                container_overrides={
                    "source": "portainer",
                    "compose_project": "stack",
                    "compose_service": "svc",
                }
            ),
            DockwatchConfig(),
        )

        self.assertTrue(plan.allowed)
        self.assertEqual(plan.mode, "portainer-compose")
        self.assertIsNone(plan.environment_id)

    def test_portainer_update_plan_threads_labels(self) -> None:
        plan = build_update_plan(
            _result(
                container_overrides={
                    "source": "portainer",
                    "compose_project": "stack",
                    "compose_service": "svc",
                    "labels": {"dockwatch.hook.pre_update": "echo label"},
                }
            ),
            DockwatchConfig(),
        )

        self.assertTrue(plan.allowed)
        self.assertEqual(plan.labels, {"dockwatch.hook.pre_update": "echo label"})


class RollbackPlannerTests(unittest.TestCase):
    def test_plain_container_rollback_is_allowed(self) -> None:
        plan = build_rollback_plan(
            _result(), DockwatchConfig(), old_tag="0.9.0", new_tag="1.0.0",
        )

        self.assertTrue(plan.allowed)
        self.assertEqual(plan.mode, "plain")
        self.assertEqual(plan.image_ref, "nginx:0.9.0")

    def test_plain_container_rollback_blocks_stale_deployed_tag(self) -> None:
        plan = build_rollback_plan(
            _result(), DockwatchConfig(), old_tag="1.0.0", new_tag="1.1.0",
        )

        self.assertFalse(plan.allowed)
        self.assertIn("expected '1.1.0'", plan.reason or "")

    def test_portainer_compose_container_rollback_is_allowed(self) -> None:
        plan = build_rollback_plan(
            _result(
                container_overrides={
                    "source": "portainer",
                    "compose_project": "stack",
                    "compose_service": "svc",
                }
            ),
            DockwatchConfig(),
            old_tag="0.9.0",
            new_tag="1.0.0",
        )

        self.assertTrue(plan.allowed)
        self.assertEqual(plan.mode, "portainer-compose")

    def test_portainer_rollback_plan_threads_labels(self) -> None:
        plan = build_rollback_plan(
            _result(
                container_overrides={
                    "source": "portainer",
                    "compose_project": "stack",
                    "compose_service": "svc",
                    "labels": {"dockwatch.hook.pre_rollback": "echo rb"},
                }
            ),
            DockwatchConfig(),
            old_tag="0.9.0",
            new_tag="1.0.0",
        )

        self.assertTrue(plan.allowed)
        self.assertEqual(plan.labels, {"dockwatch.hook.pre_rollback": "echo rb"})

    def test_portainer_non_compose_container_rollback_is_blocked(self) -> None:
        plan = build_rollback_plan(
            _result(container_overrides={"source": "portainer"}),
            DockwatchConfig(),
            old_tag="0.9.0",
            new_tag="1.0.0",
        )

        self.assertFalse(plan.allowed)
        self.assertIn("compose-managed", plan.reason or "")

    def test_compose_container_rollback_requires_mapping(self) -> None:
        plan = build_rollback_plan(
            _result(container_overrides={"compose_project": "media", "compose_service": "web"}),
            DockwatchConfig(),
            old_tag="1.0.0",
            new_tag="1.1.0",
        )

        self.assertFalse(plan.allowed)
        self.assertEqual(plan.mode, "compose")

    def test_compose_container_rollback_swaps_tags(self) -> None:
        config = DockwatchConfig(
            compose_projects={"media": ComposeProjectConfig(workdir="/srv/media")}
        )
        plan = build_rollback_plan(
            _result(
                container_overrides={
                    "compose_project": "media",
                    "compose_service": "web",
                    "current_tag": "1.1.0",
                }
            ),
            config,
            old_tag="1.0.0",
            new_tag="1.1.0",
        )

        self.assertTrue(plan.allowed)
        self.assertEqual(plan.mode, "compose")
        self.assertEqual(plan.current_tag, "1.1.0")
        self.assertEqual(plan.remote_tag, "1.0.0")

    def test_rollback_blocked_when_deployed_tag_mismatches_history(self) -> None:
        config = DockwatchConfig(
            compose_projects={"media": ComposeProjectConfig(workdir="/srv/media")}
        )
        plan = build_rollback_plan(
            _result(
                container_overrides={
                    "compose_project": "media",
                    "compose_service": "web",
                    "current_tag": "1.2.0",
                }
            ),
            config,
            old_tag="1.0.0",
            new_tag="1.1.0",
        )

        self.assertFalse(plan.allowed)
        self.assertIn("refresh", plan.reason or "")


class OperationFieldTests(unittest.TestCase):
    def test_built_update_plan_operation_is_update(self) -> None:
        plan = build_update_plan(_result(), DockwatchConfig())

        self.assertEqual(plan.operation, "update")

    def test_built_rollback_plan_operation_is_rollback(self) -> None:
        plan = build_rollback_plan(
            _result(), DockwatchConfig(), old_tag="0.9.0", new_tag="1.0.0",
        )

        self.assertEqual(plan.operation, "rollback")

    def test_blocked_update_plan_operation_is_update(self) -> None:
        plan = build_update_plan(_result(status="PINNED"), DockwatchConfig())

        self.assertFalse(plan.allowed)
        self.assertEqual(plan.operation, "update")

    def test_blocked_rollback_plan_operation_is_rollback(self) -> None:
        plan = build_rollback_plan(
            _result(), DockwatchConfig(), old_tag="1.0.0", new_tag="1.1.0",
        )

        self.assertFalse(plan.allowed)
        self.assertEqual(plan.operation, "rollback")


class UpdateExecutionTests(unittest.TestCase):
    def test_execute_update_returns_block_reason(self) -> None:
        result = execute_update(
            build_update_plan(_result(status="PINNED"), DockwatchConfig()),
            DockwatchConfig(),
        )

        self.assertFalse(result.success)
        self.assertIn("pinned", result.message)

    def test_create_replacement_container_uses_supported_kwargs(self) -> None:
        # Regression: the plain-recreate path previously passed `open_stdin`
        # (not a docker-py create_container kwarg), so any non-compose update
        # blew up with TypeError.
        from dockwatch.updater import _create_replacement_container

        container = MagicMock()
        container.attrs = {
            "Config": {
                "Labels": {},
                "Image": "busybox",
                "Cmd": ["sleep", "3600"],
                "Env": [],
                "ExposedPorts": {},
                "OpenStdin": True,
                "Tty": False,
                "Hostname": "web",
                "User": None,
                "WorkingDir": None,
                "Entrypoint": None,
            },
            "HostConfig": {"NetworkMode": "default"},
            "NetworkSettings": {"Networks": {}},
            "Mounts": [],
        }
        client = MagicMock()
        client.api.create_container.return_value = {"Id": "new-id"}
        client.containers.get.return_value = MagicMock()

        _create_replacement_container(container, client, "busybox", "web")

        kwargs = client.api.create_container.call_args.kwargs
        self.assertNotIn("open_stdin", kwargs)
        self.assertIs(kwargs["stdin_open"], True)
        self.assertEqual(kwargs["image"], "busybox")

    def test_create_replacement_container_forwards_healthcheck(self) -> None:
        from dockwatch.updater import _create_replacement_container

        healthcheck = {
            "Test": ["CMD", "true"],
            "Interval": 30000000000,
            "Timeout": 5000000000,
            "Retries": 3,
            "StartPeriod": 0,
        }
        attrs = _replacement_attrs()
        attrs["Config"]["Healthcheck"] = healthcheck
        container = MagicMock()
        container.attrs = attrs
        client = MagicMock()
        client.api.create_container.return_value = {"Id": "new-id"}
        client.containers.get.return_value = MagicMock()

        _create_replacement_container(container, client, "busybox", "web")

        kwargs = client.api.create_container.call_args.kwargs
        self.assertEqual(kwargs["healthcheck"], healthcheck)

    def test_create_replacement_container_omits_healthcheck_when_absent(self) -> None:
        from dockwatch.updater import _create_replacement_container

        container = MagicMock()
        container.attrs = _replacement_attrs()
        client = MagicMock()
        client.api.create_container.return_value = {"Id": "new-id"}
        client.containers.get.return_value = MagicMock()

        _create_replacement_container(container, client, "busybox", "web")

        kwargs = client.api.create_container.call_args.kwargs
        self.assertNotIn("healthcheck", kwargs)

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


class ExecutePlanDispatchTests(unittest.IsolatedAsyncioTestCase):
    def _plan(self, mode: str) -> UpdatePlan:
        return UpdatePlan(
            container_name="web",
            container_id="abcdef123456",
            source="local",
            mode=mode,
            allowed=True,
            image_ref="nginx:1.0.0",
            deployed_display="1.0.0",
            remote_display="1.1.0",
        )

    async def test_execute_plan_dispatches_portainer_compose(self) -> None:
        plan = self._plan("portainer-compose")
        config = DockwatchConfig()
        portainer = AsyncMock(return_value=UpdateExecutionResult(True, "portainer-compose", "ok"))
        agent_update = AsyncMock()
        agent_rollback = AsyncMock()
        local = MagicMock()
        with patch("dockwatch.updater.execute_portainer_compose_update", portainer), patch(
            "dockwatch.updater.execute_agent_update", agent_update
        ), patch("dockwatch.updater.execute_agent_rollback", agent_rollback), patch(
            "dockwatch.updater.execute_update", local
        ):
            result = await execute_plan(plan, config)

        portainer.assert_awaited_once_with(plan, config)
        agent_update.assert_not_awaited()
        agent_rollback.assert_not_awaited()
        local.assert_not_called()
        self.assertTrue(result.success)

    async def test_execute_plan_dispatches_agent_update(self) -> None:
        plan = self._plan("agent-update")
        config = DockwatchConfig()
        portainer = AsyncMock()
        agent_update = AsyncMock(return_value=UpdateExecutionResult(True, "agent-update", "ok"))
        agent_rollback = AsyncMock()
        local = MagicMock()
        with patch("dockwatch.updater.execute_portainer_compose_update", portainer), patch(
            "dockwatch.updater.execute_agent_update", agent_update
        ), patch("dockwatch.updater.execute_agent_rollback", agent_rollback), patch(
            "dockwatch.updater.execute_update", local
        ):
            result = await execute_plan(plan, config)

        agent_update.assert_awaited_once_with(plan, config)
        portainer.assert_not_awaited()
        agent_rollback.assert_not_awaited()
        local.assert_not_called()
        self.assertTrue(result.success)

    async def test_execute_plan_dispatches_agent_rollback(self) -> None:
        plan = self._plan("agent-rollback")
        config = DockwatchConfig()
        portainer = AsyncMock()
        agent_update = AsyncMock()
        agent_rollback = AsyncMock(return_value=UpdateExecutionResult(True, "agent-rollback", "ok"))
        local = MagicMock()
        with patch("dockwatch.updater.execute_portainer_compose_update", portainer), patch(
            "dockwatch.updater.execute_agent_update", agent_update
        ), patch("dockwatch.updater.execute_agent_rollback", agent_rollback), patch(
            "dockwatch.updater.execute_update", local
        ):
            result = await execute_plan(plan, config)

        agent_rollback.assert_awaited_once_with(plan, config)
        portainer.assert_not_awaited()
        agent_update.assert_not_awaited()
        local.assert_not_called()
        self.assertTrue(result.success)

    async def test_execute_plan_dispatches_plain_via_thread(self) -> None:
        plan = self._plan("plain")
        config = DockwatchConfig()
        portainer = AsyncMock()
        agent_update = AsyncMock()
        agent_rollback = AsyncMock()
        local = MagicMock(return_value=UpdateExecutionResult(True, "plain", "ok"))
        with patch("dockwatch.updater.execute_portainer_compose_update", portainer), patch(
            "dockwatch.updater.execute_agent_update", agent_update
        ), patch("dockwatch.updater.execute_agent_rollback", agent_rollback), patch(
            "dockwatch.updater.execute_update", local
        ):
            result = await execute_plan(plan, config)

        local.assert_called_once_with(plan, config)
        portainer.assert_not_awaited()
        agent_update.assert_not_awaited()
        agent_rollback.assert_not_awaited()
        self.assertTrue(result.success)

    async def test_execute_plan_returns_block_reason_when_not_allowed(self) -> None:
        plan = self._plan("plain")
        plan.allowed = False
        plan.reason = "blocked for testing"

        result = await execute_plan(plan, DockwatchConfig())

        self.assertFalse(result.success)
        self.assertEqual(result.message, "blocked for testing")


class _FakeContainer:
    def __init__(self, name, cid, *, running=True, labels=None, events=None, fail_remove=False, fail_stop=False):
        self.name = name
        self.id = cid
        self._events = events
        self._fail_remove = fail_remove
        self._fail_stop = fail_stop
        self.attrs = {
            "Id": cid,
            "State": {"Running": running},
            "Config": {
                "Labels": labels or {},
                "Image": "nginx:1.0.0",
                "Cmd": ["sleep", "3600"],
                "Env": [],
                "ExposedPorts": {},
                "OpenStdin": True,
                "Tty": False,
                "Hostname": name,
                "User": None,
                "WorkingDir": None,
                "Entrypoint": None,
            },
            "HostConfig": {"NetworkMode": "default"},
            "NetworkSettings": {"Networks": {}},
            "Mounts": [],
        }
        self.renamed_to = None
        self.removed = False

    def _record(self, event):
        if self._events is not None:
            self._events.append(event)

    def stop(self, timeout=10):
        if self._fail_stop:
            raise DockerException("stop failed")
        self._record(f"stop:{self.name}")
        self.attrs["State"]["Running"] = False

    def rename(self, new_name):
        self._record(f"rename:{self.name}:{new_name}")
        self.renamed_to = new_name

    def start(self):
        self._record(f"start:{self.name}")
        self.attrs["State"]["Running"] = True

    def reload(self):
        pass

    def remove(self, force=False):
        if self._fail_remove:
            raise DockerException("remove failed")
        self._record(f"remove:{self.name}")
        self.removed = True


class _FakeContainers:
    def __init__(self, original, replacement):
        self.original = original
        self.replacement = replacement

    def get(self, key):
        if key in (self.original.name, self.original.id):
            return self.original
        if key == self.original.name + "-dockwatch-backup":
            raise NotFound("stale backup not found")
        if key in (self.replacement.name, self.replacement.id):
            return self.replacement
        raise NotFound(f"no container {key}")


class _FakeImages:
    def __init__(self):
        self.pulled = []

    def pull(self, ref):
        self.pulled.append(ref)


class _FakeApi:
    def __init__(self, replacement_id):
        self.replacement_id = replacement_id

    def create_container(self, **kwargs):
        return {"Id": self.replacement_id}

    def create_host_config(self, **kwargs):
        return {}

    def create_endpoint_config(self, **kwargs):
        return {}

    def create_networking_config(self, **kwargs):
        return {}


class _FakeNetworks:
    def get(self, name):
        raise AssertionError("networks.get should not be called for a default network")


class _FakeClient:
    def __init__(self, original, replacement=None, events=None):
        self.original = original
        self.replacement = replacement or _FakeContainer("web-new", "fedcba654321", running=False, events=events)
        self.containers = _FakeContainers(original, self.replacement)
        self.images = _FakeImages()
        self.api = _FakeApi(self.replacement.id)
        self.networks = _FakeNetworks()
        self.close_called = False

    def close(self):
        self.close_called = True


def _plain_plan(**kwargs) -> UpdatePlan:
    fields = dict(
        container_name="web",
        container_id="abcdef123456",
        source="local",
        mode="plain",
        allowed=True,
        image_ref="nginx:1.0.0",
        deployed_display="1.0.0",
        remote_display="1.1.0",
    )
    fields.update(kwargs)
    return UpdatePlan(**fields)


class HookInsertionTests(unittest.TestCase):
    def test_hook_phases_fire_at_the_right_points(self) -> None:
        events: list[str] = []
        original = _FakeContainer("web", "abcdef123456", running=True, events=events)
        client = _FakeClient(original, events=events)
        plan = _plain_plan()
        calls: list[HookPhase] = []

        def runner(phase, info):
            events.append(f"hook:{phase.value}")
            calls.append(phase)
            return HookOutcome([])

        result = _execute_plain_update_with_client(plan, client, hook_runner=runner)

        self.assertTrue(result.success)
        self.assertEqual(calls, [HookPhase.PRE_UPDATE, HookPhase.PRE_STOP, HookPhase.POST_UPDATE])
        self.assertLess(events.index("hook:pre_update"), events.index("stop:web"))
        self.assertLess(events.index("hook:pre_stop"), events.index("stop:web"))
        self.assertLess(events.index("start:web-new"), events.index("hook:post_update"))

    def test_blocking_pre_update_aborts_before_stop(self) -> None:
        events: list[str] = []
        original = _FakeContainer("web", "abcdef123456", running=True, events=events)
        client = _FakeClient(original, events=events)
        plan = _plain_plan()

        def runner(phase, info):
            events.append(f"hook:{phase.value}")
            if phase == HookPhase.PRE_UPDATE:
                return HookOutcome([HookResult(HookPhase.PRE_UPDATE, "exit 1", 1, "", False, 0, None)])
            return HookOutcome([])

        result = _execute_plain_update_with_client(plan, client, hook_runner=runner)

        self.assertFalse(result.success)
        self.assertIn("pre_update", result.message)
        self.assertNotIn("stop:web", events)
        self.assertNotIn("start:web-new", events)
        self.assertIsNone(original.renamed_to)
        self.assertFalse(original.removed)

    def test_post_update_failure_does_not_fail_update(self) -> None:
        original = _FakeContainer("web", "abcdef123456", running=True)
        client = _FakeClient(original)
        plan = _plain_plan()

        def runner(phase, info):
            if phase == HookPhase.POST_UPDATE:
                return HookOutcome([HookResult(HookPhase.POST_UPDATE, "exit 1", 1, "boom", False, 0, None)])
            return HookOutcome([])

        result = _execute_plain_update_with_client(plan, client, hook_runner=runner)

        self.assertTrue(result.success)

    def test_no_hook_runner_runs_no_hooks(self) -> None:
        original = _FakeContainer("web", "abcdef123456", running=True)
        client = _FakeClient(original)
        plan = _plain_plan()

        result = _execute_plain_update_with_client(plan, client)

        self.assertTrue(result.success)
        self.assertFalse(any("hook" in detail for detail in result.details))

    def test_post_rollback_fires_after_original_restarted(self) -> None:
        events: list[str] = []
        original = _FakeContainer("web", "abcdef123456", running=True, events=events, fail_remove=True)
        client = _FakeClient(original, events=events)
        plan = _plain_plan()
        calls: list[HookPhase] = []

        def runner(phase, info):
            events.append(f"hook:{phase.value}")
            calls.append(phase)
            return HookOutcome([])

        result = _execute_plain_update_with_client(plan, client, hook_runner=runner)

        self.assertFalse(result.success)
        self.assertEqual(
            calls,
            [HookPhase.PRE_UPDATE, HookPhase.PRE_STOP, HookPhase.PRE_ROLLBACK, HookPhase.POST_ROLLBACK],
        )
        self.assertLess(events.index("start:web"), events.index("hook:post_rollback"))
        self.assertIn("restarted original container", result.rollback_message or "")
        self.assertNotIn("pulled", result.rollback_message or "")

    def test_compose_pre_update_before_up_and_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "compose.yml").write_text("services:\n  web:\n    image: nginx:1.0.0\n")
            config = DockwatchConfig(
                compose_projects={"media": ComposeProjectConfig(workdir=str(workdir), files=["compose.yml"])},
                hooks={
                    "web": HookConfig(
                        pre_stop=["echo stop"],
                        pre_rollback=["echo rb"],
                        post_rollback=["echo prb"],
                    )
                },
            )
            plan = build_update_plan(
                _result(container_overrides={"compose_project": "media", "compose_service": "web"}),
                config,
            )

            events: list[str] = []

            def runner(phase, info):
                events.append(f"hook:{phase.value}")
                return HookOutcome([])

            def fake_run(cmd, **kwargs):
                events.append("run:up" if "up" in cmd else "run:pull")
                return MagicMock(returncode=0, stdout="", stderr="")

            with patch("dockwatch.updater.subprocess.run", side_effect=fake_run), patch.dict(
                "os.environ", {"DOCKWATCH_ENABLE_HOOKS": "true"},
            ):
                result = _execute_compose_update(plan, config, hook_runner=runner)

        self.assertTrue(result.success)
        self.assertLess(events.index("hook:pre_update"), events.index("run:up"))
        self.assertLess(events.index("run:up"), events.index("hook:post_update"))
        self.assertTrue(any("pre_stop" in d and "skipped" in d for d in result.details))
        self.assertTrue(any("pre_rollback" in d and "skipped" in d for d in result.details))
        self.assertTrue(any("post_rollback" in d and "skipped" in d for d in result.details))

    def test_compose_blocking_pre_update_prevents_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "compose.yml").write_text("services:\n  web:\n    image: nginx:1.0.0\n")
            config = DockwatchConfig(
                compose_projects={"media": ComposeProjectConfig(workdir=str(workdir), files=["compose.yml"])}
            )
            plan = build_update_plan(
                _result(container_overrides={"compose_project": "media", "compose_service": "web"}),
                config,
            )

            def runner(phase, info):
                if phase == HookPhase.PRE_UPDATE:
                    return HookOutcome([HookResult(HookPhase.PRE_UPDATE, "exit 1", 1, "", False, 0, None)])
                return HookOutcome([])

            with patch("dockwatch.updater.subprocess.run") as run_mock:
                result = _execute_compose_update(plan, config, hook_runner=runner)

        self.assertFalse(result.success)
        self.assertIn("pre_update", result.message)
        run_mock.assert_not_called()

    def test_plain_rollback_without_pre_rollback_hook_reports_nothing(self) -> None:
        original = _FakeContainer("web", "abcdef123456", running=True, fail_stop=True)
        client = _FakeClient(original)
        plan = _plain_plan()
        config = DockwatchConfig(hooks={"web": HookConfig(pre_update=["echo hi"])})

        def runner(phase, info):
            return HookOutcome([])

        with patch.dict("os.environ", {"DOCKWATCH_ENABLE_HOOKS": "true"}):
            result = _execute_plain_update_with_client(plan, client, hook_runner=runner, config=config)

        self.assertFalse(result.success)
        self.assertFalse(any("pre_rollback" in detail for detail in result.details))

    def test_plain_rollback_with_pre_rollback_hook_reports_skip(self) -> None:
        original = _FakeContainer("web", "abcdef123456", running=True, fail_stop=True)
        client = _FakeClient(original)
        plan = _plain_plan()
        config = DockwatchConfig(hooks={"web": HookConfig(pre_rollback=["echo rb"])})

        def runner(phase, info):
            return HookOutcome([])

        with patch.dict("os.environ", {"DOCKWATCH_ENABLE_HOOKS": "true"}):
            result = _execute_plain_update_with_client(plan, client, hook_runner=runner, config=config)

        self.assertFalse(result.success)
        self.assertTrue(any("pre_rollback" in d and "skipped" in d for d in result.details))

    def test_compose_timeout_keeps_pre_update_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "compose.yml").write_text("services:\n  web:\n    image: nginx:1.0.0\n")
            config = DockwatchConfig(
                compose_projects={"media": ComposeProjectConfig(workdir=str(workdir), files=["compose.yml"])}
            )
            plan = build_update_plan(
                _result(container_overrides={"compose_project": "media", "compose_service": "web"}),
                config,
            )

            def runner(phase, info):
                if phase == HookPhase.PRE_UPDATE:
                    return HookOutcome([HookResult(HookPhase.PRE_UPDATE, "echo ok", 0, "", False, 0, None)])
                return HookOutcome([])

            with patch(
                "dockwatch.updater.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="docker compose", timeout=1),
            ):
                result = _execute_compose_update(plan, config, hook_runner=runner)

        self.assertFalse(result.success)
        self.assertTrue(any("hook pre_update: ok" in d for d in result.details))

    def test_compose_oserror_keeps_pre_update_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / "compose.yml").write_text("services:\n  web:\n    image: nginx:1.0.0\n")
            config = DockwatchConfig(
                compose_projects={"media": ComposeProjectConfig(workdir=str(workdir), files=["compose.yml"])}
            )
            plan = build_update_plan(
                _result(container_overrides={"compose_project": "media", "compose_service": "web"}),
                config,
            )

            def runner(phase, info):
                if phase == HookPhase.PRE_UPDATE:
                    return HookOutcome([HookResult(HookPhase.PRE_UPDATE, "echo ok", 0, "", False, 0, None)])
                return HookOutcome([])

            with patch("dockwatch.updater.subprocess.run", side_effect=OSError("no docker binary")):
                result = _execute_compose_update(plan, config, hook_runner=runner)

        self.assertFalse(result.success)
        self.assertTrue(any("hook pre_update: ok" in d for d in result.details))

    def test_compose_blocking_pre_update_leaves_file_unmodified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            compose_file = workdir / "compose.yml"
            original = "services:\n  web:\n    image: nginx:1.0.0\n"
            compose_file.write_text(original)
            config = DockwatchConfig(
                compose_projects={"media": ComposeProjectConfig(workdir=str(workdir), files=["compose.yml"])}
            )
            plan = build_update_plan(
                _result(container_overrides={"compose_project": "media", "compose_service": "web"}),
                config,
            )

            def runner(phase, info):
                if phase == HookPhase.PRE_UPDATE:
                    return HookOutcome([HookResult(HookPhase.PRE_UPDATE, "exit 1", 1, "", False, 0, None)])
                return HookOutcome([])

            with patch("dockwatch.updater.subprocess.run") as run_mock:
                result = _execute_compose_update(plan, config, hook_runner=runner)

            self.assertFalse(result.success)
            self.assertIn("pre_update", result.message)
            run_mock.assert_not_called()
            self.assertEqual(compose_file.read_text(), original)

    def test_execute_update_supplies_a_hook_runner(self) -> None:
        original = _FakeContainer("web", "abcdef123456", running=True)
        client = _FakeClient(original)
        plan = _plain_plan()
        phases: list[HookPhase] = []

        def fake_run_phase_sync(phase, info, config, *, store=None, environment_id=None):
            phases.append(phase)
            return HookOutcome([])

        with patch("dockwatch.updater.ManifestStore"), patch(
            "dockwatch.updater._docker_client", return_value=client
        ), patch(
            "dockwatch.updater.run_phase_sync", side_effect=fake_run_phase_sync,
        ), patch.dict("os.environ", {"DOCKWATCH_ENABLE_HOOKS": "true"}):
            result = execute_update(plan, DockwatchConfig())

        self.assertTrue(result.success)
        self.assertIn(HookPhase.PRE_UPDATE, phases)
        self.assertIn(HookPhase.PRE_STOP, phases)
        self.assertIn(HookPhase.POST_UPDATE, phases)


class HookAuditTests(unittest.TestCase):
    def _run_local_update(
        self, store: ManifestStore, hook_config: HookConfig, exec_result: ExecResult,
    ) -> UpdateExecutionResult:
        config = DockwatchConfig(hooks={"web": hook_config})
        plan = _plain_plan()
        original = _FakeContainer("web", "abcdef123456", running=True)
        client = _FakeClient(original)

        def fake_exec(name, command, *, timeout_seconds=60, user=None, workdir=None):
            return exec_result

        with patch("dockwatch.updater.ManifestStore", return_value=store), patch(
            "dockwatch.updater._docker_client", return_value=client
        ), patch("dockwatch.hooks.docker_client.exec_in_container", side_effect=fake_exec), patch.dict(
            "os.environ", {"DOCKWATCH_ENABLE_HOOKS": "true"}
        ):
            return execute_update(plan, config)

    def test_local_update_audits_successful_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ManifestStore(Path(tmp) / "manifests.db")
            result = self._run_local_update(
                store, HookConfig(pre_update=["echo ok"]), ExecResult(exit_code=0, output="ok", truncated=False),
            )

            self.assertTrue(result.success)
            records = store.list_update_history(container_name="web")
            hooks = [r for r in records if r.action == "hook"]
            self.assertEqual(len(hooks), 1)
            record = hooks[0]
            self.assertEqual(record.action, "hook")
            self.assertEqual(record.container_name, "web")
            self.assertEqual(record.source, "local")
            self.assertEqual(record.status, "success")
            self.assertIsNone(record.error)
            self.assertEqual(record.new_tag, "pre_update")
            self.assertEqual(record.username, HOOK_USERNAME)
            self.assertIsNone(record.environment_id)

    def test_local_update_audits_failing_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ManifestStore(Path(tmp) / "manifests.db")
            result = self._run_local_update(
                store, HookConfig(pre_update=["exit 1"]), ExecResult(exit_code=1, output="boom", truncated=False),
            )

            self.assertFalse(result.success)
            records = store.list_update_history(container_name="web")
            hooks = [r for r in records if r.action == "hook"]
            self.assertEqual(len(hooks), 1)
            record = hooks[0]
            self.assertEqual(record.action, "hook")
            self.assertEqual(record.status, "failed")
            self.assertEqual(record.new_tag, "pre_update")
            self.assertEqual(record.username, HOOK_USERNAME)
            self.assertIn("exit 1", record.error or "")
            self.assertIn("exited 1", record.error or "")


if __name__ == "__main__":
    unittest.main()
