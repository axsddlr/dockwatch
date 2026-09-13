"""Lifecycle hook execution for dockwatch.

Hooks are shell commands run *inside* a container at defined lifecycle points
(pre/post update, pre-stop, pre/post rollback).  They are resolved from the
per-container ``[hooks.<name>]`` config mapping merged with the
``dockwatch.hook.*`` Docker labels (labels win per phase), and are inert unless
``DOCKWATCH_ENABLE_HOOKS=true``.

Pre-* phases (``PRE_UPDATE``, ``PRE_STOP``, ``PRE_ROLLBACK``) are *blocking*: a
nonzero exit code, an execution error, or a timeout aborts the operation and
leaves the container as-is.  Post-* phases are report-only and never block.

.. important::
    A hook that times out may still be running inside the container.  Docker
    exposes no way to cancel an in-flight exec, so the local ``exec_in_container``
    enforces the deadline on our side only — it abandons the read of the output
    while the in-container process keeps running until it exits on its own.
    A "timed out" pre-* hook is therefore **not** guaranteed to have stopped.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum

from docker.errors import DockerException

from . import docker_client
from .config import AgentConfig, DockwatchConfig, hooks_enabled
from .db import ManifestStore
from .docker_client import ExecResult
from .integrations import AgentClient, AgentError
from .models import ContainerInfo

# Username recorded on hook audit rows, matching the AUTO_UPDATE_USERNAME /
# HEALTH_RESTART_USERNAME convention for scheduler-driven actions.
HOOK_USERNAME = "scheduler (hooks)"

# Cap on the audit ``error`` field so a chatty hook cannot bloat
# update_history rows with an unbounded payload.
HOOK_AUDIT_ERROR_LIMIT = 500

_LABEL_PREFIX = "dockwatch.hook."
_PORTAINER_SKIP_REASON = "hooks are not supported for Portainer-managed containers"


class HookPhase(str, Enum):
    PRE_UPDATE = "pre_update"
    POST_UPDATE = "post_update"
    PRE_STOP = "pre_stop"
    PRE_ROLLBACK = "pre_rollback"
    POST_ROLLBACK = "post_rollback"


BLOCKING_PHASES: frozenset[HookPhase] = frozenset({
    HookPhase.PRE_UPDATE,
    HookPhase.PRE_STOP,
    HookPhase.PRE_ROLLBACK,
})


@dataclass(slots=True)
class HookSpec:
    """One resolved hook command, before execution."""

    phase: HookPhase
    command: str
    timeout_seconds: int
    user: str
    workdir: str
    origin: str  # "label" or "config"


@dataclass(slots=True)
class HookResult:
    """Outcome of one hook attempt.

    ``skipped_reason`` is set only when the hook did not run at all (e.g. an
    unsupported source); it never counts as a failure.  An execution error or
    timeout leaves ``exit_code`` as ``None`` and carries the error text in
    ``output``; that *does* count as a failure.
    """

    phase: HookPhase
    command: str
    exit_code: int | None
    output: str
    truncated: bool
    duration_ms: int
    skipped_reason: str | None

    @property
    def failed(self) -> bool:
        """Whether this hook ran (or attempted to run) and did not succeed."""
        if self.skipped_reason is not None:
            return False
        return self.exit_code is None or self.exit_code != 0


@dataclass(slots=True)
class HookOutcome:
    results: list[HookResult]

    @property
    def blocking_failure(self) -> bool:
        """True only when a *blocking* phase contains at least one failure."""
        return any(
            result.phase in BLOCKING_PHASES and result.failed
            for result in self.results
        )


def _make_spec(phase: HookPhase, command: str, config: DockwatchConfig, origin: str) -> HookSpec:
    defaults = config.hook_defaults
    return HookSpec(
        phase=phase,
        command=command,
        timeout_seconds=defaults.timeout_seconds,
        user=defaults.user,
        workdir=defaults.workdir,
        origin=origin,
    )


def resolve_hooks(info: ContainerInfo, config: DockwatchConfig) -> dict[HookPhase, list[HookSpec]]:
    """Resolve the hooks for one container, merged per phase.

    For each phase, the ``dockwatch.hook.<phase>`` label wins over the
    ``config.hooks[<name>]`` entry when the label key is present.  A present but
    blank label still wins (suppressing the config value) and yields no command.
    Blank/whitespace commands are skipped.  Returns ``{}`` when hooks are
    disabled or the container has no hooks at all.
    """
    resolved: dict[HookPhase, list[HookSpec]] = {}
    if not hooks_enabled():
        return resolved

    container_cfg = config.hooks.get(info.name)

    for phase in HookPhase:
        label_command = info.labels.get(f"{_LABEL_PREFIX}{phase.value}")
        if label_command is not None:
            command = label_command.strip()
            if command:
                resolved[phase] = [_make_spec(phase, command, config, "label")]
            continue

        if container_cfg is None:
            continue
        specs = [
            _make_spec(phase, command.strip(), config, "config")
            for command in (getattr(container_cfg, phase.value) or [])
            if command.strip()
        ]
        if specs:
            resolved[phase] = specs

    return resolved


def _find_agent(config: DockwatchConfig, name: str | None) -> AgentConfig | None:
    for agent in config.agents:
        if agent.enabled and agent.name == name:
            return agent
    return None


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _error_result(phase: HookPhase, spec: HookSpec, message: str, start: float) -> HookResult:
    return HookResult(
        phase=phase,
        command=spec.command,
        exit_code=None,
        output=message,
        truncated=False,
        duration_ms=_elapsed_ms(start),
        skipped_reason=None,
    )


def _local_result(phase: HookPhase, spec: HookSpec, result: ExecResult, start: float) -> HookResult:
    """Turn a synchronous local ``exec_in_container`` result into a HookResult."""
    return HookResult(
        phase=phase,
        command=spec.command,
        exit_code=result.exit_code,
        output=result.output,
        truncated=result.truncated,
        duration_ms=_elapsed_ms(start),
        skipped_reason=None,
    )


def _agent_payload_result(phase: HookPhase, spec: HookSpec, payload: dict, start: float) -> HookResult:
    """Turn an agent exec response payload into a HookResult."""
    exit_code = payload.get("exit_code")
    return HookResult(
        phase=phase,
        command=spec.command,
        exit_code=exit_code if isinstance(exit_code, int) else None,
        output=str(payload.get("output") or ""),
        truncated=bool(payload.get("truncated")),
        duration_ms=_elapsed_ms(start),
        skipped_reason=None,
    )


async def _execute(
    phase: HookPhase,
    info: ContainerInfo,
    config: DockwatchConfig,
    spec: HookSpec,
    environment_id: str | None,
) -> HookResult:
    """Execute one spec, dispatching on ``info.source`` (single shared copy).

    The ``local`` branch offloads the synchronous
    :func:`docker_client.exec_in_container` call to a worker thread; the
    ``agent`` branch awaits the async :meth:`AgentClient.exec_container`.  An
    unsupported source or an execution error becomes a failed ``HookResult``
    (``exit_code=None``) rather than propagating.
    """
    start = time.monotonic()
    try:
        if info.source == "local":
            result = await asyncio.to_thread(
                docker_client.exec_in_container,
                info.name,
                spec.command,
                timeout_seconds=spec.timeout_seconds,
                user=spec.user or None,
                workdir=spec.workdir or None,
            )
            return _local_result(phase, spec, result, start)
        if info.source == "agent":
            agent = _find_agent(config, environment_id)
            if agent is None:
                return _error_result(
                    phase, spec,
                    f"no enabled agent configured for environment '{environment_id}'",
                    start,
                )
            client = AgentClient(base_url=agent.url, token=agent.token)
            payload = await client.exec_container(
                info.container_id,
                command=spec.command,
                timeout_seconds=spec.timeout_seconds,
                user=spec.user or None,
                workdir=spec.workdir or None,
            )
            return _agent_payload_result(phase, spec, payload, start)
        return _error_result(phase, spec, f"unsupported source '{info.source}'", start)
    except (DockerException, AgentError) as exc:
        return _error_result(phase, spec, str(exc), start)
    except Exception as exc:  # noqa: BLE001 -- any exec failure becomes a failed HookResult
        # A mid-stream read error in exec_in_container re-raises the worker's
        # raw exception verbatim (a transport/OSError/httpx error, not a
        # DockerException). It must never escape run_phase into the updater or
        # scheduler caller; collapse it into a failed (exit_code=None) result.
        return _error_result(phase, spec, str(exc), start)


async def _run_phase(
    phase: HookPhase,
    info: ContainerInfo,
    config: DockwatchConfig,
    *,
    store: ManifestStore | None = None,
    environment_id: str | None = None,
    execute: Callable[..., Awaitable[HookResult]],
) -> HookOutcome:
    """Resolve, execute, and audit every hook for ``phase`` (one shared copy).

    ``execute`` is the per-spec executor (an async callable returning a
    ``HookResult``).  ``environment_id`` routes agent containers to their
    agent (falling back to ``info.environment_id``).  Portainer-managed
    containers are not supported: they produce one skipped (never-blocking)
    result per resolved spec.
    """
    specs = resolve_hooks(info, config).get(phase, [])
    if not specs:
        return HookOutcome([])

    env_id = environment_id if environment_id is not None else info.environment_id

    if info.source == "portainer":
        return HookOutcome(_skipped_results(phase, specs, _PORTAINER_SKIP_REASON))

    results: list[HookResult] = []
    for spec in specs:
        result = await execute(phase, info, config, spec, env_id)
        results.append(result)
        if store is not None:
            _record(store, info, phase, result, env_id)
    return HookOutcome(results)


def _audit_error(result: HookResult) -> str:
    if result.exit_code is None:
        return f"command '{result.command}' failed: {result.output or 'hook failed'}"
    text = f"command '{result.command}' exited {result.exit_code}"
    if result.output:
        text += f": {result.output}"
    return text


def _truncate(text: str, limit: int = HOOK_AUDIT_ERROR_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def _record(
    store: ManifestStore,
    info: ContainerInfo,
    phase: HookPhase,
    result: HookResult,
    environment_id: str | None,
) -> None:
    if result.exit_code == 0:
        store.record_update_event(
            container_name=info.name,
            action="hook",
            source=info.source,
            status="success",
            error=None,
            username=HOOK_USERNAME,
            new_tag=phase.value,
            environment_id=environment_id,
        )
        return
    store.record_update_event(
        container_name=info.name,
        action="hook",
        source=info.source,
        status="failed",
        error=_truncate(_audit_error(result)),
        username=HOOK_USERNAME,
        new_tag=phase.value,
        environment_id=environment_id,
    )


def _skipped_results(phase: HookPhase, specs: list[HookSpec], reason: str) -> list[HookResult]:
    return [
        HookResult(
            phase=phase,
            command=spec.command,
            exit_code=None,
            output="",
            truncated=False,
            duration_ms=0,
            skipped_reason=reason,
        )
        for spec in specs
    ]


def skipped_phase(
    phase: HookPhase,
    info: ContainerInfo,
    config: DockwatchConfig,
    *,
    reason: str,
) -> HookOutcome:
    """A skipped outcome for ``phase``: one skipped result per resolved spec.

    Used by callers that must not run a phase at all (e.g. the compose updater,
    which does not own the container stop) but still want an explicit,
    auditable ``skipped_reason`` instead of a silent absence.  Returns an empty
    outcome when the container has no hooks for ``phase``.
    """
    specs = resolve_hooks(info, config).get(phase, [])
    if not specs:
        return HookOutcome([])
    return HookOutcome(_skipped_results(phase, specs, reason))


async def run_phase(
    phase: HookPhase,
    info: ContainerInfo,
    config: DockwatchConfig,
    *,
    store: ManifestStore | None = None,
    environment_id: str | None = None,
) -> HookOutcome:
    """Execute every resolved hook for ``phase`` against ``info`` and audit each."""
    return await _run_phase(
        phase, info, config, store=store, environment_id=environment_id, execute=_execute,
    )


def run_phase_sync(
    phase: HookPhase,
    info: ContainerInfo,
    config: DockwatchConfig,
    *,
    store: ManifestStore | None = None,
    environment_id: str | None = None,
) -> HookOutcome:
    """Synchronous counterpart of :func:`run_phase` for non-async callers.

    Drives the shared async engine (:func:`_run_phase`) under
    :func:`asyncio.run`, so the resolve/classify/audit logic is the exact same
    copy used by :func:`run_phase`.

    .. important::
        Because it drives an event loop, this must be called from a thread with
        **no running event loop** (e.g. the plain/compose update path, which
        runs inside ``asyncio.to_thread``).  An async caller must use
        :func:`run_phase` instead.
    """
    return asyncio.run(
        _run_phase(phase, info, config, store=store, environment_id=environment_id, execute=_execute),
    )
