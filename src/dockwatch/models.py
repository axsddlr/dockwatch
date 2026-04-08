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


@dataclass(slots=True)
class UpdateResult:
    container_info: ContainerInfo
    latest_tag: str | None = None
    is_outdated: bool | None = None
    check_error: str | None = None
    status: str | None = None
    event: str | None = None
