"""Docker client utilities for container discovery and image parsing."""

from __future__ import annotations

import docker
from docker.errors import DockerException

from .models import ContainerInfo, RegistryType

DIGEST_PINNED_TAG = "DIGEST_PINNED"
TRUE_LABEL_VALUES = {"1", "true", "yes", "on"}
FALSE_LABEL_VALUES = {"0", "false", "no", "off"}


class DockerConnectionError(RuntimeError):
    """Raised when the Docker daemon cannot be reached."""


def _parse_label_flag(labels: dict[str, str], key: str) -> bool | None:
    raw_value = labels.get(key)
    if raw_value is None:
        return None
    normalized = str(raw_value).strip().lower()
    if normalized in TRUE_LABEL_VALUES:
        return True
    if normalized in FALSE_LABEL_VALUES:
        return False
    return None


def _parse_label_list(labels: dict[str, str], key: str) -> list[str] | None:
    if key not in labels:
        return None
    raw_value = str(labels.get(key, "")).strip()
    if not raw_value:
        return []
    items: list[str] = []
    for line in raw_value.splitlines():
        for chunk in line.split(";"):
            for item in chunk.split(","):
                items.append(item.strip())
    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _tag_override_kwargs(labels: dict[str, str]) -> dict[str, list[str] | None]:
    return {
        "include_tags_override": _parse_label_list(labels, "dockwatch.include_tags"),
        "exclude_tags_override": _parse_label_list(labels, "dockwatch.exclude_tags"),
    }


def _build_container_info(
    *,
    name: str,
    container_id: str,
    image_ref: str,
    registry: RegistryType,
    namespace: str,
    image_name: str,
    current_tag: str,
    labels: dict[str, str],
    compose_image_digest: str | None,
    repo_digest: str | None,
) -> ContainerInfo:
    return ContainerInfo(
        name=name,
        container_id=container_id,
        image_ref=image_ref,
        registry=registry,
        namespace=namespace,
        image_name=image_name,
        current_tag=current_tag,
        labels=labels,
        version_label=labels.get("org.opencontainers.image.version"),
        compose_image_digest=compose_image_digest,
        repo_digest=repo_digest,
        watch_enabled=_parse_label_flag(labels, "dockwatch.enable"),
        pinned_override=_parse_label_flag(labels, "dockwatch.pin"),
        ignored_override=_parse_label_flag(labels, "dockwatch.ignore"),
        notify_enabled=_parse_label_flag(labels, "dockwatch.notify"),
        compose_project=labels.get("com.docker.compose.project"),
        compose_service=labels.get("com.docker.compose.service"),
        **_tag_override_kwargs(labels),
    )


def _infer_default_registry(
    parts: list[str],
    *,
    repo_digest: str | None,
) -> RegistryType:
    """Infer registry for refs without an explicit host component.

    Single-segment refs like ``dockwatch-local:dev`` are often locally built
    images. If Docker has no repo digest for them, treat them as local/unknown
    instead of assuming Docker Hub.
    """
    if len(parts) == 1 and not repo_digest:
        return RegistryType.UNKNOWN
    return RegistryType.DOCKERHUB


def parse_image_ref(
    image_str: str,
    *,
    name: str = "",
    container_id: str = "",
    labels: dict[str, str] | None = None,
    compose_image_digest: str | None = None,
    repo_digest: str | None = None,
) -> ContainerInfo:
    """Parse an image reference into normalized container metadata."""
    labels = dict(labels or {})
    compose_image_digest = compose_image_digest or labels.get("com.docker.compose.image")
    image_ref = (image_str or "").strip()
    if not image_ref:
        return _build_container_info(
            name=name,
            container_id=container_id,
            image_ref=image_ref,
            registry=RegistryType.UNKNOWN,
            namespace="library",
            image_name="unknown",
            current_tag="latest",
            labels=labels,
            compose_image_digest=compose_image_digest,
            repo_digest=repo_digest,
        )

    repo_part = image_ref
    current_tag = "latest"

    if "@" in image_ref:
        repo_part = image_ref.split("@", 1)[0]
        current_tag = DIGEST_PINNED_TAG
    else:
        last_slash = repo_part.rfind("/")
        last_colon = repo_part.rfind(":")
        if last_colon > last_slash:
            repo_part, current_tag = repo_part.rsplit(":", 1)

    parts = [p for p in repo_part.split("/") if p]
    if not parts:
        return _build_container_info(
            name=name,
            container_id=container_id,
            image_ref=image_ref,
            registry=RegistryType.UNKNOWN,
            namespace="library",
            image_name="unknown",
            current_tag=current_tag,
            labels=labels,
            compose_image_digest=compose_image_digest,
            repo_digest=repo_digest,
        )

    first = parts[0]
    has_explicit_registry = "." in first or ":" in first or first == "localhost"

    registry = _infer_default_registry(parts, repo_digest=repo_digest)
    path_parts = parts

    if has_explicit_registry:
        host = first.lower()
        path_parts = parts[1:]
        if host == "ghcr.io":
            registry = RegistryType.GHCR
        elif host == "lscr.io":
            registry = RegistryType.LSCR
        elif host == "codeberg.org":
            registry = RegistryType.CODEBERG
        elif host in {"docker.io", "index.docker.io", "registry-1.docker.io"}:
            registry = RegistryType.DOCKERHUB
        else:
            registry = RegistryType.UNKNOWN

    if not path_parts:
        return _build_container_info(
            name=name,
            container_id=container_id,
            image_ref=image_ref,
            registry=registry,
            namespace="library",
            image_name="unknown",
            current_tag=current_tag,
            labels=labels,
            compose_image_digest=compose_image_digest,
            repo_digest=repo_digest,
        )

    if len(path_parts) == 1:
        namespace = "library"
        image_name = path_parts[0]
    else:
        namespace = "/".join(path_parts[:-1])
        image_name = path_parts[-1]

    return _build_container_info(
        name=name,
        container_id=container_id,
        image_ref=image_ref,
        registry=registry,
        namespace=namespace,
        image_name=image_name,
        current_tag=current_tag,
        labels=labels,
        compose_image_digest=compose_image_digest,
        repo_digest=repo_digest,
    )


def get_running_containers() -> list[ContainerInfo]:
    """Return Docker containers, including non-running ones, with normalized image metadata."""
    try:
        client = docker.from_env()
        raw_containers = client.containers.list(all=True)
    except DockerException as exc:
        raise DockerConnectionError(
            "Could not connect to Docker. Ensure the Docker daemon is running "
            "and the current user can access the Docker socket."
        ) from exc

    containers: list[ContainerInfo] = []
    for container in raw_containers:
        config = container.attrs.get("Config", {}) or {}
        labels = dict(config.get("Labels", {}) or {})
        image_attrs = getattr(container.image, "attrs", {}) or {}
        repo_digests = image_attrs.get("RepoDigests", []) or []
        repo_digest = repo_digests[0] if repo_digests else None
        image_ref = (
            config.get("Image")
            or getattr(container.image, "tags", [""])[0]
            or ""
        )
        info = parse_image_ref(
            image_ref,
            name=(container.name or ""),
            container_id=(container.id or "")[:12],
            labels=labels,
            compose_image_digest=labels.get("com.docker.compose.image"),
            repo_digest=repo_digest,
        )
        containers.append(info)

    return containers
