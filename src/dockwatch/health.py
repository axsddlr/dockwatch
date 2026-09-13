"""Container healthcheck monitoring with opt-in auto-restart.

The health loop samples every discovered container (local, Portainer and agent
sources), persists a rolling ``HealthStateRecord`` per container, and — when a
container is opted in and its health condition is actionable — restarts it under
a cooldown + hourly-cap policy.  Restart attempts are always audited and
notified; state transitions are notified only when ``notify_transitions`` is on.

``decide_restart`` is pure (``now`` is passed in) so the policy can be tested
exhaustively without I/O or clock reads.
"""

from __future__ import annotations

import asyncio
import inspect
import random
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone

from docker.errors import DockerException

from . import docker_client
from .config import AgentConfig, DockwatchConfig
from .db import HealthStateRecord, ManifestStore
from .integrations import AgentClient, AgentError, PortainerClient, PortainerError
from .models import ContainerInfo
from .notifiers import send_configured_events
from .notifiers.base import NotificationEvent
from .sources import discover_containers
from .utils import parse_bool

HEALTH_RESTART_USERNAME = "scheduler (health)"


@dataclass(slots=True)
class HealthSample:
    container_name: str
    source: str
    environment_id: str | None
    state: str | None
    health_status: str | None
    observed_at: str


@dataclass(slots=True)
class HealthPolicy:
    """Resolved restart policy for a single container.

    ``auto_restart`` is the *per-container* resolution: the global
    ``health.auto_restart`` toggle AND the container's opt-in (auto-restart
    label or the SQLite ``health_restart`` flag), minus any explicit
    ``dockwatch.health=false`` opt-out.
    """

    enabled: bool
    auto_restart: bool
    restart_unhealthy_only: bool
    unhealthy_after_samples: int
    max_restarts_per_hour: int
    cooldown_seconds: int
    notify_transitions: bool


@dataclass(slots=True)
class RestartDecision:
    should_restart: bool
    reason: str


def container_health_key(source: str, environment_id: str | None, name: str) -> str:
    return f"{source}|{environment_id or ''}|{name}"


def _transition_key(state: str | None, health_status: str | None) -> str:
    return f"{state}|{health_status}"


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize a datetime to naive UTC so durations never mix tz offsets."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_actionable(sample: HealthSample, policy: HealthPolicy) -> bool:
    """Whether the sample's condition is one we act on (restart-wise)."""
    if sample.health_status == "unhealthy":
        return True
    return not policy.restart_unhealthy_only and sample.state == "exited"


def decide_restart(
    previous: HealthStateRecord | None,
    sample: HealthSample,
    policy: HealthPolicy,
    now: datetime,
) -> RestartDecision:
    """Decide whether ``sample`` warrants a restart, without I/O or clock reads.

    Checks, in order: monitoring enabled, per-container opt-in, actionable
    condition, consecutive-unhealthy threshold, restart cooldown, then the
    hourly restart cap.  Every branch returns a human-readable reason.
    """
    if not policy.enabled:
        return RestartDecision(False, "health monitoring is disabled")
    if not policy.auto_restart:
        return RestartDecision(False, f"auto-restart is not enabled for container '{sample.container_name}'")
    if not _is_actionable(sample, policy):
        if sample.health_status == "starting":
            return RestartDecision(False, f"container '{sample.container_name}' is still starting")
        return RestartDecision(
            False,
            f"container '{sample.container_name}' is not in a restartable condition "
            f"(state={sample.state}, health={sample.health_status})",
        )

    consecutive = previous.consecutive_unhealthy if previous is not None else 0
    if consecutive < policy.unhealthy_after_samples:
        return RestartDecision(
            False,
            f"container '{sample.container_name}' unhealthy streak ({consecutive}) is below "
            f"the unhealthy threshold of {policy.unhealthy_after_samples} sample(s)",
        )

    if previous is not None:
        last_restart = _parse_ts(previous.last_restart_at)
        if last_restart is not None:
            elapsed = (_to_naive_utc(now) - _to_naive_utc(last_restart)).total_seconds()
            if elapsed < policy.cooldown_seconds:
                return RestartDecision(
                    False,
                    f"container '{sample.container_name}' is in restart cooldown "
                    f"({policy.cooldown_seconds - elapsed:.0f}s remaining)",
                )

    if previous is not None:
        window_started = _parse_ts(previous.window_started_at)
        if window_started is not None:
            in_window = (_to_naive_utc(now) - _to_naive_utc(window_started)).total_seconds() < 3600
            if in_window and previous.restarts_in_window >= policy.max_restarts_per_hour:
                return RestartDecision(
                    False,
                    f"container '{sample.container_name}' reached the hourly restart cap "
                    f"({previous.restarts_in_window} restart(s) in the last hour)",
                )

    return RestartDecision(
        True,
        f"container '{sample.container_name}' is unhealthy (state={sample.state}, "
        f"health={sample.health_status}); restarting",
    )


