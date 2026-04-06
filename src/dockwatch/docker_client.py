"""Docker client utilities for container discovery and image parsing."""

from __future__ import annotations

import docker
from docker.errors import DockerException

from .models import ContainerInfo, RegistryType

DIGEST_PINNED_TAG = "DIGEST_PINNED"


class DockerConnectionError(RuntimeError):
    """Raised when the Docker daemon cannot be reached."""


def parse_image_ref(
    image_str: str,
    *,
    name: str = "",
    container_id: str = "",
) -> ContainerInfo:
    """Parse an image reference into normalized container metadata."""
    image_ref = (image_str or "").strip()
    if not image_ref:
        return ContainerInfo(
            name=name,
            container_id=container_id,
            image_ref=image_ref,
            registry=RegistryType.UNKNOWN,
            namespace="library",
            image_name="unknown",
            current_tag="latest",
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
        return ContainerInfo(
            name=name,
            container_id=container_id,
            image_ref=image_ref,
            registry=RegistryType.UNKNOWN,
            namespace="library",
            image_name="unknown",
            current_tag=current_tag,
        )

    first = parts[0]
    has_explicit_registry = "." in first or ":" in first or first == "localhost"

    registry = RegistryType.DOCKERHUB
    path_parts = parts

    if has_explicit_registry:
        host = first.lower()
        path_parts = parts[1:]
        if host == "ghcr.io":
            registry = RegistryType.GHCR
        elif host in {"docker.io", "index.docker.io", "registry-1.docker.io"}:
            registry = RegistryType.DOCKERHUB
        else:
            registry = RegistryType.UNKNOWN

    if not path_parts:
        return ContainerInfo(
            name=name,
            container_id=container_id,
            image_ref=image_ref,
            registry=registry,
            namespace="library",
            image_name="unknown",
            current_tag=current_tag,
        )

    if len(path_parts) == 1:
        namespace = "library"
        image_name = path_parts[0]
    else:
        namespace = "/".join(path_parts[:-1])
        image_name = path_parts[-1]

    return ContainerInfo(
        name=name,
        container_id=container_id,
        image_ref=image_ref,
        registry=registry,
        namespace=namespace,
        image_name=image_name,
        current_tag=current_tag,
    )


def get_running_containers() -> list[ContainerInfo]:
    """Return running Docker containers with normalized image metadata."""
    try:
        client = docker.from_env()
        raw_containers = client.containers.list()
    except DockerException as exc:
        raise DockerConnectionError(
            "Could not connect to Docker. Ensure the Docker daemon is running "
            "and the current user can access the Docker socket."
        ) from exc

    containers: list[ContainerInfo] = []
    for container in raw_containers:
        image_ref = (
            container.attrs.get("Config", {}).get("Image")
            or getattr(container.image, "tags", [""])[0]
            or ""
        )
        info = parse_image_ref(
            image_ref,
            name=(container.name or ""),
            container_id=(container.id or "")[:12],
        )
        containers.append(info)

    return containers
