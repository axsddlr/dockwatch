"""Opt-in image pruning with a retention guard.

``plan_prune`` is the pure heart of the feature: it decides, without any I/O,
which images are safe to remove given the set of image ids currently in use by
a container (running or stopped) and the configured keep-N-per-repository
retention.  ``execute_prune`` removes each candidate individually — never via
``docker.images.prune``, which cannot honour the retention guard — and records
one audit row per removed image plus a single summary notification.

``PruneScheduler`` mirrors :class:`HealthMonitor`: a background loop that runs
on startup (when configured) and then on an interval, guarded by an
``asyncio.Lock`` so overlapping runs are skipped rather than racing.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from . import docker_client
from .config import DockwatchConfig
from .db import ManifestStore
from .docker_client import ImageInfo
from .integrations import AgentClient, AgentError
from .notifiers import send_configured_events
from .notifiers.base import NotificationEvent

logger = logging.getLogger(__name__)

PRUNE_USERNAME = "scheduler (prune)"

# Pseudo container name used for audit rows so the existing per-container
# history cap keeps working without new columns or a new history table.
PRUNE_CONTAINER_NAME = "(images)"


@dataclass(slots=True)
class PruneCandidate:
    image_id: str
    repo_tags: list[str]
    repo: str
    created: int
    size_bytes: int
    reason: str


@dataclass(slots=True)
class PrunePreview:
    candidates: list[PruneCandidate]
    retained: list[PruneCandidate]
    estimated_bytes: int
    mode: str
    keep_recent: int


@dataclass(slots=True)
class PruneResult:
    removed: list[str]
    failed: list[tuple[str, str]]
    reclaimed_bytes: int


def _repository_of(tag: str) -> str:
    """Strip the tag (or digest) from a repository tag, e.g. ``ghcr.io/o/n:1`` → ``ghcr.io/o/n``."""
    if "@" in tag:
        return tag.split("@", 1)[0]
    last_slash = tag.rfind("/")
    last_colon = tag.rfind(":")
    if last_colon > last_slash:
        return tag[:last_colon]
    return tag


def _repos_of(repo_tags: list[str]) -> list[str]:
    """Return every repository named in ``repo_tags`` (tag/digest stripped).

    ``["<none>"]`` when there are no tags. Duplicate repositories (two tags of
    the same repo, e.g. ``["app:latest", "app:1"]``) collapse to one entry so a
    single image is never double-counted in a repository's keep-N window.
    """
    if not repo_tags:
        return ["<none>"]
    return list(dict.fromkeys(_repository_of(tag) for tag in repo_tags))


def _candidate(image: ImageInfo, repo: str, reason: str) -> PruneCandidate:
    return PruneCandidate(
        image_id=image.image_id,
        repo_tags=list(image.repo_tags),
        repo=repo,
        created=image.created,
        size_bytes=image.size_bytes,
        reason=reason,
    )


def plan_prune(
    images: list[ImageInfo],
    in_use_ids: set[str],
    *,
    mode: str,
    keep_recent: int,
) -> PrunePreview:
    """Decide which images to prune, without any I/O.

    Steps, in order:

    1. Exclude every image whose id is in ``in_use_ids`` — never a candidate
       in any mode.
    2. When ``mode == "dangling"`` only images with *no* repo tags are ever
       candidates.
    3. Assign every remaining image to *every* repository named in its
       ``repo_tags`` (not just the first tag), and retain the union — over all
       repositories — of the newest ``keep_recent`` image ids. A multi-tag
       image is therefore retained when it is among the newest ``keep_recent``
       in *any* of its repositories. The dangling/``<none>`` group has no
       repository ordering and is never retained by this rule.
    4. A candidate is any remaining image whose id is not in that retained
       union (and which has no repo tags when ``mode == "dangling"``), with a
       human-readable ``reason``; retained images go into ``retained``.

    The result is independent of the order of an image's ``repo_tags``.
    """
    remaining = [image for image in images if image.image_id not in in_use_ids]

    # Assign every image to every repository named in its repo_tags.
    by_repo: dict[str, list[ImageInfo]] = {}
    for image in remaining:
        for repo in _repos_of(image.repo_tags):
            if repo != "<none>":
                by_repo.setdefault(repo, []).append(image)

    # Retained ids: the union, over all repositories, of the newest keep_recent
    # image ids. ``retained_repo`` records one repository (deterministically)
    # that retained each id, for the human-readable reason.
    retained_ids: set[str] = set()
    retained_repo: dict[str, str] = {}
    if keep_recent > 0:
        for repo in sorted(by_repo):
            repo_images = by_repo[repo]
            repo_images.sort(key=lambda image: image.created, reverse=True)
            for image in repo_images[:keep_recent]:
                retained_ids.add(image.image_id)
                retained_repo.setdefault(image.image_id, repo)

    candidates: list[PruneCandidate] = []
    retained: list[PruneCandidate] = []

    for image in remaining:
        if mode == "dangling" and image.repo_tags:
            # Tagged images are never candidates in dangling mode.
            continue

        if image.image_id in retained_ids:
            repo = retained_repo[image.image_id]
            retained.append(
                _candidate(
                    image,
                    repo,
                    f"retained (within the newest {keep_recent} in {repo})",
                )
            )
            continue

        if not image.repo_tags:
            candidates.append(_candidate(image, "<none>", "dangling"))
        elif keep_recent > 0:
            repo = min(_repos_of(image.repo_tags))
            candidates.append(
                _candidate(image, repo, f"older than the newest {keep_recent} in {repo}")
            )
        else:
            repo = min(_repos_of(image.repo_tags))
            candidates.append(_candidate(image, repo, "unused (retention disabled)"))

    return PrunePreview(
        candidates=candidates,
        retained=retained,
        estimated_bytes=sum(candidate.size_bytes for candidate in candidates),
        mode=mode,
        keep_recent=keep_recent,
    )


async def _prune_agent_hosts(
    config: DockwatchConfig,
    *,
    mode: str,
    keep_recent: int,
    store: ManifestStore | None,
) -> PruneResult:
    """Prune every enabled agent host, at the host level.

    The central cannot enumerate a remote host's images, so agent pruning is
    delegated wholesale: each agent runs its own ``plan_prune`` + ``execute_prune``
    against its own daemon via the agent prune endpoint, and the central records
    one audit row per host (success or failure). ``mode``/``keep_recent`` are the
    *resolved* values, so a caller's explicit override reaches every agent rather
    than each agent silently applying its configured defaults.
    """
    removed: list[str] = []
    failed: list[tuple[str, str]] = []
    reclaimed_bytes = 0

    for agent in [a for a in config.agents if a.enabled]:
        try:
            client = AgentClient(base_url=agent.url, token=agent.token)
            result = await client.prune_images(mode=mode, keep_recent=keep_recent)
        except AgentError as exc:
            failed.append((agent.name, str(exc)))
            if store is not None:
                store.record_update_event(
                    container_name=PRUNE_CONTAINER_NAME,
                    action="prune_images",
                    source="agent",
                    status="failed",
                    error=str(exc),
                    username=PRUNE_USERNAME,
                    environment_id=agent.name,
                )
            continue

        host_removed = list(result.get("removed", []) or [])
        host_failed = list(result.get("failed", []) or [])
        host_reclaimed = int(result.get("reclaimed_bytes", 0) or 0)
        removed.extend(host_removed)
        failed.extend((image_id, error) for image_id, error in host_failed)
        reclaimed_bytes += host_reclaimed

        if store is not None:
            store.record_update_event(
                container_name=PRUNE_CONTAINER_NAME,
                action="prune_images",
                source="agent",
                status="success",
                username=PRUNE_USERNAME,
                environment_id=agent.name,
                new_tag=f"removed {len(host_removed)} image(s)",
            )

    return PruneResult(removed=removed, failed=failed, reclaimed_bytes=reclaimed_bytes)


async def _remove_candidate(
    candidate: PruneCandidate,
    *,
    source: str,
    config: DockwatchConfig,
) -> tuple[bool, str | None]:
    try:
        if source == "local":
            await asyncio.to_thread(docker_client.remove_image, candidate.image_id)
            return True, None
        if source == "portainer":
            return False, "portainer image pruning is not supported (its prune proxy cannot honour keep-N)"
        return False, f"unsupported prune source '{source}'"
    except Exception as exc:  # noqa: BLE001 -- one failed removal must not abort the rest
        return False, str(exc)


async def _remove_candidates(
    preview: PrunePreview,
    *,
    config: DockwatchConfig,
    store: ManifestStore | None,
    source: str,
) -> PruneResult:
    """Remove each candidate individually, auditing as it goes.

    Never calls ``docker.images.prune`` (which cannot honour the retention
    guard) and never forces a removal. A failure on one image is recorded in
    ``failed`` and does not abort the remaining removals; ``reclaimed_bytes``
    accumulates only images actually removed.
    """
    removed: list[str] = []
    failed: list[tuple[str, str]] = []
    reclaimed_bytes = 0

    for candidate in preview.candidates:
        success, error = await _remove_candidate(candidate, source=source, config=config)
        if success:
            removed.append(candidate.image_id)
            reclaimed_bytes += candidate.size_bytes
        else:
            failed.append((candidate.image_id, error))

        if store is not None:
            store.record_update_event(
                container_name=PRUNE_CONTAINER_NAME,
                action="prune_images",
                source=source,
                status="success" if success else "failed",
                error=error if not success else None,
                username=PRUNE_USERNAME,
                old_digest=candidate.image_id,
                new_tag=candidate.repo_tags[0] if candidate.repo_tags else "<none>",
            )

    return PruneResult(removed=removed, failed=failed, reclaimed_bytes=reclaimed_bytes)


async def _send_prune_notification(result: PruneResult, config: DockwatchConfig) -> None:
    """Emit the single prune summary notification for ``result`` (no-op when disabled)."""
    if not config.prune.notify:
        return
    severity = "warning" if result.failed else "info"
    event = NotificationEvent(
        kind="prune",
        title="Image pruning complete",
        message=(
            f"Removed {len(result.removed)} image(s), reclaimed {result.reclaimed_bytes} bytes"
            + (f"; {len(result.failed)} removal(s) failed" if result.failed else "")
        ),
        fields={
            "removed": str(len(result.removed)),
            "reclaimed_bytes": str(result.reclaimed_bytes),
            "failed": str(len(result.failed)),
        },
        severity=severity,
    )
    for error in await send_configured_events([event], config):
        logger.warning("Prune notifier error: %s", error)


async def execute_prune(
    preview: PrunePreview,
    *,
    config: DockwatchConfig,
    store: ManifestStore | None = None,
    source: str = "local",
) -> PruneResult:
    """Remove each candidate individually, auditing and notifying as it goes.

    ``source`` is ``"local"`` (remove from this daemon) or ``"portainer"``
    (unsupported, reported per-image). Agent hosts are pruned by
    :func:`prune_all`, which delegates a full prune to each enabled agent and
    emits one combined notification.

    Never calls ``docker.images.prune`` (which cannot honour the retention
    guard) and never forces a removal. A failure on one image is recorded in
    ``failed`` and does not abort the remaining removals; ``reclaimed_bytes``
    accumulates only images actually removed.
    """
    result = await _remove_candidates(preview, config=config, store=store, source=source)
    await _send_prune_notification(result, config)
    return result


async def prune_all(
    config: DockwatchConfig,
    *,
    mode: str,
    keep_recent: int,
    store: ManifestStore | None = None,
    broadcast: Callable[[str, dict], Awaitable[None]] | None = None,
) -> PruneResult:
    """Prune the local daemon and every enabled agent host in one pass.

    Lists local images, plans with the resolved ``mode``/``keep_recent``,
    removes local candidates, delegates a full prune to each agent host with the
    same resolved values, combines the results, emits one combined notification,
    and returns the combined result. ``broadcast``, when given, receives
    ``prune_started`` before any work and a balanced ``prune_complete``
    afterwards (including on a listing failure, which is then re-raised).
    """
    if broadcast is not None:
        await broadcast("prune_started", {})

    try:
        images = await asyncio.to_thread(docker_client.list_images)
        in_use_ids = await asyncio.to_thread(docker_client.in_use_image_ids)
    except Exception as exc:
        if broadcast is not None:
            await broadcast(
                "prune_complete",
                {"error": str(exc), "removed": [], "failed": [], "reclaimed_bytes": 0},
            )
        raise

    preview = plan_prune(images, in_use_ids, mode=mode, keep_recent=keep_recent)
    local_result = await _remove_candidates(preview, config=config, store=store, source="local")
    agent_result = await _prune_agent_hosts(config, mode=mode, keep_recent=keep_recent, store=store)

    combined = PruneResult(
        removed=local_result.removed + agent_result.removed,
        failed=local_result.failed + agent_result.failed,
        reclaimed_bytes=local_result.reclaimed_bytes + agent_result.reclaimed_bytes,
    )

    await _send_prune_notification(combined, config)

    if broadcast is not None:
        await broadcast(
            "prune_complete",
            {
                "removed": combined.removed,
                "failed": combined.failed,
                "reclaimed_bytes": combined.reclaimed_bytes,
            },
        )

    return combined


class PruneScheduler:
    """Background image-pruning loop mirroring :class:`HealthMonitor`."""

    def __init__(
        self,
        *,
        config: DockwatchConfig,
        store: ManifestStore,
        emit: Callable[[str], None] | None = None,
        broadcast: Callable[[str, dict], Awaitable[None]] | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.emit = emit or (lambda _message: None)
        self.broadcast = broadcast
        self._run_lock = asyncio.Lock()

    def next_delay(self) -> float:
        return float(self.config.prune.interval_hours) * 3600 + random.uniform(
            0, self.config.schedule_jitter_seconds
        )

    async def run_once(self, *, force: bool = False) -> bool:
        """Run one prune cycle.

        Returns ``True`` when the cycle completed (or was skipped because the
        feature is disabled) and ``False`` when it was skipped because a
        previous run was still in progress.

        When ``config.prune.enabled`` is False the scheduler is inert: it emits
        a message and returns without listing images, removing anything, or
        writing audit rows. ``force=True`` bypasses that guard for a deliberate
        manual one-shot while the background feature is off.
        """
        if not self.config.prune.enabled and not force:
            self.emit("Image pruning is disabled; skipping run.")
            return True

        if self._run_lock.locked():
            self.emit("Skipped prune run: previous run still in progress.")
            return False

        async with self._run_lock:
            try:
                result = await prune_all(
                    self.config,
                    mode=self.config.prune.mode,
                    keep_recent=self.config.prune.keep_recent_per_repository,
                    store=self.store,
                    broadcast=self.broadcast,
                )
            except Exception as exc:  # noqa: BLE001 -- a listing failure must not crash serve_forever
                self.emit(f"Prune failed: {exc}")
                return True

            self.emit(
                f"Prune complete: removed {len(result.removed)} image(s), "
                f"{len(result.failed)} failed."
            )
            return True

    async def serve_forever(self) -> None:
        if self.config.prune.run_on_startup:
            await self.run_once()

        while True:
            await asyncio.sleep(self.next_delay())
            await self.run_once()
