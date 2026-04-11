"""Core data models for dockwatch."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum

from .semver import VersionDiff


class RegistryType(str, Enum):
    DOCKERHUB = "dockerhub"
    LSCR = "lscr"
    GHCR = "ghcr"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ContainerInfo:
    name: str
    container_id: str
    image_ref: str
    registry: RegistryType
    namespace: str
    image_name: str
    current_tag: str
    labels: dict[str, str] = field(default_factory=dict)
    version_label: str | None = None
    compose_image_digest: str | None = None
    repo_digest: str | None = None
    watch_enabled: bool | None = None
    pinned_override: bool | None = None
    ignored_override: bool | None = None
    notify_enabled: bool | None = None
    include_tags_override: list[str] | None = None
    exclude_tags_override: list[str] | None = None
    source: str = "local"
    environment_id: str | None = None
    environment_name: str | None = None


def deployed_version_hint(info: ContainerInfo) -> str | None:
    return info.version_label or info.labels.get("build_version")


def deployed_digest(info: ContainerInfo) -> str | None:
    candidate = info.repo_digest or info.compose_image_digest
    if not candidate:
        return None
    return candidate.split("@", 1)[1] if "@" in candidate else candidate


def _short_digest(digest: str | None) -> str | None:
    if not digest:
        return None
    normalized = digest.split("@", 1)[1] if "@" in digest else digest
    if normalized.startswith("sha256:"):
        return f"sha256:{normalized.removeprefix('sha256:')[:12]}"
    return normalized[:19]


_FLOATING_TAGS = {"latest", "edge", "dev", "nightly"}


def deployed_display(info: ContainerInfo) -> str:
    """Best-effort display of the deployed version from container info alone."""
    if info.current_tag.lower() not in _FLOATING_TAGS:
        return info.current_tag or "-"
    hint = deployed_version_hint(info)
    if hint:
        return f"latest ({hint})"
    short_digest = _short_digest(deployed_digest(info))
    if short_digest:
        return f"latest ({short_digest})"
    return "latest"


@dataclass(slots=True)
class UpdateResult:
    container_info: ContainerInfo
    latest_tag: str | None = None
    latest_version: str | None = None
    is_outdated: bool | None = None
    check_error: str | None = None
    status: str | None = None
    event: str | None = None
    deployed_tag: str | None = None
    deployed_version: str | None = None
    deployed_digest: str | None = None
    remote_tag: str | None = None
    remote_digest: str | None = None
    comparison_basis: str | None = None
    comparison_reason: str | None = None
    version_status: str | None = None
    version_diff: VersionDiff | None = None


def resolved_deployed_version(result: UpdateResult) -> str | None:
    if result.deployed_version:
        return result.deployed_version
    deployed_tag = result.deployed_tag or result.container_info.current_tag
    if deployed_tag and deployed_tag.lower() not in _FLOATING_TAGS:
        return deployed_tag
    return None


def resolved_remote_version(result: UpdateResult) -> str | None:
    if result.latest_version:
        return result.latest_version
    remote_tag = result.remote_tag or result.latest_tag
    if remote_tag and remote_tag.lower() not in _FLOATING_TAGS:
        return remote_tag
    return None


def deployed_display_result(result: UpdateResult) -> str:
    """Richer deployed display using comparison results.

    When digests match the remote tag we can confirm the exact running version,
    e.g. ``latest = 4.13.7``. Falls back to ``deployed_display()`` otherwise.
    """
    info = result.container_info
    if info.current_tag.lower() not in _FLOATING_TAGS:
        return info.current_tag or "-"
    if (
        result.deployed_digest
        and result.remote_digest
        and result.deployed_digest == result.remote_digest
        and result.remote_tag
    ):
        return f"latest = {result.remote_tag}"
    return deployed_display(info)


def remote_display(result: UpdateResult) -> str:
    if result.status == "PINNED":
        return "Pinned by config"
    if result.check_error:
        return result.check_error
    remote_version = resolved_remote_version(result)
    remote_label = remote_version or result.remote_tag or result.latest_tag or "-"
    short_digest = _short_digest(result.remote_digest)
    if short_digest:
        return f"{remote_label} ({short_digest})"
    return remote_label


def comparison_summary(result: UpdateResult) -> str:
    if result.comparison_reason:
        return result.comparison_reason
    if result.comparison_basis:
        return f"comparison by {result.comparison_basis}"
    if result.status == "PINNED" or result.check_error:
        return "-"
    return "no comparison details"