def _container_opted_in(info: ContainerInfo, health_restart_names: set[str]) -> bool:
    """Per-container opt-in, ignoring the global toggle.

    Eligible when the ``dockwatch.health.auto_restart`` label is true or the
    container's name is in the SQLite ``health_restart`` flag.  An explicit
    ``dockwatch.health=false`` label opts out entirely and beats both.
    """
    if parse_bool(info.labels.get("dockwatch.health"), True) is False:
        return False
    if info.health_restart_override is True:
        return True
    return info.name in health_restart_names


def _build_policy(config: DockwatchConfig, info: ContainerInfo, health_restart_names: set[str]) -> HealthPolicy:
    health = config.health
    return HealthPolicy(
        enabled=health.enabled,
        auto_restart=health.auto_restart and _container_opted_in(info, health_restart_names),
        restart_unhealthy_only=health.restart_unhealthy_only,
        unhealthy_after_samples=health.unhealthy_after_samples,
        max_restarts_per_hour=health.max_restarts_per_hour,
        cooldown_seconds=health.cooldown_seconds,
        notify_transitions=health.notify_transitions,
    )


def _compute_next_record(
    previous: HealthStateRecord | None,
    sample: HealthSample,
    policy: HealthPolicy,
    now: datetime,
) -> HealthStateRecord:
    """Build the persisted record for ``sample`` without I/O.

    ``consecutive_unhealthy`` increments while actionable and resets otherwise;
    ``last_changed_at`` only moves when state/health actually change; the
    restart counters are carried forward (restart dispatch updates them).
    """
    now_iso = now.isoformat()
    key = container_health_key(sample.source, sample.environment_id, sample.container_name)
    actionable = _is_actionable(sample, policy)
    if previous is None:
        return HealthStateRecord(
            container_key=key,
            container_name=sample.container_name,
            source=sample.source,
            environment_id=sample.environment_id,
            state=sample.state,
            health_status=sample.health_status,
            consecutive_unhealthy=1 if actionable else 0,
            last_changed_at=now_iso,
        )

    changed = (previous.state, previous.health_status) != (sample.state, sample.health_status)
    return HealthStateRecord(
        container_key=key,
        container_name=sample.container_name,
        source=sample.source,
        environment_id=sample.environment_id,
        state=sample.state,
        health_status=sample.health_status,
        consecutive_unhealthy=previous.consecutive_unhealthy + 1 if actionable else 0,
        last_changed_at=now_iso if changed else previous.last_changed_at,
        last_restart_at=previous.last_restart_at,
        restarts_in_window=previous.restarts_in_window,
        window_started_at=previous.window_started_at,
        last_notified_key=previous.last_notified_key,
    )


def _next_restart_window(
    previous: HealthStateRecord | None,
    now: datetime,
) -> tuple[str, int]:
    """Return ``(window_started_at, restarts_in_window)`` after a restart."""
    if previous is None or previous.window_started_at is None:
        return now.isoformat(), 1
    window_started = _parse_ts(previous.window_started_at)
    if window_started is None or (_to_naive_utc(now) - _to_naive_utc(window_started)).total_seconds() >= 3600:
        return now.isoformat(), 1
    return previous.window_started_at, previous.restarts_in_window + 1


