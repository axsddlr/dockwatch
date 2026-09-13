from __future__ import annotations

import asyncio

import pytest
from docker.errors import DockerException

from dockwatch.config import AgentConfig, DockwatchConfig, HookConfig, HookDefaultsConfig
from dockwatch.db import ManifestStore
from dockwatch.docker_client import ExecResult
from dockwatch.hooks import (
    HOOK_AUDIT_ERROR_LIMIT,
    HookOutcome,
    HookPhase,
    HookResult,
    hooks_enabled,
    resolve_hooks,
    run_phase,
    run_phase_sync,
    skipped_phase,
)
from dockwatch.models import ContainerInfo, RegistryType


def _info(*, name="web", container_id="abcdef123456", source="local", environment_id=None, labels=None):
    return ContainerInfo(
        name=name,
        container_id=container_id,
        image_ref="nginx:1.0.0",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name="nginx",
        current_tag="1.0.0",
        source=source,
        environment_id=environment_id,
        labels=labels or {},
    )


def _config(*, hooks=None, hook_defaults=None, agents=None):
    return DockwatchConfig(
        hooks=hooks or {},
        hook_defaults=hook_defaults or HookDefaultsConfig(),
        agents=agents or [],
    )


# --- hooks_enabled ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        (" True ", True),
        ("false", False),
        ("", False),
        ("1", False),
        ("yes", False),
    ],
)
def test_hooks_enabled_parsing(monkeypatch, raw, expected) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", raw)
    assert hooks_enabled() is expected


def test_hooks_enabled_unset_is_false(monkeypatch) -> None:
    monkeypatch.delenv("DOCKWATCH_ENABLE_HOOKS", raising=False)
    assert hooks_enabled() is False


# --- resolve_hooks ---


def test_resolve_hooks_gate_off_resolves_nothing(monkeypatch) -> None:
    monkeypatch.delenv("DOCKWATCH_ENABLE_HOOKS", raising=False)
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})
    info = _info(labels={"dockwatch.hook.pre_update": "echo label"})
    assert resolve_hooks(info, config) == {}


def test_resolve_hooks_label_wins_per_phase(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(
        hooks={"web": HookConfig(pre_update=["echo config"], post_update=["echo bye"])}
    )
    info = _info(labels={"dockwatch.hook.pre_update": "echo label"})
    resolved = resolve_hooks(info, config)

    pre = resolved[HookPhase.PRE_UPDATE]
    assert len(pre) == 1
    assert pre[0].command == "echo label"
    assert pre[0].origin == "label"

    post = resolved[HookPhase.POST_UPDATE]
    assert len(post) == 1
    assert post[0].command == "echo bye"
    assert post[0].origin == "config"


def test_resolve_hooks_config_only(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_stop=["echo stop"])})
    resolved = resolve_hooks(_info(), config)
    assert resolved[HookPhase.PRE_STOP][0].command == "echo stop"
    assert resolved[HookPhase.PRE_STOP][0].origin == "config"


def test_resolve_hooks_unknown_container_is_empty(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    assert resolve_hooks(_info(name="nope"), _config()) == {}


def test_resolve_hooks_blank_command_skipped(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["   ", "echo real", ""])})
    resolved = resolve_hooks(_info(), config)
    commands = [spec.command for spec in resolved[HookPhase.PRE_UPDATE]]
    assert commands == ["echo real"]


