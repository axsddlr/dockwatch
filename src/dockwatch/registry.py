"""Registry checkers for Docker Hub and GHCR."""

from __future__ import annotations

import asyncio
import re

import httpx
from packaging.version import InvalidVersion, Version

from .config import DockwatchConfig, load_config
from .docker_client import DIGEST_PINNED_TAG
from .models import ContainerInfo, RegistryType, UpdateResult

FLOATING_TAGS = {"latest", "edge", "dev", "nightly"}
MANIFEST_ACCEPT_HEADER = "application/vnd.docker.distribution.manifest.v2+json"
LINUXSERVER_SUFFIX_RE = re.compile(r"(?i)-ls(\d+)$")


def _skip_result(info: ContainerInfo, reason: str) -> UpdateResult:
    return UpdateResult(
        container_info=info,
        latest_tag=None,
        is_outdated=None,
        check_error=reason,
        status="UNKNOWN",
    )


def _normalize_tag(tag: str) -> str:
    return tag.strip()


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


def _select_latest_from_tags(tags: list[str]) -> str | None:
    normalized = [_normalize_tag(tag) for tag in tags if isinstance(tag, str) and tag.strip()]
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
    response = await client.get(
        f"{base_url}/v2/{namespace}/{image_name}/manifests/{tag}",
        headers={
            "Accept": MANIFEST_ACCEPT_HEADER,
            **(headers or {}),
        },
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.headers.get("Docker-Content-Digest")


async def check_dockerhub(info: ContainerInfo) -> UpdateResult:
    if not info.namespace or not info.image_name:
        return _skip_result(info, "invalid image reference for Docker Hub")

    path = f"library/{info.image_name}" if info.namespace == "library" else f"{info.namespace}/{info.image_name}"
    url = f"https://hub.docker.com/v2/repositories/{path}/tags?page_size=20&ordering=last_updated"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url)
            if response.status_code == 404:
                return _skip_result(info, "docker hub image not found")
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        return _skip_result(info, f"docker hub check failed: {exc}")

    results = payload.get("results", []) if isinstance(payload, dict) else []
    tags = [row.get("name") for row in results if isinstance(row, dict)]
    latest_tag = _select_latest_from_tags(tags)

    return UpdateResult(
        container_info=info,
        latest_tag=latest_tag,
        is_outdated=_compare_tags(info, latest_tag),
        check_error=None if latest_tag else "no tags returned by docker hub",
        status=None if latest_tag else "UNKNOWN",
    )


async def check_lscr(info: ContainerInfo) -> UpdateResult:
    if not info.namespace or not info.image_name:
        return _skip_result(info, "invalid image reference for lscr")

    base_url = "https://lscr.io"
    tags_url = f"{base_url}/v2/{info.namespace}/{info.image_name}/tags/list"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            tags_response = await client.get(tags_url)
            if tags_response.status_code == 404:
                return _skip_result(info, "lscr image not found")
            tags_response.raise_for_status()
            tags_payload = tags_response.json()
            tags = tags_payload.get("tags", []) if isinstance(tags_payload, dict) else []
            latest_tag = _select_latest_from_tags(tags)
            if not latest_tag:
                return UpdateResult(
                    container_info=info,
                    latest_tag=None,
                    is_outdated=None,
                    check_error="no tags returned by lscr",
                    status="UNKNOWN",
                )
            remote_digest = await _fetch_manifest_digest(
                client,
                base_url=base_url,
                namespace=info.namespace,
                image_name=info.image_name,
                tag=latest_tag,
            )
    except httpx.HTTPError as exc:
        return _skip_result(info, f"lscr check failed: {exc}")

    return UpdateResult(
        container_info=info,
        latest_tag=latest_tag,
        is_outdated=_compare_tags(info, latest_tag, remote_digest),
        check_error=None,
        status=None,
    )


async def check_ghcr(info: ContainerInfo) -> UpdateResult:
    if not info.namespace or not info.image_name:
        return _skip_result(info, "invalid image reference for ghcr")

    token_url = f"https://ghcr.io/token?scope=repository:{info.namespace}/{info.image_name}:pull"
    tags_url = f"https://ghcr.io/v2/{info.namespace}/{info.image_name}/tags/list"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_response = await client.get(token_url)
            if token_response.status_code == 404:
                return _skip_result(info, "ghcr repository not found")
            token_response.raise_for_status()
            token_payload = token_response.json()
            token = token_payload.get("token") if isinstance(token_payload, dict) else None
            if not token:
                return _skip_result(info, "ghcr token response missing token")

            tags_response = await client.get(tags_url, headers={"Authorization": f"Bearer {token}"})
            if tags_response.status_code == 404:
                return _skip_result(info, "ghcr repository not found")
            tags_response.raise_for_status()
            tags_payload = tags_response.json()
            tags = tags_payload.get("tags", []) if isinstance(tags_payload, dict) else []
            latest_tag = _select_latest_from_tags(tags)
            if not latest_tag:
                return UpdateResult(
                    container_info=info,
                    latest_tag=None,
                    is_outdated=None,
                    check_error="no tags returned by ghcr",
                    status="UNKNOWN",
                )
            remote_digest = await _fetch_manifest_digest(
                client,
                base_url="https://ghcr.io",
                namespace=info.namespace,
                image_name=info.image_name,
                tag=latest_tag,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        return _skip_result(info, f"ghcr check failed: {exc}")

    return UpdateResult(
        container_info=info,
        latest_tag=latest_tag,
        is_outdated=_compare_tags(info, latest_tag, remote_digest),
        check_error=None,
        status=None,
    )


async def check_container(info: ContainerInfo) -> UpdateResult:
    lowered = info.current_tag.lower()
    if lowered == DIGEST_PINNED_TAG.lower():
        return _skip_result(info, "skipped digest-pinned image")

    if info.registry == RegistryType.DOCKERHUB:
        return await check_dockerhub(info)
    if info.registry == RegistryType.LSCR:
        return await check_lscr(info)
    if info.registry == RegistryType.GHCR:
        return await check_ghcr(info)

    return _skip_result(info, "unsupported registry")


async def check_all(containers: list[ContainerInfo], config: DockwatchConfig | None = None) -> list[UpdateResult]:
    resolved_config = config or load_config()
    ignored = set(resolved_config.ignored)
    pinned = set(resolved_config.pinned)

    precomputed: list[UpdateResult] = []
    check_targets: list[ContainerInfo] = []
    for container in containers:
        name = container.name
        if name in ignored:
            continue
        if name in pinned:
            precomputed.append(
                UpdateResult(
                    container_info=container,
                    latest_tag=None,
                    is_outdated=None,
                    check_error=None,
                    status="PINNED",
                )
            )
            continue
        check_targets.append(container)

    tasks = [check_container(container) for container in check_targets]
    if not tasks:
        return precomputed
    checked = await asyncio.gather(*tasks)
    return [*precomputed, *checked]