def _should_notify_transition(
    previous: HealthStateRecord | None,
    sample: HealthSample,
    policy: HealthPolicy,
) -> bool:
    """Whether ``sample`` represents a notifiable health transition.

    Suppressed when monitoring is disabled, when ``notify_transitions`` is
    off, when nothing changed, and when the target ``state|health`` key was
    already notified (dedupe).
    """
    if not policy.enabled:
        return False
    if not policy.notify_transitions:
        return False
    if previous is None:
        return False
    if (previous.state, previous.health_status) == (sample.state, sample.health_status):
        return False
    if previous.last_notified_key == _transition_key(sample.state, sample.health_status):
        return False
    return True


def _to_sample(info: ContainerInfo) -> HealthSample:
    return HealthSample(
        container_name=info.name,
        source=info.source,
        environment_id=info.environment_id,
        state=info.state,
        health_status=info.health_status,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )


async def sample_health(
    config: DockwatchConfig,
    *,
    emit: Callable[[str], None] | None = None,
) -> list[HealthSample]:
    """Discover every source and map each container to a :class:`HealthSample`.

    When ``emit`` is provided, each discovery error is surfaced through it
    (mirroring :meth:`HealthMonitor._discover_all`), so callers can report
    failures instead of silently dropping them.
    """
    discovery = await discover_containers(config, source="all")
    if emit is not None:
        for error in discovery.errors:
            emit(f"Health discovery error: {error}")
    return [_to_sample(info) for info in discovery.containers]


def _find_agent(config: DockwatchConfig, name: str | None) -> AgentConfig | None:
    for agent in config.agents:
        if agent.enabled and agent.name == name:
            return agent
    return None