def test_resolve_hooks_blank_label_suppresses_config(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo config"])})
    info = _info(labels={"dockwatch.hook.pre_update": "   "})
    assert resolve_hooks(info, config) == {}


def test_resolve_hooks_defaults_applied(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(
        hooks={"web": HookConfig(pre_update=["echo hi"])},
        hook_defaults=HookDefaultsConfig(timeout_seconds=30, user="app", workdir="/srv"),
    )
    spec = resolve_hooks(_info(), config)[HookPhase.PRE_UPDATE][0]
    assert spec.timeout_seconds == 30
    assert spec.user == "app"
    assert spec.workdir == "/srv"


# --- blocking semantics ---


def test_blocking_failure_pre_update_failure_blocks() -> None:
    outcome = HookOutcome([HookResult(HookPhase.PRE_UPDATE, "echo", 1, "", False, 10, None)])
    assert outcome.blocking_failure is True


def test_blocking_failure_post_update_failure_does_not_block() -> None:
    outcome = HookOutcome([HookResult(HookPhase.POST_UPDATE, "echo", 1, "", False, 10, None)])
    assert outcome.blocking_failure is False


def test_blocking_failure_success_does_not_block() -> None:
    outcome = HookOutcome([HookResult(HookPhase.PRE_UPDATE, "echo", 0, "", False, 10, None)])
    assert outcome.blocking_failure is False


def test_blocking_failure_skipped_never_blocks() -> None:
    result = HookResult(
        HookPhase.PRE_UPDATE,
        "echo",
        None,
        "",
        False,
        0,
        "hooks are not supported for Portainer-managed containers",
    )
    assert HookOutcome([result]).blocking_failure is False


# --- run_phase ---


def test_run_phase_no_hooks_for_phase_is_empty(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})
    outcome = asyncio.run(run_phase(HookPhase.POST_UPDATE, _info(), config))
    assert outcome.results == []
    assert outcome.blocking_failure is False


def test_run_phase_local_success(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo ok"])})

    def fake_exec(name, command, *, timeout_seconds=60, user=None, workdir=None):
        return ExecResult(exit_code=0, output="ok", truncated=False)

    monkeypatch.setattr("dockwatch.hooks.docker_client.exec_in_container", fake_exec)
    outcome = asyncio.run(run_phase(HookPhase.PRE_UPDATE, _info(), config))
    assert len(outcome.results) == 1
    assert outcome.results[0].exit_code == 0
    assert outcome.blocking_failure is False


def test_run_phase_portainer_skipped_non_blocking(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})
    info = _info(source="portainer", environment_id="2")
    outcome = asyncio.run(run_phase(HookPhase.PRE_UPDATE, info, config))
    assert len(outcome.results) == 1
    result = outcome.results[0]
    assert result.exit_code is None
    assert result.skipped_reason == "hooks are not supported for Portainer-managed containers"
    assert outcome.blocking_failure is False


def test_run_phase_exec_error_blocks_pre_not_post(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(
        hooks={"web": HookConfig(pre_update=["echo pre"], post_update=["echo post"])}
    )

    def fake_exec(name, command, *, timeout_seconds=60, user=None, workdir=None):
        raise DockerException("boom")

    monkeypatch.setattr("dockwatch.hooks.docker_client.exec_in_container", fake_exec)

    pre = asyncio.run(run_phase(HookPhase.PRE_UPDATE, _info(), config))
    assert pre.results[0].exit_code is None
    assert pre.blocking_failure is True

    post = asyncio.run(run_phase(HookPhase.POST_UPDATE, _info(), config))
    assert post.results[0].exit_code is None
    assert post.blocking_failure is False


def test_run_phase_timeout_blocks_pre_not_post(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(
        hooks={"web": HookConfig(pre_update=["echo pre"], post_update=["echo post"])}
    )

    def fake_exec(name, command, *, timeout_seconds=60, user=None, workdir=None):
        # The exact timeout text raised by docker_client.exec_in_container.
        raise DockerException(f"Docker exec timed out after {timeout_seconds}s")

    monkeypatch.setattr("dockwatch.hooks.docker_client.exec_in_container", fake_exec)

    pre = asyncio.run(run_phase(HookPhase.PRE_UPDATE, _info(), config))
    assert pre.results[0].exit_code is None
    assert pre.blocking_failure is True

    post = asyncio.run(run_phase(HookPhase.POST_UPDATE, _info(), config))
    assert post.results[0].exit_code is None
    assert post.blocking_failure is False


def test_run_phase_agent_dispatch(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(
        hooks={"web": HookConfig(pre_update=["echo hi"])},
        agents=[AgentConfig(name="media-pc", url="http://media-pc:8081", token="tok")],
    )
    info = _info(source="agent", environment_id="media-pc")
    calls: dict = {}

    class FakeClient:
        async def exec_container(self, container_id, *, command, timeout_seconds=60, user=None, workdir=None):
            calls["container_id"] = container_id
            calls["command"] = command
            return {"exit_code": 0, "output": "", "truncated": False}

    monkeypatch.setattr("dockwatch.hooks.AgentClient", lambda base_url, token: FakeClient())
    outcome = asyncio.run(run_phase(HookPhase.PRE_UPDATE, info, config))
    assert calls["container_id"] == "abcdef123456"
    assert calls["command"] == "echo hi"
    assert outcome.results[0].exit_code == 0


# --- auditing ---


def test_run_phase_audits_success(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo ok"])})
    store = ManifestStore(tmp_path / "manifests.db")

    def fake_exec(name, command, *, timeout_seconds=60, user=None, workdir=None):
        return ExecResult(exit_code=0, output="ok", truncated=False)

    monkeypatch.setattr("dockwatch.hooks.docker_client.exec_in_container", fake_exec)
    asyncio.run(run_phase(HookPhase.PRE_UPDATE, _info(), config, store=store))

    records = store.list_update_history(container_name="web")
    assert len(records) == 1
    assert records[0].action == "hook"
    assert records[0].status == "success"
    assert records[0].error is None
    assert records[0].new_tag == "pre_update"


def test_run_phase_audits_failure_with_truncated_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})
    store = ManifestStore(tmp_path / "manifests.db")

    def fake_exec(name, command, *, timeout_seconds=60, user=None, workdir=None):
        return ExecResult(exit_code=1, output="x" * 2000, truncated=True)

    monkeypatch.setattr("dockwatch.hooks.docker_client.exec_in_container", fake_exec)
    asyncio.run(run_phase(HookPhase.PRE_UPDATE, _info(), config, store=store))

    records = store.list_update_history(container_name="web")
    assert len(records) == 1
    record = records[0]
    assert record.action == "hook"
    assert record.status == "failed"
    assert record.new_tag == "pre_update"
    assert record.username == "scheduler (hooks)"
    assert record.error is not None
    assert len(record.error) <= HOOK_AUDIT_ERROR_LIMIT
    assert "echo hi" in record.error


def test_run_phase_arbitrary_exception_becomes_failed_result(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})
    store = ManifestStore(tmp_path / "manifests.db")

    def fake_exec(name, command, *, timeout_seconds=60, user=None, workdir=None):
        # A mid-stream read error in exec_in_container re-raises the worker's
        # raw exception (not a DockerException), e.g. an OSError.
        raise OSError("connection reset by peer")

    monkeypatch.setattr("dockwatch.hooks.docker_client.exec_in_container", fake_exec)
    outcome = asyncio.run(run_phase(HookPhase.PRE_UPDATE, _info(), config, store=store))

    assert len(outcome.results) == 1
    result = outcome.results[0]
    assert result.exit_code is None
    assert "connection reset by peer" in result.output
    assert outcome.blocking_failure is True

    records = store.list_update_history(container_name="web")
    assert len(records) == 1
    assert records[0].action == "hook"
    assert records[0].status == "failed"


def test_run_phase_no_store_no_crash(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo ok"])})

    def fake_exec(name, command, *, timeout_seconds=60, user=None, workdir=None):
        return ExecResult(exit_code=0, output="", truncated=False)

    monkeypatch.setattr("dockwatch.hooks.docker_client.exec_in_container", fake_exec)
    outcome = asyncio.run(run_phase(HookPhase.PRE_UPDATE, _info(), config))
    assert len(outcome.results) == 1
    assert outcome.results[0].exit_code == 0


# --- run_phase_sync ---


def test_run_phase_sync_matches_run_phase_local(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})

    def fake_exec(name, command, *, timeout_seconds=60, user=None, workdir=None):
        return ExecResult(exit_code=0, output="ok", truncated=False)

    monkeypatch.setattr("dockwatch.hooks.docker_client.exec_in_container", fake_exec)
    async_outcome = asyncio.run(run_phase(HookPhase.PRE_UPDATE, _info(), config))
    sync_outcome = run_phase_sync(HookPhase.PRE_UPDATE, _info(), config)

    assert len(sync_outcome.results) == 1
    a = async_outcome.results[0]
    s = sync_outcome.results[0]
    assert (s.phase, s.command, s.exit_code, s.output, s.truncated, s.skipped_reason) == (
        a.phase,
        a.command,
        a.exit_code,
        a.output,
        a.truncated,
        a.skipped_reason,
    )
    assert sync_outcome.blocking_failure is False


def test_run_phase_sync_audits_like_run_phase(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})

    def fake_exec(name, command, *, timeout_seconds=60, user=None, workdir=None):
        return ExecResult(exit_code=1, output="boom", truncated=False)

    monkeypatch.setattr("dockwatch.hooks.docker_client.exec_in_container", fake_exec)
    store_a = ManifestStore(tmp_path / "a.db")
    store_b = ManifestStore(tmp_path / "b.db")
    asyncio.run(run_phase(HookPhase.PRE_UPDATE, _info(), config, store=store_a))
    run_phase_sync(HookPhase.PRE_UPDATE, _info(), config, store=store_b)

    rec_a = store_a.list_update_history(container_name="web")
    rec_b = store_b.list_update_history(container_name="web")
    assert len(rec_a) == len(rec_b) == 1
    assert rec_a[0].action == rec_b[0].action == "hook"
    assert rec_a[0].status == rec_b[0].status == "failed"
    assert rec_a[0].new_tag == rec_b[0].new_tag == "pre_update"


def test_run_phase_sync_matches_run_phase_portainer(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})
    info = _info(source="portainer", environment_id="2")
    store_a = ManifestStore(tmp_path / "a.db")
    store_b = ManifestStore(tmp_path / "b.db")

    async_outcome = asyncio.run(run_phase(HookPhase.PRE_UPDATE, info, config, store=store_a))
    sync_outcome = run_phase_sync(HookPhase.PRE_UPDATE, info, config, store=store_b)

    assert len(async_outcome.results) == len(sync_outcome.results) == 1
    a = async_outcome.results[0]
    s = sync_outcome.results[0]
    assert (s.phase, s.command, s.exit_code, s.output, s.truncated, s.skipped_reason) == (
        a.phase, a.command, a.exit_code, a.output, a.truncated, a.skipped_reason,
    )
    assert s.skipped_reason == "hooks are not supported for Portainer-managed containers"
    assert async_outcome.blocking_failure is False
    assert sync_outcome.blocking_failure is False
    # Portainer skips are never audited, so both stores stay empty.
    assert store_a.list_update_history(container_name="web") == []
    assert store_b.list_update_history(container_name="web") == []


