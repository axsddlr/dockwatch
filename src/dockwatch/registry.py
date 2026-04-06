"""Registry checkers for Docker Hub and GHCR."""

from __future__ import annotations

import asyncio

import httpx
from packaging.version import InvalidVersion, Version

from .config import DockwatchConfig, load_config
from .docker_client import DIGEST_PINNED_TAG
from .models import ContainerInfo, RegistryType, UpdateResult

FLOATING_TAGS = {"latest", "edge", "dev", "nightly"}


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
    try:
        return Version(tag)
    except InvalidVersion:
        return None


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


def _compare_tags(current_tag: str, latest_tag: str | None) -> bool | None:
    if latest_tag is None:
        return None

    current_version = _safe_version(current_tag)
    latest_version = _safe_version(latest_tag)
    if current_version is not None and latest_version is not None:
        return latest_version > current_version

    return latest_tag != current_tag


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
        is_outdated=_compare_tags(info.current_tag, latest_tag),
        check_error=None if latest_tag else "no tags returned by docker hub",
        status=None if latest_tag else "UNKNOWN",
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
    except httpx.HTTPError as exc:
        return _skip_result(info, f"ghcr check failed: {exc}")

    tags = tags_payload.get("tags", []) if isinstance(tags_payload, dict) else []
    latest_tag = _select_latest_from_tags(tags)

    return UpdateResult(
        container_info=info,
        latest_tag=latest_tag,
        is_outdated=_compare_tags(info.current_tag, latest_tag),
        check_error=None if latest_tag else "no tags returned by ghcr",
        status=None if latest_tag else "UNKNOWN",
    )


async def check_container(info: ContainerInfo) -> UpdateResult:
    lowered = info.current_tag.lower()
    if lowered == DIGEST_PINNED_TAG.lower():
        return _skip_result(info, "skipped digest-pinned image")

    if info.registry == RegistryType.DOCKERHUB:
        return await check_dockerhub(info)
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