class HealthMonitor:
    def __init__(
        self,
        *,
        config: DockwatchConfig,
        store: ManifestStore,
        notify: bool = True,
        sample_loader: Callable[[], list[ContainerInfo] | Awaitable[list[ContainerInfo]]] | None = None,
        emit: Callable[[str], None] | None = None,
        broadcast: Callable[[str, dict], Awaitable[None]] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.notify = notify
        # The loader yields the containers to sample (mirroring the scheduler's
        # ``container_loader``); the monitor maps each to a HealthSample so it
        # keeps the full ContainerInfo for opt-in resolution and restart dispatch.
        self.sample_loader = sample_loader or self._discover_all
        self.emit = emit or (lambda _message: None)
        self.broadcast = broadcast
        self._run_lock = asyncio.Lock()

    async def _discover_all(self) -> list[ContainerInfo]:
        discovery = await discover_containers(self.config, source="all")
        for error in discovery.errors:
            self.emit(f"Health discovery error: {error}")
        return discovery.containers

    def next_delay(self) -> float:
        # HealthConfig has no jitter field of its own; reuse the schedule's
        # jitter so health samples spread out the same way scheduled checks do.
        return float(self.config.health.interval_seconds) + random.uniform(0, self.config.schedule_jitter_seconds)

    async def run_once(self, *, force: bool = False) -> bool:
        """Run one health sampling cycle.

        Returns ``True`` when the cycle completed (or was skipped because the
        feature is disabled) and ``False`` when it was skipped because a
        previous run was still in progress.

        When ``config.health.enabled`` is False the monitor is inert: it emits
        a message and returns without sampling, persisting, auditing, notifying
        or broadcasting.  ``force=True`` bypasses that guard so a deliberate
        manual one-shot (a later task's CLI/API command) can still sample and
        report health while the background feature is off; auto-restart remains
        gated by ``policy.enabled``.
        """
        if not self.config.health.enabled and not force:
            self.emit("Health monitoring is disabled; skipping run.")
            return True

        if self._run_lock.locked():
            self.emit("Skipped health run: previous run still in progress.")
            return False

        async with self._run_lock:
            infos = self.sample_loader()
            if inspect.isawaitable(infos):
                infos = await infos

            now = datetime.now(timezone.utc)
            health_restart_names = set(self.store.get_health_restart())

            transition_events: list[NotificationEvent] = []
            restart_targets: list[tuple[ContainerInfo, HealthSample, HealthStateRecord]] = []

            for info in infos:
                sample = _to_sample(info)
                policy = _build_policy(self.config, info, health_restart_names)
                previous = self.store.get_health_state(
                    container_health_key(sample.source, sample.environment_id, sample.container_name)
                )
                record = _compute_next_record(previous, sample, policy, now)
                if self.notify and _should_notify_transition(previous, sample, policy):
                    record.last_notified_key = _transition_key(sample.state, sample.health_status)
                    transition_events.append(
                        NotificationEvent(
                            kind="health",
                            title=f"Container '{sample.container_name}' health changed",
                            message=(
                                f"Container '{sample.container_name}' transitioned from "
                                f"{previous.state if previous else 'unknown'}/"
                                f"{previous.health_status if previous else 'unknown'} to "
                                f"{sample.state}/{sample.health_status}."
                            ),
                            fields={
                                "container": sample.container_name,
                                "state": sample.state or "",
                                "health_status": sample.health_status or "",
                            },
                            severity="info",
                        )
                    )
                if decide_restart(previous, sample, policy, now).should_restart:
                    restart_targets.append((info, sample, record))
                else:
                    self.store.upsert_health_state(record)

            if self.notify and transition_events:
                for error in await send_configured_events(transition_events, self.config):
                    self.emit(f"Notifier error: {error}")

            restart_events: list[NotificationEvent] = []
            for info, sample, record in restart_targets:
                success, error = await self._restart(info, sample)
                self.store.record_update_event(
                    container_name=sample.container_name,
                    action="health_restart",
                    source=sample.source,
                    status="success" if success else "failed",
                    error=error,
                    username=HEALTH_RESTART_USERNAME,
                    environment_id=sample.environment_id,
                )
                window_started, restarts_in_window = _next_restart_window(record, now)
                self.store.upsert_health_state(
                    replace(
                        record,
                        last_restart_at=now.isoformat(),
                        window_started_at=window_started,
                        restarts_in_window=restarts_in_window,
                    )
                )
                if self.notify:
                    restart_events.append(
                        NotificationEvent(
                            kind="health",
                            title=(
                                f"Container '{sample.container_name}' restarted"
                                if success
                                else f"Container '{sample.container_name}' restart failed"
                            ),
                            message=(
                                f"Container '{sample.container_name}' was automatically restarted "
                                "after failing health checks."
                                if success
                                else f"Failed to restart container '{sample.container_name}': {error}"
                            ),
                            fields={"container": sample.container_name, "source": sample.source},
                            severity="warning" if success else "error",
                        )
                    )
                if self.broadcast is not None:
                    await self.broadcast(
                        "health_restarted",
                        {"name": sample.container_name, "success": success},
                    )

            if self.notify and restart_events:
                for error in await send_configured_events(restart_events, self.config):
                    self.emit(f"Notifier error: {error}")

            if self.broadcast is not None:
                await self.broadcast(
                    "health_updated",
                    {"states": [asdict(record) for record in self.store.list_health_states()]},
                )

            return True

    async def _restart(self, info: ContainerInfo, sample: HealthSample) -> tuple[bool, str | None]:
        """Dispatch a restart for one container and return ``(success, error)``."""
        try:
            if sample.source == "local":
                await asyncio.to_thread(docker_client.restart_container, sample.container_name)
                return True, None
            if sample.source == "agent":
                agent = _find_agent(self.config, sample.environment_id)
                if agent is None:
                    return False, f"no enabled agent configured for environment '{sample.environment_id}'"
                client = AgentClient(base_url=agent.url, token=agent.token)
                await client.restart_container(info.container_id)
                return True, None
            if sample.source == "portainer":
                if not self.config.portainer.enabled:
                    return False, "portainer integration is disabled"
                if not sample.environment_id:
                    return False, f"container '{sample.container_name}' has no Portainer environment id"
                client = PortainerClient(base_url=self.config.portainer.url, api_key=self.config.portainer.api_key)
                await client.restart_container(int(sample.environment_id), info.container_id)
                return True, None
            return False, f"unsupported source '{sample.source}'"
        except (DockerException, AgentError, PortainerError, ValueError) as exc:
            return False, str(exc)

    async def serve_forever(self) -> None:
        if self.config.run_on_startup:
            await self.run_once()

        while True:
            await asyncio.sleep(self.next_delay())
            await self.run_once()
