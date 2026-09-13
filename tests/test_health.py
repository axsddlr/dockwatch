from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from dockwatch.config import AgentConfig, DockwatchConfig
from dockwatch.db import HealthStateRecord, ManifestStore
from dockwatch.health import (
    HEALTH_RESTART_USERNAME,
    HealthMonitor,
    HealthPolicy,
    HealthSample,
    _build_policy,
    _compute_next_record,
    _container_opted_in,
    _next_restart_window,
    _should_notify_transition,
    container_health_key,
    decide_restart,
    sample_health,
)
from dockwatch.integrations import AgentError
from dockwatch.models import ContainerInfo, RegistryType


def _now() -> datetime:
    return datetime.now(UTC)


def _info(
    name: str = "web",
    *,
    source: str = "local",
    environment_id: str | None = None,
    state: str | None = None,
    health_status: str | None = None,
    labels: dict[str, str] | None = None,
    health_restart_override: bool | None = None,
) -> ContainerInfo:
    return ContainerInfo(
        name=name,
        container_id="abcdef123456",
        image_ref="nginx:1.0.0",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name="nginx",
        current_tag="1.0.0",
        labels=labels or {},
        source=source,
        environment_id=environment_id,
        state=state,
        health_status=health_status,
        health_restart_override=health_restart_override,
    )


def _sample(
    name: str = "web",
    *,
    source: str = "local",
    environment_id: str | None = None,
    state: str | None = "running",
    health_status: str | None = None,
) -> HealthSample:
    return HealthSample(
        container_name=name,
        source=source,
        environment_id=environment_id,
        state=state,
        health_status=health_status,
        observed_at=_now().isoformat(),
    )


def _record(
    *,
    name: str = "web",
    consecutive: int = 0,
    state: str | None = None,
    health: str | None = None,
    last_changed_at: str | None = None,
    last_restart_at: str | None = None,
    restarts: int = 0,
    window: str | None = None,
    last_notified: str | None = None,
) -> HealthStateRecord:
    return HealthStateRecord(
        container_key=container_health_key("local", None, name),
        container_name=name,
        source="local",
        environment_id=None,
        state=state,
        health_status=health,
        consecutive_unhealthy=consecutive,
        last_changed_at=last_changed_at,
        last_restart_at=last_restart_at,
        restarts_in_window=restarts,
        window_started_at=window,
        last_notified_key=last_notified,
    )


def _policy(**kwargs: object) -> HealthPolicy:
    defaults: dict[str, object] = {
        "enabled": True,
        "auto_restart": True,
        "restart_unhealthy_only": True,
        "unhealthy_after_samples": 2,
        "max_restarts_per_hour": 3,
        "cooldown_seconds": 300,
        "notify_transitions": True,
    }
    defaults.update(kwargs)
    return HealthPolicy(**defaults)


class ContainerHealthKeyTests(unittest.TestCase):
    def test_key_includes_source_environment_and_name(self) -> None:
        self.assertEqual(container_health_key("local", None, "web"), "local||web")
        self.assertEqual(container_health_key("agent", "agent-1", "web"), "agent|agent-1|web")


