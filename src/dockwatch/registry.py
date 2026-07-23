"""Registry checkers for Docker Hub, GHCR, Codeberg, and lscr.io."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from packaging.version import InvalidVersion, Version

from .config import DockwatchConfig, load_config
from .db import ManifestStore
from .docker_client import DIGEST_PINNED_TAG
from .models import (
    ContainerInfo,
    RegistryType,
    UpdateResult,
    deployed_digest,
    deployed_display,
    deployed_version_hint,
)
from .semver import compare_versions, parse_version

logger = logging.getLogger(__name__)

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
ARCH_TAG_RE = re.compile(r"(?i)[-_.](arm64|amd64|aarch64|armv?\d*|armhf|x86[-_]64|i386|s390x|ppc64le)$")
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_BEARER_KV_RE = re.compile(r'(\w+)="([^"]*)"')


def _skip_result(info: ContainerInfo, reason: str) -> UpdateResult:
    return UpdateResult(
        container_info=info,
        latest_tag=None,
        is_outdated=None,
        check_error=reason,
        status="UNKNOWN",
        event=None,
        deployed_tag=info.current_tag,
        deployed_version=deployed_version_hint(info),
        deployed_digest=deployed_digest(info),
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
    ls_normalized = LINUXSERVER_SUFFIX_RE.sub(r".post\1", normalized)
    try:
        return Version(ls_normalized)
    except InvalidVersion:
        pass
    # Not a linuxserver-style "-lsNN" suffix (e.g. "-alpine", "-slim",
    # "-bookworm"): fall back to semver's more lenient normalizer instead
    # of giving up, so distro-suffixed tags still get a comparable version
    # rather than silently degrading is_outdated to UNKNOWN.
    return parse_version(tag)


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
    current_tag: str | None = None,
) -> str | None:
    normalized = _filter_tags(
        tags,
        include_patterns=include_patterns or [],
        exclude_patterns=exclude_patterns or [],
    )
    if not normalized:
        return None

    current_parsed = _safe_version(current_tag) if current_tag else None
    allow_prerelease = current_parsed is not None and current_parsed.is_prerelease

    semver_candidates: list[tuple[Version, str]] = []
    for tag in normalized:
        lowered = tag.lower()
        if lowered in FLOATING_TAGS:
            continue
        parsed = _safe_version(tag)
        if parsed is not None:
            # Stable-track deployments should not be offered rc/beta/dev tags.
            if parsed.is_prerelease and not allow_prerelease:
                continue
            semver_candidates.append((parsed, tag))

    if semver_candidates:
        semver_candidates.sort(key=lambda item: item[0], reverse=True)
        return semver_candidates[0][1]

    # Prefer non-floating tags without an arch suffix; arch-specific tags are
    # per-platform aliases, not release candidates.
    for tag in normalized:
        if tag.lower() not in FLOATING_TAGS and not ARCH_TAG_RE.search(tag):
            return tag

    for tag in normalized:
        if tag.lower() not in FLOATING_TAGS:
            return tag

    return normalized[0]


def _build_comparison_result(
    info: ContainerInfo,
    *,
    latest_tag: str | None,
    remote_tag: str | None,
    remote_digest: str | None,
    event: str | None,
    check_error: str | None = None,
    status: str | None = None,
) -> UpdateResult:
    local_digest = deployed_digest(info)
    local_version = deployed_version_hint(info)
    deployed_version = local_version or (_normalize_tag(info.current_tag) if _safe_version(info.current_tag) else None)
    latest_version = latest_tag if latest_tag and _safe_version(latest_tag) is not None else None
    comparison_basis: str | None = None
    comparison_reason: str | None = None
    is_outdated: bool | None = None
    version_status: str | None = None
    version_diff = None
    effective_remote_tag = remote_tag or latest_tag

    if deployed_version is not None and latest_version is not None:
        version_diff = compare_versions(deployed_version, latest_version)
        deployed_parsed = _safe_version(deployed_version)
        latest_parsed = _safe_version(latest_version)
        if deployed_parsed is not None and latest_parsed is not None:
            if latest_parsed > deployed_parsed:
                version_status = "behind"
            elif latest_parsed < deployed_parsed:
                version_status = "ahead"
            else:
                version_status = "equal"

    if latest_tag is not None:
        if local_digest and remote_digest:
            comparison_basis = "digest"
            is_outdated = local_digest != remote_digest
            if is_outdated:
                if effective_remote_tag == info.current_tag:
                    comparison_reason = "digest changed behind same tag"
                else:
                    if latest_version and deployed_version:
                        comparison_reason = (
                            f"registry digest differs for {effective_remote_tag} "
                            f"({deployed_version} -> {latest_version})"
                        )
                    else:
                        comparison_reason = f"registry digest differs for {effective_remote_tag}"
            else:
                if latest_version and deployed_version and latest_version == deployed_version:
                    comparison_reason = f"digest matches ({deployed_version})"
                else:
                    comparison_reason = "digest matches"
        else:
            current_version = _safe_version(deployed_version or "")
            latest_parsed = _safe_version(latest_tag)
            if current_version is not None and latest_parsed is not None:
                comparison_basis = "version"
                is_outdated = latest_parsed > current_version
                if is_outdated:
                    comparison_reason = (
                        f"remote version {latest_tag} is newer than deployed "
                        f"{deployed_version or deployed_display(info)}"
                    )
                else:
                    comparison_reason = "version matches latest candidate"
            else:
                comparison_basis = "tag"
                if effective_remote_tag == info.current_tag:
                    is_outdated = False
                    comparison_reason = "tag matches latest candidate"
                else:
                    # A bare string difference proves nothing without a digest
                    # or parseable versions; report UNKNOWN instead of a
                    # perma-outdated container.
                    is_outdated = None
                    comparison_reason = (
                        f"cannot compare deployed tag {info.current_tag} with remote "
                        f"candidate {effective_remote_tag}; no digest or version information"
                    )

    return UpdateResult(
        container_info=info,
        latest_tag=latest_tag,
        is_outdated=is_outdated,
        check_error=check_error,
        status=status,
        event=event,
        deployed_tag=info.current_tag,
        deployed_version=deployed_version,
        deployed_digest=local_digest,
        remote_tag=effective_remote_tag,
        remote_digest=remote_digest,
        latest_version=latest_version,
        comparison_basis=comparison_basis,
        comparison_reason=comparison_reason,
        version_status=version_status,
        version_diff=version_diff,
    )


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


def _parse_bearer_challenge(header: str | None) -> dict[str, str] | None:
    if not header:
        return None
    scheme, _, params = header.partition(" ")
    if scheme.lower() != "bearer" or not params.strip():
        return None
    parsed = {key: value for key, value in _BEARER_KV_RE.findall(params)}
    if "realm" not in parsed:
        return None
    return parsed


def _build_token_url(challenge: dict[str, str]) -> str:
    realm = challenge["realm"]
    parsed = urlparse(realm)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in ("service", "scope"):
        if challenge.get(key):
            existing[key] = challenge[key]
    return urlunparse(parsed._replace(query=urlencode(existing)))


async def _resolve_bearer_headers(
    client: httpx.AsyncClient,
    response: httpx.Response,
) -> dict[str, str] | None:
    challenge = _parse_bearer_challenge(response.headers.get("Www-Authenticate"))
    if challenge is None:
        return None
    token_response = await _request_with_retry(lambda: client.get(_build_token_url(challenge)))
    token_response.raise_for_status()
    token_payload = token_response.json()
    token = token_payload.get("token") if isinstance(token_payload, dict) else None
    if not token:
        raise httpx.HTTPError("registry token response missing token", request=token_response.request)
    return {"Authorization": f"Bearer {token}"}


async def _check_repository_tags(
    client: httpx.AsyncClient,
    *,
    info: ContainerInfo,
    store: ManifestStore | None,
    base_url: str,
    tags_url: str,
    not_found_reason: str,
    error_prefix: str,
    include_patterns: list[re.Pattern[str]],
    exclude_patterns: list[re.Pattern[str]],
    headers: dict[str, str] | None = None,
) -> UpdateResult:
    all_tags: list[str] = []
    _first_url = tags_url
    if "?" not in _first_url:
        _first_url = f"{_first_url}?n=100"
    next_url: str | None = _first_url
    _MAX_PAGES = 50
    _MAX_TAGS = 25000

    for _page in range(_MAX_PAGES):
        tags_response = await _request_with_retry(lambda: client.get(next_url, headers=headers))
        if tags_response.status_code == 404:
            return _skip_result(info, not_found_reason)
        tags_response.raise_for_status()
        tags_payload = tags_response.json()
        page_tags = tags_payload.get("tags", []) if isinstance(tags_payload, dict) else []
        all_tags.extend(page_tags)

        if len(all_tags) >= _MAX_TAGS:
            break

        link_header = tags_response.headers.get("Link", "")
        next_found = False
        for part in link_header.split(","):
            if 'rel="next"' in part:
                match = re.search(r"<([^>]+)>", part)
                if match:
                    next_url = match.group(1)
                    if next_url.startswith("/"):
                        next_url = f"{base_url}{next_url}"
                    next_found = True
                    break
        if not next_found:
            break

    tags = all_tags
    latest_tag = _select_latest_from_tags(
        tags,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        current_tag=info.current_tag,
    )
    if not latest_tag:
        return _build_comparison_result(
            info,
            latest_tag=None,
            remote_tag=None,
            remote_digest=None,
            event=None,
            check_error="no tags matched configured tag filters",
            status="UNKNOWN",
        )
    # For floating deployments always digest-compare the deployed tag itself:
    # that is what `docker pull` would actually deliver. The best semver tag
    # still travels as latest_tag/latest_version for display.
    comparison_tag = latest_tag
    if info.current_tag.lower() in FLOATING_TAGS and comparison_tag != info.current_tag:
        comparison_tag = info.current_tag

    remote_digest = await _fetch_manifest_digest(
        client,
        base_url=base_url,
        namespace=info.namespace,
        image_name=info.image_name,
        tag=comparison_tag,
        headers=headers,
    )
    return _build_comparison_result(
        info,
        latest_tag=latest_tag,
        remote_tag=comparison_tag,
        remote_digest=remote_digest,
        event=_record_event(store, info, latest_tag=latest_tag, remote_digest=remote_digest),
    )


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
        trivy=config.trivy,
    )
    return _resolve_tag_filters(effective_config)


_DH_REST_TAGS_URL = "https://hub.docker.com/v2/repositories"
_DH_REST_PAGE_SIZE = 100
_DH_REST_MAX_PAGES = 10


async def _fetch_dockerhub_tags_via_rest(
    namespace: str,
    image_name: str,
    client: httpx.AsyncClient,
) -> list[str]:
    all_tags: list[str] = []
    page = 1
    for _ in range(_DH_REST_MAX_PAGES):
        url = (
            f"{_DH_REST_TAGS_URL}/{namespace}/{image_name}/tags"
            f"?page_size={_DH_REST_PAGE_SIZE}&page={page}&ordering=last_updated"
        )
        response = await _request_with_retry(lambda: client.get(url))
        if response.status_code == 404:
            break
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", []) if isinstance(payload, dict) else []
        for item in results:
            if isinstance(item, dict) and "name" in item:
                all_tags.append(item["name"])
        if not payload.get("next"):
            break
        page += 1
    if all_tags:
        logger.debug(
            "REST API fetched %d tags for %s/%s, top 3: %r",
            len(all_tags), namespace, image_name, all_tags[:3],
        )
    return all_tags


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
        tags = await _fetch_dockerhub_tags_via_rest(
            info.namespace, info.image_name, client
        )
        if not tags:
            return _skip_result(info, "docker hub image not found or has no tags")

        latest_tag = _select_latest_from_tags(
            tags,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            current_tag=info.current_tag,
        )
        if not latest_tag:
            return _build_comparison_result(
                info,
                latest_tag=None,
                remote_tag=None,
                remote_digest=None,
                event=None,
                check_error="no tags matched configured tag filters",
                status="UNKNOWN",
            )

        token_response = await _request_with_retry(lambda: client.get(token_url))
        if token_response.status_code == 404:
            return _skip_result(info, "docker hub image not found")
        token_response.raise_for_status()
        token_payload = token_response.json()
        token = token_payload.get("token") if isinstance(token_payload, dict) else None
        if not token:
            return _skip_result(info, "docker hub token response missing token")
        auth_headers = {"Authorization": f"Bearer {token}"}

        comparison_tag = latest_tag
        if info.current_tag.lower() in FLOATING_TAGS and comparison_tag != info.current_tag:
            comparison_tag = info.current_tag

        remote_digest = await _fetch_manifest_digest(
            client,
            base_url=base_url,
            namespace=info.namespace,
            image_name=info.image_name,
            tag=comparison_tag,
            headers=auth_headers,
        )
        return _build_comparison_result(
            info,
            latest_tag=latest_tag,
            remote_tag=comparison_tag,
            remote_digest=remote_digest,
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
        probe = await _request_with_retry(lambda: client.get(tags_url))
        if probe.status_code == 404:
            return _skip_result(info, "lscr image not found")
        headers: dict[str, str] | None = None
        if probe.status_code == 401:
            headers = await _resolve_bearer_headers(client, probe)
        return await _check_repository_tags(
            client,
            info=info,
            store=store,
            base_url=base_url,
            tags_url=tags_url,
            not_found_reason="lscr image not found",
            error_prefix="lscr",
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            headers=headers,
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

        return await _check_repository_tags(
            client,
            info=info,
            store=store,
            base_url="https://ghcr.io",
            tags_url=tags_url,
            not_found_reason="ghcr repository not found",
            error_prefix="ghcr",
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            headers={"Authorization": f"Bearer {token}"},
        )

    try:
        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(timeout=15.0) as session:
            return await _run(session)
    except httpx.HTTPError as exc:
        return _skip_result(info, f"ghcr check failed: {exc}")


async def check_codeberg(
    info: ContainerInfo,
    store: ManifestStore | None = None,
    config: DockwatchConfig | None = None,
    client: httpx.AsyncClient | None = None,
) -> UpdateResult:
    if not info.namespace or not info.image_name:
        return _skip_result(info, "invalid image reference for codeberg")
    resolved_config = config or load_config()
    include_patterns, exclude_patterns, pattern_error = _resolve_effective_tag_filters(info, resolved_config)
    if pattern_error:
        return _skip_result(info, pattern_error)

    base_url = "https://codeberg.org"
    tags_url = f"{base_url}/v2/{info.namespace}/{info.image_name}/tags/list"

    async def _run(client: httpx.AsyncClient) -> UpdateResult:
        probe = await _request_with_retry(lambda: client.get(tags_url))
        if probe.status_code == 404:
            return _skip_result(info, "codeberg repository not found")
        headers: dict[str, str] | None = None
        if probe.status_code == 401:
            headers = await _resolve_bearer_headers(client, probe)
        return await _check_repository_tags(
            client,
            info=info,
            store=store,
            base_url=base_url,
            tags_url=tags_url,
            not_found_reason="codeberg repository not found",
            error_prefix="codeberg",
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            headers=headers,
        )

    try:
        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(timeout=15.0) as session:
            return await _run(session)
    except httpx.HTTPError as exc:
        return _skip_result(info, f"codeberg check failed: {exc}")


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
    if info.registry == RegistryType.CODEBERG:
        return await check_codeberg(info, store, config, client=client)

    if info.registry == RegistryType.UNKNOWN:
        # Locally built images have no registry to check; that is expected,
        # not an error.
        return UpdateResult(
            container_info=info,
            latest_tag=None,
            is_outdated=None,
            check_error=None,
            status="LOCAL",
            event=None,
            deployed_tag=info.current_tag,
            deployed_version=deployed_version_hint(info),
            deployed_digest=deployed_digest(info),
            comparison_reason="locally built image; no registry to check",
        )
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
    ignored = set(store.get_ignored()) if store else set()
    pinned = set(store.get_pinned()) if store else set()

    precomputed: list[UpdateResult] = []
    check_targets: list[ContainerInfo] = []
    for container in containers:
        if _is_effectively_ignored(container, ignored):
            continue
        if _is_effectively_pinned(container, pinned):
            precomputed.append(
                _build_comparison_result(
                    container,
                    latest_tag=None,
                    remote_tag=None,
                    remote_digest=None,
                    event=None,
                    status="PINNED",
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
        checked = await asyncio.gather(
            *[_run_check(container, client) for container in check_targets],
            return_exceptions=True,
        )
    results: list[UpdateResult] = [r for r in checked if isinstance(r, UpdateResult)]
    return [*precomputed, *results]
