"""Core data models for dockwatch."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum


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


def deployed_version_hint(info: ContainerInfo) -> str | None:
    return info.version_label or info.labels.get("build_version")


def deployed_digest(info: ContainerInfo) -> str | None:
    candidate = info.repo_digest or info.compose_image_digest
    if not candidate:
        return None
    return candidate.split("@", 1)[1] if "@" in candidate else candidate


def deployed_display(info: ContainerInfo) -> str:
    if info.current_tag.lower() != "latest":
        return info.current_tag or "-"
    hint = deployed_version_hint(info)
    if hint:
        return f"latest ({hint})"
    return info.current_tag or "-"


@dataclass(slots=True)
class UpdateResult:
    container_info: ContainerInfo
    latest_tag: str | None = None
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


def remote_display(result: UpdateResult) -> str:
    if result.status == "PINNED":
        return "Pinned by config"
    if result.check_error:
        return result.check_error
    return result.remote_tag or result.latest_tag or "-"


def comparison_summary(result: UpdateResult) -> str:
    if result.comparison_reason:
        return result.comparison_reason
    if result.comparison_basis:
        return f"comparison by {result.comparison_basis}"
    if result.status == "PINNED" or result.check_error:
        return "-"
    return "no comparison details"