class DecideRestartTests(unittest.TestCase):
    def test_disabled(self) -> None:
        decision = decide_restart(None, _sample(health_status="unhealthy"), _policy(enabled=False), _now())
        self.assertFalse(decision.should_restart)
        self.assertIn("disabled", decision.reason)

    def test_not_opted_in(self) -> None:
        decision = decide_restart(None, _sample(health_status="unhealthy"), _policy(auto_restart=False), _now())
        self.assertFalse(decision.should_restart)
        self.assertTrue(decision.reason)

    def test_starting_does_not_count(self) -> None:
        previous = _record(consecutive=5, state="running", health="unhealthy")
        decision = decide_restart(previous, _sample(state="running", health_status="starting"), _policy(), _now())
        self.assertFalse(decision.should_restart)
        self.assertIn("starting", decision.reason)

    def test_below_threshold(self) -> None:
        previous = _record(consecutive=1)
        decision = decide_restart(previous, _sample(health_status="unhealthy"), _policy(), _now())
        self.assertFalse(decision.should_restart)
        self.assertIn("threshold", decision.reason)

    def test_first_sight_below_threshold(self) -> None:
        decision = decide_restart(None, _sample(health_status="unhealthy"), _policy(), _now())
        self.assertFalse(decision.should_restart)
        self.assertTrue(decision.reason)

    def test_cooldown_active(self) -> None:
        now = _now()
        previous = _record(consecutive=2, last_restart_at=(now - timedelta(seconds=10)).isoformat())
        decision = decide_restart(previous, _sample(health_status="unhealthy"), _policy(), now)
        self.assertFalse(decision.should_restart)
        self.assertIn("cooldown", decision.reason)

    def test_hourly_cap_hit(self) -> None:
        now = _now()
        previous = _record(consecutive=2, restarts=3, window=(now - timedelta(seconds=60)).isoformat())
        decision = decide_restart(previous, _sample(health_status="unhealthy"), _policy(max_restarts_per_hour=3), now)
        self.assertFalse(decision.should_restart)
        self.assertIn("cap", decision.reason)

    def test_hourly_cap_expired_allows_restart(self) -> None:
        now = _now()
        previous = _record(consecutive=2, restarts=3, window=(now - timedelta(seconds=3601)).isoformat())
        decision = decide_restart(previous, _sample(health_status="unhealthy"), _policy(max_restarts_per_hour=3), now)
        self.assertTrue(decision.should_restart)

    def test_positive(self) -> None:
        previous = _record(consecutive=2)
        decision = decide_restart(previous, _sample(health_status="unhealthy"), _policy(), _now())
        self.assertTrue(decision.should_restart)
        self.assertTrue(decision.reason)

    def test_exited_actionable_when_unhealthy_only_false(self) -> None:
        previous = _record(consecutive=2)
        decision = decide_restart(previous, _sample(state="exited"), _policy(restart_unhealthy_only=False), _now())
        self.assertTrue(decision.should_restart)

    def test_exited_not_actionable_when_unhealthy_only_true(self) -> None:
        previous = _record(consecutive=2)
        decision = decide_restart(previous, _sample(state="exited"), _policy(restart_unhealthy_only=True), _now())
        self.assertFalse(decision.should_restart)

    def test_healthy_not_actionable(self) -> None:
        previous = _record(consecutive=2)
        decision = decide_restart(previous, _sample(state="running", health_status="healthy"), _policy(), _now())
        self.assertFalse(decision.should_restart)

    def test_running_without_health_status_not_actionable(self) -> None:
        previous = _record(consecutive=2)
        decision = decide_restart(previous, _sample(state="running", health_status=None), _policy(), _now())
        self.assertFalse(decision.should_restart)

    def test_cooldown_expired_allows_restart(self) -> None:
        now = _now()
        previous = _record(consecutive=2, last_restart_at=(now - timedelta(seconds=301)).isoformat())
        decision = decide_restart(previous, _sample(health_status="unhealthy"), _policy(cooldown_seconds=300), now)
        self.assertTrue(decision.should_restart)


class OptInResolutionTests(unittest.TestCase):
    def test_label_opt_in(self) -> None:
        info = _info(health_restart_override=True)
        self.assertTrue(_container_opted_in(info, set()))

    def test_store_flag_opt_in(self) -> None:
        info = _info()
        self.assertTrue(_container_opted_in(info, {"web"}))

    def test_neither_not_eligible(self) -> None:
        info = _info()
        self.assertFalse(_container_opted_in(info, set()))

    def test_explicit_opt_out_beats_both(self) -> None:
        info = _info(labels={"dockwatch.health": "false"}, health_restart_override=True)
        self.assertFalse(_container_opted_in(info, {"web"}))

    def test_global_toggle_off_disables_auto_restart(self) -> None:
        config = DockwatchConfig()
        config.health.auto_restart = False
        info = _info(health_restart_override=True)
        policy = _build_policy(config, info, {"web"})
        self.assertFalse(policy.auto_restart)

    def test_build_policy_copies_health_fields(self) -> None:
        config = DockwatchConfig()
        config.health.enabled = True
        config.health.auto_restart = True
        config.health.restart_unhealthy_only = False
        config.health.unhealthy_after_samples = 5
        config.health.max_restarts_per_hour = 9
        config.health.cooldown_seconds = 42
        config.health.notify_transitions = False
        policy = _build_policy(config, _info(health_restart_override=True), set())
        self.assertTrue(policy.enabled)
        self.assertTrue(policy.auto_restart)
        self.assertFalse(policy.restart_unhealthy_only)
        self.assertEqual(policy.unhealthy_after_samples, 5)
        self.assertEqual(policy.max_restarts_per_hour, 9)
        self.assertEqual(policy.cooldown_seconds, 42)
        self.assertFalse(policy.notify_transitions)


