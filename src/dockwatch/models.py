"""Core data models for dockwatch."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RegistryType(str, Enum):
    DOCKERHUB = "dockerhub"
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


@dataclass(slots=True)
class UpdateResult:
    container_info: ContainerInfo
    latest_tag: str | None = None
    is_outdated: bool | None = None
    check_error: str | None = None
    status: str | None = None
