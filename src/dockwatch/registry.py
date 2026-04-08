"""Registry checkers for Docker Hub, GHCR, and lscr.io."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable

import httpx
from packaging.version import InvalidVersion, Version

from .config import DockwatchConfig, load_config
from .db import ManifestStore
from .docker_client import DIGEST_PINNED_TAG
from .models import ContainerInfo, RegistryType, UpdateResult

FLOATING_TAGS = {"latest", "edge", "dev", "nightly"}
# Multi-arch manifest types listed first so registries return manifest list digests
# (matching what Docker stores in RepoDigests for multi-arch images)
MANIFEST_ACCEPT_HEADERS = ", ".join([
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
])
LINUXSERVER_SUFFIX_RE = re.compile(r"(?i)-ls(\d+)$")
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def _skip_result(info: ContainerInfo, reason: str) -> UpdateResult:
    return UpdateResult(
        container_info=info,
        latest_tag=None,
        is_outdated=None,
        check_error=reason,
        status="UNKNOWN",
        event=None,
    )


def _normalize_tag(tag: str) -> str:
    return tag.strip()


def _compile_tag_patterns(patterns: list[str]) -> tuple[list[re.Pattern[str]], str | None]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            return [], f"invalid tag regex '{pattern}': {exc}"
    return compiled, None


def _filter_tags(
    tags: list[str],
    *,
    include_patterns: list[re.Pattern[str]],
    exclude_patterns: list[re.Pattern[str]],
) -> list[str]:
    filtered = [_normalize_tag(tag) for tag in tags if isinstance(tag, str) and tag.strip()]
    if include_patterns:
        filtered = [
            tag for tag in filtered if any(pattern.search(tag) for pattern in include_patterns)
        ]
    if exclude_patterns:
        filtered = [
            tag for tag in filtered if not any(pattern.search(tag) for pattern in exclude_patterns)
        ]
    return filtered


def _safe_version(tag: str) -> Version | None:
    normalized = _normalize_tag(tag).lstrip("v")
    normalized = LINUXSERVER_SUFFIX_RE.sub(r".post\1", normalized)
    try:
        return Version(normalized)
    except InvalidVersion:
        return None


def _effective_current_version_text(info: ContainerInfo) -> str:
    if info.current_tag.lower() != "latest":
        return info.current_tag
    return info.version_label or info.labels.get("build_version") or info.current_tag


def _effective_current_digest(info: ContainerInfo) -> str | None:
    candidate = info.repo_digest or info.compose_image_digest
    if not candidate:
        return None
    return candidate.split("@", 1)[1] if "@" in candidate else candidate


async def _request_with_retry(
    request: Callable[[], Awaitable[httpx.Response]],
    *,
    attempts: int = 3,
    initial_delay: float = 0.25,
) -> httpx.Response:
    delay = initial_delay
    for attempt in range(1, attempts + 1):
        try:
            response = await request()
            if response.status_code in RETRYABLE_STATUSES and attempt < attempts:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            return response
        except httpx.RequestError:
            if attempt >= attempts:
                raise
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError("request retry loop exhausted")


def _select_latest_from_tags(
    tags: list[str],
    *,
    include_patterns: list[re.Pattern[str]] | None = None,
    exclude_patterns: list[re.Pattern[str]] | None = None,
) -> str | None:
    normalized = _filter_tags(
        tags,
        include_patterns=include_patterns or [],
        exclude_patterns=exclude_patterns or [],
    )
    if not normalized:
        return None

    semver_candidates: list[tuple[Version, str]] = []
    for tag in normalized:
        lowered = tag.lower()
        if lowered in FLOATING_TAGS:
            continue
        parsed = _safe_version(tag)
        if parsed is not None:
            semver_candidates.append((parsed, tag))

    if semver_candidates:
        semver_candidates.sort(key=lambda item: item[0], reverse=True)
        return semver_candidates[0][1]

    for tag in normalized:
        if tag.lower() not in FLOATING_TAGS:
            return tag

    return normalized[0]


def _compare_tags(info: ContainerInfo, latest_tag: str | None, remote_digest: str | None = None) -> bool | None:
    if latest_tag is None:
        return None

    current_digest = _effective_current_digest(info)
    if current_digest and remote_digest:
        return current_digest != remote_digest

    current_version = _safe_version(_effective_current_version_text(info))
    latest_version = _safe_version(latest_tag)
    if current_version is not None and latest_version is not None:
        return latest_version > current_version

    return latest_tag != info.current_tag


async def _fetch_manifest_digest(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    namespace: str,
    image_name: str,
    tag: str,
    headers: dict[str, str] | None = None,
) -> str | None:
    response = await _request_with_retry(
        lambda: client.head(
            f"{base_url}/v2/{namespace}/{image_name}/manifests/{tag}",
            headers={
                "Accept": MANIFEST_ACCEPT_HEADERS,
                **(headers or {}),
            },
        )
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.headers.get("Docker-Content-Digest")


def _record_event(
    store: ManifestStore | None,
    info: ContainerInfo,
    *,
    latest_tag: str | None,
    remote_digest: str | None,
) -> str | None:
    if store is None:
        return None
    return store.record_observation(
        info,
        latest_tag=latest_tag,
        remote_digest=remote_digest,
    )


def _resolve_tag_filters(config: DockwatchConfig) -> tuple[list[re.Pattern[str]], list[re.Pattern[str]], str | None]:
    include_patterns, include_error = _compile_tag_patterns(config.include_tags)
    if include_error:
        return [], [], include_error
    exclude_patterns, exclude_error = _compile_tag_patterns(config.exclude_tags)
    if exclude_error:
        return [], [], exclude_error
    return include_patterns, exclude_patterns, None


def _resolve_effective_tag_filters(
    info: ContainerInfo,
    config: DockwatchConfig,
) -> tuple[list[re.Pattern[str]], list[re.Pattern[str]], str | None]:
    effective_config = DockwatchConfig(
        pinned=config.pinned,
        ignored=config.ignored,
        notify_only=config.notify_only,
        include_tags=info.include_tags_override if info.include_tags_override is not None else config.include_tags,
        exclude_tags=info.exclude_tags_override if info.exclude_tags_override is not None else config.exclude_tags,
        notify_on=config.notify_on,
        first_check_notify=config.first_check_notify,
        webhook_url=config.webhook_url,
        discord_webhook=config.discord_webhook,
        ntfy_url=config.ntfy_url,
        schedule_interval_seconds=config.schedule_interval_seconds,
        schedule_jitter_seconds=config.schedule_jitter_seconds,
        run_on_startup=config.run_on_startup,
        max_concurrent_checks=config.max_concurrent_checks,
    )
    return _resolve_tag_filters(effective_config)


async def check_dockerhub(
    info: ContainerInfo,
    store: ManifestStore | None = None,
    config: DockwatchConfig | None = None,
    client: httpx.AsyncClient | None = None,
) -> UpdateResult:
    if not info.namespace or not info.image_name:
        return _skip_result(info, "invalid image reference for Docker Hub")
    resolved_config = config or load_config()
    include_patterns, exclude_patterns, pattern_error = _resolve_effective_tag_filters(info, resolved_config)
    if pattern_error:
        return _skip_result(info, pattern_error)

    base_url = "https://registry-1.docker.io"
    token_url = (
        f"https://auth.docker.io/token"
        f"?service=registry.docker.io"
        f"&scope=repository:{info.namespace}/{info.image_name}:pull"
    )

    async def _run(client: httpx.AsyncClient) -> UpdateResult:
        token_response = await _request_with_retry(lambda: client.get(token_url))
        if token_response.status_code == 404:
            return _skip_result(info, "docker hub image not found")
        token_response.raise_for_status()
        token_payload = token_response.json()
        token = token_payload.get("token") if isinstance(token_payload, dict) else None
        if not token:
            return _skip_result(info, "docker hub token response missing token")

        auth_headers = {"Authorization": f"Bearer {token}"}

        tags_response = await _request_with_retry(
            lambda: client.get(
                f"{base_url}/v2/{info.namespace}/{info.image_name}/tags/list",
                headers=auth_headers,
            )
        )
        if tags_response.status_code == 404:
            return _skip_result(info, "docker hub image not found")
        tags_response.raise_for_status()
        tags_payload = tags_response.json()
        tags = tags_payload.get("tags", []) if isinstance(tags_payload, dict) else []
        latest_tag = _select_latest_from_tags(
            tags,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
        if not latest_tag:
            return UpdateResult(
                container_info=info,
                latest_tag=None,
                is_outdated=None,
                check_error="no tags matched configured tag filters",
                status="UNKNOWN",
                event=None,
            )
        remote_digest = await _fetch_manifest_digest(
            client,
            base_url=base_url,
            namespace=info.namespace,
            image_name=info.image_name,
            tag=latest_tag,
            headers=auth_headers,
        )
        return UpdateResult(
            container_info=info,
            latest_tag=latest_tag,
            is_outdated=_compare_tags(info, latest_tag, remote_digest),
            check_error=None,
            status=None,
            event=_record_event(store, info, latest_tag=latest_tag, remote_digest=remote_digest),
        )

    try:
        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(timeout=15.0) as session:
            return await _run(session)
    except httpx.HTTPError as exc:
        return _skip_result(info, f"docker hub check failed: {exc}")


async def check_lscr(
    info: ContainerInfo,
    store: ManifestStore | None = None,
    config: DockwatchConfig | None = None,
    client: httpx.AsyncClient | None = None,
) -> UpdateResult:
    if not info.namespace or not info.image_name:
        return _skip_result(info, "invalid image reference for lscr")
    resolved_config = config or load_config()
    include_patterns, exclude_patterns, pattern_error = _resolve_effective_tag_filters(info, resolved_config)
    if pattern_error:
        return _skip_result(info, pattern_error)

    base_url = "https://lscr.io"
    tags_url = f"{base_url}/v2/{info.namespace}/{info.image_name}/tags/list"

    async def _run(client: httpx.AsyncClient) -> UpdateResult:
        tags_response = await _request_with_retry(lambda: client.get(tags_url))
        if tags_response.status_code == 404:
            return _skip_result(info, "lscr image not found")
        tags_response.raise_for_status()
        tags_payload = tags_response.json()
        tags = tags_payload.get("tags", []) if isinstance(tags_payload, dict) else []
        latest_tag = _select_latest_from_tags(
            tags,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
        if not latest_tag:
            return UpdateResult(
                container_info=info,
                latest_tag=None,
                is_outdated=None,
                check_error="no tags matched configured tag filters",
                status="UNKNOWN",
                event=None,
            )
        remote_digest = await _fetch_manifest_digest(
            client,
            base_url=base_url,
            namespace=info.namespace,
            image_name=info.image_name,
            tag=latest_tag,
        )
        return UpdateResult(
            container_info=info,
            latest_tag=latest_tag,
            is_outdated=_compare_tags(info, latest_tag, remote_digest),
            check_error=None,
            status=None,
            event=_record_event(store, info, latest_tag=latest_tag, remote_digest=remote_digest),
        )

    try:
        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(timeout=15.0) as session:
            return await _run(session)
    except httpx.HTTPError as exc:
        return _skip_result(info, f"lscr check failed: {exc}")


async def check_ghcr(
    info: ContainerInfo,
    store: ManifestStore | None = None,
    config: DockwatchConfig | None = None,
    client: httpx.AsyncClient | None = None,
) -> UpdateResult:
    if not info.namespace or not info.image_name:
        return _skip_result(info, "invalid image reference for ghcr")
    resolved_config = config or load_config()
    include_patterns, exclude_patterns, pattern_error = _resolve_effective_tag_filters(info, resolved_config)
    if pattern_error:
        return _skip_result(info, pattern_error)

    token_url = f"https://ghcr.io/token?scope=repository:{info.namespace}/{info.image_name}:pull"
    tags_url = f"https://ghcr.io/v2/{info.namespace}/{info.image_name}/tags/list"

    async def _run(client: httpx.AsyncClient) -> UpdateResult:
        token_response = await _request_with_retry(lambda: client.get(token_url))
        if token_response.status_code == 404:
            return _skip_result(info, "ghcr repository not found")
        token_response.raise_for_status()
        token_payload = token_response.json()
        token = token_payload.get("token") if isinstance(token_payload, dict) else None
        if not token:
            return _skip_result(info, "ghcr token response missing token")

        tags_response = await _request_with_retry(
            lambda: client.get(tags_url, headers={"Authorization": f"Bearer {token}"})
        )
        if tags_response.status_code == 404:
            return _skip_result(info, "ghcr repository not found")
        tags_response.raise_for_status()
        tags_payload = tags_response.json()
        tags = tags_payload.get("tags", []) if isinstance(tags_payload, dict) else []
        latest_tag = _select_latest_from_tags(
            tags,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
        if not latest_tag:
            return UpdateResult(
                container_info=info,
                latest_tag=None,
                is_outdated=None,
                check_error="no tags matched configured tag filters",
                status="UNKNOWN",
                event=None,
            )
        remote_digest = await _fetch_manifest_digest(
            client,
            base_url="https://ghcr.io",
            namespace=info.namespace,
            image_name=info.image_name,
            tag=latest_tag,
            headers={"Authorization": f"Bearer {token}"},
        )
        return UpdateResult(
            container_info=info,
            latest_tag=latest_tag,
            is_outdated=_compare_tags(info, latest_tag, remote_digest),
            check_error=None,
            status=None,
            event=_record_event(store, info, latest_tag=latest_tag, remote_digest=remote_digest),
        )

    try:
        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(timeout=15.0) as session:
            return await _run(session)
    except httpx.HTTPError as exc:
        return _skip_result(info, f"ghcr check failed: {exc}")


async def check_container(
    info: ContainerInfo,
    store: ManifestStore | None = None,
    config: DockwatchConfig | None = None,
    client: httpx.AsyncClient | None = None,
) -> UpdateResult:
    lowered = info.current_tag.lower()
    if lowered == DIGEST_PINNED_TAG.lower():
        return _skip_result(info, "skipped digest-pinned image")

    if info.registry == RegistryType.DOCKERHUB:
        return await check_dockerhub(info, store, config, client=client)
    if info.registry == RegistryType.LSCR:
        return await check_lscr(info, store, config, client=client)
    if info.registry == RegistryType.GHCR:
        return await check_ghcr(info, store, config, client=client)

    return _skip_result(info, "unsupported registry")


def _is_effectively_ignored(info: ContainerInfo, ignored: set[str]) -> bool:
    if info.watch_enabled is False:
        return True
    if info.ignored_override is not None:
        return info.ignored_override
    if info.watch_enabled is True:
        return False
    return info.name in ignored


def _is_effectively_pinned(info: ContainerInfo, pinned: set[str]) -> bool:
    if info.pinned_override is not None:
        return info.pinned_override
    return info.name in pinned


async def check_all(
    containers: list[ContainerInfo],
    config: DockwatchConfig | None = None,
    *,
    store: ManifestStore | None = None,
    max_concurrency: int | None = None,
) -> list[UpdateResult]:
    resolved_config = config or load_config()
    ignored = set(resolved_config.ignored)
    pinned = set(resolved_config.pinned)

    precomputed: list[UpdateResult] = []
    check_targets: list[ContainerInfo] = []
    for container in containers:
        if _is_effectively_ignored(container, ignored):
            continue
        if _is_effectively_pinned(container, pinned):
            precomputed.append(
                UpdateResult(
                    container_info=container,
                    latest_tag=None,
                    is_outdated=None,
                    check_error=None,
                    status="PINNED",
                    event=None,
                )
            )
            continue
        check_targets.append(container)

    concurrency = max(1, max_concurrency or resolved_config.max_concurrent_checks)
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_check(container: ContainerInfo, client: httpx.AsyncClient) -> UpdateResult:
        async with semaphore:
            try:
                return await check_container(container, store, resolved_config, client=client)
            except Exception as exc:  # noqa: BLE001
                return _skip_result(container, f"container check failed: {exc}")

    if not check_targets:
        return precomputed

    async with httpx.AsyncClient(timeout=15.0) as client:
        checked = await asyncio.gather(*[_run_check(container, client) for container in check_targets])
    return [*precomputed, *checked]