class CounterMaintenanceTests(unittest.TestCase):
    def test_consecutive_increments_then_resets(self) -> None:
        policy = _policy()
        now = _now()
        first = _compute_next_record(None, _sample(health_status="unhealthy"), policy, now)
        self.assertEqual(first.consecutive_unhealthy, 1)
        second = _compute_next_record(first, _sample(health_status="unhealthy"), policy, now)
        self.assertEqual(second.consecutive_unhealthy, 2)
        third = _compute_next_record(second, _sample(health_status="healthy"), policy, now)
        self.assertEqual(third.consecutive_unhealthy, 0)

    def test_starting_resets_streak(self) -> None:
        policy = _policy()
        now = _now()
        previous = _record(consecutive=5, state="running", health="unhealthy")
        record = _compute_next_record(previous, _sample(state="running", health_status="starting"), policy, now)
        self.assertEqual(record.consecutive_unhealthy, 0)

    def test_last_changed_at_only_moves_on_change(self) -> None:
        policy = _policy()
        now = _now()
        previous = _record(state="running", health=None, last_changed_at="2026-01-01T00:00:00+00:00")
        unchanged = _compute_next_record(previous, _sample(state="running"), policy, now)
        self.assertEqual(unchanged.last_changed_at, "2026-01-01T00:00:00+00:00")
        changed = _compute_next_record(previous, _sample(state="exited"), policy, now)
        self.assertEqual(changed.last_changed_at, now.isoformat())

    def test_window_resets_after_hour(self) -> None:
        now = _now()
        previous = _record(restarts=5, window=(now - timedelta(seconds=3601)).isoformat())
        window, restarts = _next_restart_window(previous, now)
        self.assertEqual(window, now.isoformat())
        self.assertEqual(restarts, 1)

    def test_window_increments_within_hour(self) -> None:
        now = _now()
        previous = _record(restarts=2, window=(now - timedelta(seconds=60)).isoformat())
        window, restarts = _next_restart_window(previous, now)
        self.assertEqual(window, previous.window_started_at)
        self.assertEqual(restarts, 3)

    def test_window_none_starts_fresh(self) -> None:
        now = _now()
        window, restarts = _next_restart_window(None, now)
        self.assertEqual(window, now.isoformat())
        self.assertEqual(restarts, 1)

    def test_compute_next_record_carries_forward_restart_counters(self) -> None:
        policy = _policy()
        now = _now()
        previous = _record(
            consecutive=2,
            state="running",
            health="unhealthy",
            last_restart_at="2026-01-01T00:00:00+00:00",
            restarts=3,
            window="2026-01-01T00:00:00+00:00",
        )
        record = _compute_next_record(previous, _sample(health_status="unhealthy"), policy, now)
        self.assertEqual(record.last_restart_at, "2026-01-01T00:00:00+00:00")
        self.assertEqual(record.restarts_in_window, 3)
        self.assertEqual(record.window_started_at, "2026-01-01T00:00:00+00:00")


class TransitionNotificationTests(unittest.TestCase):
    def test_notify_transitions_false_suppresses(self) -> None:
        previous = _record(state="running", health=None)
        self.assertFalse(_should_notify_transition(previous, _sample(state="exited"), _policy(notify_transitions=False)))

    def test_no_change_suppresses(self) -> None:
        previous = _record(state="running", health=None)
        self.assertFalse(_should_notify_transition(previous, _sample(state="running"), _policy()))

    def test_change_notifies(self) -> None:
        previous = _record(state="running", health=None)
        self.assertTrue(_should_notify_transition(previous, _sample(state="exited"), _policy()))

    def test_repeat_identical_transition_deduped(self) -> None:
        previous = _record(state="running", health=None, last_notified="exited|None")
        self.assertFalse(_should_notify_transition(previous, _sample(state="exited"), _policy()))

    def test_first_sight_is_not_a_transition(self) -> None:
        self.assertFalse(_should_notify_transition(None, _sample(state="exited"), _policy()))

    def test_disabled_policy_suppresses_transition(self) -> None:
        previous = _record(state="running", health=None)
        self.assertFalse(_should_notify_transition(previous, _sample(state="exited"), _policy(enabled=False)))


class SampleHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_sample_health_maps_containers(self) -> None:
        config = DockwatchConfig()
        info = _info(state="running", health_status="healthy")
        discovery = MagicMock(containers=[info], environments=[], errors=[])
        with patch("dockwatch.health.discover_containers", new=AsyncMock(return_value=discovery)) as mock_discover:
            samples = await sample_health(config)
        mock_discover.assert_awaited_once_with(config, source="all")
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].container_name, "web")
        self.assertEqual(samples[0].state, "running")
        self.assertEqual(samples[0].health_status, "healthy")
        self.assertTrue(samples[0].observed_at)

    async def test_sample_health_emits_discovery_errors(self) -> None:
        config = DockwatchConfig()
        discovery = MagicMock(containers=[], environments=[], errors=["backend down"])
        emitted: list[str] = []
        with patch("dockwatch.health.discover_containers", new=AsyncMock(return_value=discovery)):
            samples = await sample_health(config, emit=emitted.append)
        self.assertEqual(samples, [])
        self.assertEqual(emitted, ["Health discovery error: backend down"])


class HealthMonitorRunOnceTests(unittest.IsolatedAsyncioTestCase):
    def _monitor(self, config: DockwatchConfig, store: ManifestStore, **kwargs: object) -> HealthMonitor:
        return HealthMonitor(config=config, store=store, emit=lambda _m: None, **kwargs)

    async def test_run_once_restarts_audits_and_notifies(self) -> None:
        config = DockwatchConfig()
        config.health.enabled = True
        config.health.auto_restart = True
        config.health.unhealthy_after_samples = 1
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            store.upsert_health_state(_record(consecutive=1, state="running", health="unhealthy"))
            info = _info(state="running", health_status="unhealthy", health_restart_override=True)
            monitor = self._monitor(config, store, sample_loader=lambda: [info])
            with patch.object(monitor, "_restart", new=AsyncMock(return_value=(True, None))), patch(
                "dockwatch.health.send_configured_events", new=AsyncMock(return_value=[])
            ) as mock_send:
                result = await monitor.run_once()

            self.assertTrue(result)
            history = store.list_update_history("web")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].action, "health_restart")
            self.assertEqual(history[0].status, "success")
            self.assertEqual(history[0].username, HEALTH_RESTART_USERNAME)
            events = mock_send.call_args[0][0]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].kind, "health")
            self.assertEqual(events[0].severity, "warning")

    async def test_failing_restart_does_not_stop_cycle(self) -> None:
        config = DockwatchConfig()
        config.health.enabled = True
        config.health.auto_restart = True
        config.health.unhealthy_after_samples = 1
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            store.upsert_health_state(_record(name="a", consecutive=1, state="running", health="unhealthy"))
            store.upsert_health_state(_record(name="b", consecutive=1, state="running", health="unhealthy"))
            info_a = _info(name="a", state="running", health_status="unhealthy", health_restart_override=True)
            info_b = _info(name="b", state="running", health_status="unhealthy", health_restart_override=True)
            monitor = self._monitor(config, store, sample_loader=lambda: [info_a, info_b])
            with patch.object(
                monitor, "_restart", new=AsyncMock(side_effect=[(False, "boom"), (True, None)])
            ), patch("dockwatch.health.send_configured_events", new=AsyncMock(return_value=[])) as mock_send:
                await monitor.run_once()

            history_a = store.list_update_history("a")
            history_b = store.list_update_history("b")
            self.assertEqual(history_a[0].status, "failed")
            self.assertEqual(history_a[0].error, "boom")
            self.assertEqual(history_b[0].status, "success")
            events = mock_send.call_args[0][0]
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0].severity, "error")
            self.assertEqual(events[1].severity, "warning")

    async def test_transition_notification_suppressed_when_disabled(self) -> None:
        config = DockwatchConfig()
        config.health.enabled = True
        config.health.notify_transitions = False
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            store.upsert_health_state(_record(state="running", health="healthy"))
            info = _info(state="exited", health_status=None)
            monitor = self._monitor(config, store, sample_loader=lambda: [info])
            with patch("dockwatch.health.send_configured_events", new=AsyncMock(return_value=[])) as mock_send:
                await monitor.run_once()
            mock_send.assert_not_called()

    async def test_run_once_skips_overlap(self) -> None:
        config = DockwatchConfig()
        config.health.enabled = True
        emitted: list[str] = []
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")

            async def slow_load() -> list[ContainerInfo]:
                await asyncio.sleep(0.05)
                return []

            monitor = HealthMonitor(config=config, store=store, emit=emitted.append, sample_loader=slow_load)
            first = asyncio.create_task(monitor.run_once())
            await asyncio.sleep(0)
            second = await monitor.run_once()
            first_result = await first

        self.assertTrue(first_result)
        self.assertFalse(second)
        self.assertIn("Skipped health run", emitted[0])

    async def test_no_broadcast_no_crash(self) -> None:
        config = DockwatchConfig()
        config.health.enabled = True
        config.health.auto_restart = True
        config.health.unhealthy_after_samples = 1
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            store.upsert_health_state(_record(consecutive=1, state="running", health="unhealthy"))
            info = _info(state="running", health_status="unhealthy", health_restart_override=True)
            monitor = self._monitor(config, store, sample_loader=lambda: [info])
            with patch.object(monitor, "_restart", new=AsyncMock(return_value=(True, None))), patch(
                "dockwatch.health.send_configured_events", new=AsyncMock(return_value=[])
            ):
                result = await monitor.run_once()
        self.assertTrue(result)

    async def test_broadcast_emits_health_events(self) -> None:
        config = DockwatchConfig()
        config.health.enabled = True
        config.health.auto_restart = True
        config.health.unhealthy_after_samples = 1
        broadcast = AsyncMock()
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            store.upsert_health_state(_record(consecutive=1, state="running", health="unhealthy"))
            info = _info(state="running", health_status="unhealthy", health_restart_override=True)
            monitor = self._monitor(config, store, sample_loader=lambda: [info], broadcast=broadcast)
            with patch.object(monitor, "_restart", new=AsyncMock(return_value=(True, None))), patch(
                "dockwatch.health.send_configured_events", new=AsyncMock(return_value=[])
            ):
                await monitor.run_once()
        names = [call.args[0] for call in broadcast.await_args_list]
        self.assertIn("health_restarted", names)
        self.assertIn("health_updated", names)

    async def test_disabled_run_once_is_inert(self) -> None:
        config = DockwatchConfig()  # health.enabled=False by default
        config.health.auto_restart = True
        config.health.unhealthy_after_samples = 1
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            store.upsert_health_state(_record(consecutive=2, state="running", health="unhealthy"))
            loaded: list[ContainerInfo] = []
            info = _info(state="exited", health_status=None, health_restart_override=True)

            def loader() -> list[ContainerInfo]:
                loaded.append(info)
                return [info]

            restart = AsyncMock(return_value=(True, None))
            broadcast = AsyncMock()
            emitted: list[str] = []
            monitor = HealthMonitor(
                config=config,
                store=store,
                sample_loader=loader,
                emit=emitted.append,
                broadcast=broadcast,
            )
            with patch.object(monitor, "_restart", new=restart), patch(
                "dockwatch.health.send_configured_events", new=AsyncMock(return_value=[])
            ) as mock_send:
                result = await monitor.run_once()

            self.assertTrue(result)
            self.assertEqual(loaded, [])
            mock_send.assert_not_called()
            restart.assert_not_called()
            broadcast.assert_not_called()
            self.assertEqual(store.list_update_history("web"), [])
            persisted = store.get_health_state(container_health_key("local", None, "web"))
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.consecutive_unhealthy, 2)
            self.assertTrue(any("disabled" in message for message in emitted))

    async def test_disabled_force_run_samples_and_reports(self) -> None:
        config = DockwatchConfig()  # health.enabled=False
        config.health.auto_restart = True
        config.health.unhealthy_after_samples = 1
        broadcast = AsyncMock()
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            store.upsert_health_state(_record(consecutive=2, state="running", health="unhealthy"))
            loaded: list[ContainerInfo] = []
            info = _info(state="running", health_status="unhealthy", health_restart_override=True)

            def loader() -> list[ContainerInfo]:
                loaded.append(info)
                return [info]

            restart = AsyncMock(return_value=(True, None))
            monitor = self._monitor(config, store, sample_loader=loader, broadcast=broadcast)
            with patch.object(monitor, "_restart", new=restart), patch(
                "dockwatch.health.send_configured_events", new=AsyncMock(return_value=[])
            ) as mock_send:
                result = await monitor.run_once(force=True)

            self.assertTrue(result)
            self.assertEqual(loaded, [info])
            persisted = store.get_health_state(container_health_key("local", None, "web"))
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.state, "running")
            self.assertEqual(persisted.health_status, "unhealthy")
            self.assertIn("health_updated", [call.args[0] for call in broadcast.await_args_list])
            restart.assert_not_called()
            mock_send.assert_not_called()
            self.assertEqual(store.list_update_history("web"), [])

    async def test_hourly_cap_holds_across_cycles(self) -> None:
        config = DockwatchConfig()
        config.health.enabled = True
        config.health.auto_restart = True
        config.health.unhealthy_after_samples = 1
        config.health.cooldown_seconds = 0
        config.health.max_restarts_per_hour = 3
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            info = _info(state="running", health_status="unhealthy", health_restart_override=True)
            monitor = self._monitor(config, store, sample_loader=lambda: [info])
            with patch.object(monitor, "_restart", new=AsyncMock(return_value=(True, None))), patch(
                "dockwatch.health.send_configured_events", new=AsyncMock(return_value=[])
            ):
                for _ in range(8):
                    await monitor.run_once()

            history = store.list_update_history("web")
            restarts = [row for row in history if row.action == "health_restart"]
            self.assertEqual(len(restarts), config.health.max_restarts_per_hour)
            self.assertLessEqual(len(restarts), config.health.max_restarts_per_hour)