def test_run_phase_sync_matches_run_phase_skipped_phase(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})
    info = _info()

    async_outcome = asyncio.run(run_phase(HookPhase.PRE_STOP, info, config))
    sync_outcome = run_phase_sync(HookPhase.PRE_STOP, info, config)

    assert async_outcome.results == []
    assert sync_outcome.results == []


def test_run_phase_sync_portainer_skipped(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})
    info = _info(source="portainer", environment_id="2")
    outcome = run_phase_sync(HookPhase.PRE_UPDATE, info, config)
    assert len(outcome.results) == 1
    assert outcome.results[0].skipped_reason == "hooks are not supported for Portainer-managed containers"
    assert outcome.blocking_failure is False


def test_run_phase_sync_portainer_rollback_phases_skipped(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_rollback=["echo rb"], post_rollback=["echo prb"])})
    info = _info(source="portainer", environment_id="2")
    for phase in (HookPhase.PRE_ROLLBACK, HookPhase.POST_ROLLBACK):
        outcome = run_phase_sync(phase, info, config)
        assert len(outcome.results) == 1
        assert outcome.results[0].skipped_reason == "hooks are not supported for Portainer-managed containers"
        assert outcome.blocking_failure is False


def test_run_phase_sync_agent_bridge(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(
        hooks={"web": HookConfig(pre_update=["echo hi"])},
        agents=[AgentConfig(name="media-pc", url="http://media-pc:8081", token="tok")],
    )
    info = _info(source="agent", environment_id="media-pc")
    calls: dict = {}

    class FakeClient:
        async def exec_container(self, container_id, *, command, timeout_seconds=60, user=None, workdir=None):
            calls["container_id"] = container_id
            calls["command"] = command
            return {"exit_code": 0, "output": "", "truncated": False}

    monkeypatch.setattr("dockwatch.hooks.AgentClient", lambda base_url, token: FakeClient())
    outcome = run_phase_sync(HookPhase.PRE_UPDATE, info, config)
    assert calls["container_id"] == "abcdef123456"
    assert calls["command"] == "echo hi"
    assert outcome.results[0].exit_code == 0


def test_skipped_phase_resolves_and_reports(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_stop=["echo stop"])})
    outcome = skipped_phase(HookPhase.PRE_STOP, _info(), config, reason="compose owns the stop")
    assert len(outcome.results) == 1
    assert outcome.results[0].skipped_reason == "compose owns the stop"
    assert outcome.results[0].command == "echo stop"
    assert outcome.blocking_failure is False


def test_skipped_phase_no_hooks_is_empty(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_ENABLE_HOOKS", "true")
    config = _config(hooks={"web": HookConfig(pre_update=["echo hi"])})
    assert skipped_phase(HookPhase.PRE_STOP, _info(), config, reason="x").results == []