class RestartDispatchTests(unittest.IsolatedAsyncioTestCase):
    def _monitor(self, config: DockwatchConfig, store: ManifestStore) -> HealthMonitor:
        return HealthMonitor(config=config, store=store)

    async def test_local_restart(self) -> None:
        config = DockwatchConfig()
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            monitor = self._monitor(config, store)
            with patch("dockwatch.health.docker_client.restart_container") as mock_restart:
                ok, err = await monitor._restart(_info(), _sample())
        self.assertTrue(ok)
        self.assertIsNone(err)
        mock_restart.assert_called_once_with("web")

    async def test_agent_restart_missing_config(self) -> None:
        config = DockwatchConfig()
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            monitor = self._monitor(config, store)
            ok, err = await monitor._restart(
                _info(source="agent", environment_id="agent-1"),
                _sample(source="agent", environment_id="agent-1"),
            )
        self.assertFalse(ok)
        self.assertIn("agent", err.lower())

    async def test_agent_restart_error(self) -> None:
        config = DockwatchConfig()
        config.agents = [AgentConfig(name="agent-1", url="http://agent", token="tok", enabled=True)]
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            monitor = self._monitor(config, store)
            with patch("dockwatch.health.AgentClient") as mock_cls:
                mock_cls.return_value.restart_container = AsyncMock(side_effect=AgentError("boom"))
                ok, err = await monitor._restart(
                    _info(source="agent", environment_id="agent-1"),
                    _sample(source="agent", environment_id="agent-1"),
                )
        self.assertFalse(ok)
        self.assertEqual(err, "boom")

    async def test_portainer_restart_requires_enabled(self) -> None:
        config = DockwatchConfig()
        config.portainer.enabled = False
        with TemporaryDirectory() as tmp_dir:
            store = ManifestStore(Path(tmp_dir) / "manifests.db")
            monitor = self._monitor(config, store)
            ok, err = await monitor._restart(
                _info(source="portainer", environment_id="1"),
                _sample(source="portainer", environment_id="1"),
            )
        self.assertFalse(ok)
        self.assertIn("portainer", err.lower())


if __name__ == "__main__":
    unittest.main()
