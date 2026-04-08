"""Registry link helpers for dockwatch notifications."""

from __future__ import annotations

from .models import ContainerInfo, RegistryType


def _source_url(info: ContainerInfo) -> str | None:
    source = info.labels.get("org.opencontainers.image.source")
    if not source:
        return None
    source = source.strip()
    if source.startswith("http://") or source.startswith("https://"):
        return source
    return None


def build_registry_url(info: ContainerInfo) -> str | None:
    source_url = _source_url(info)
    if source_url:
        return source_url

    if info.registry == RegistryType.DOCKERHUB:
        if info.namespace and info.namespace != "library":
            return f"https://hub.docker.com/r/{info.namespace}/{info.image_name}"
        return f"https://hub.docker.com/_/{info.image_name}"

    if info.registry == RegistryType.GHCR:
        if info.namespace:
            return f"https://github.com/{info.namespace}/{info.image_name}"
        return None

    if info.registry == RegistryType.LSCR:
        if info.namespace:
            return f"https://github.com/{info.namespace}/docker-{info.image_name}"
        return None

    return None


def build_registry_link(info: ContainerInfo) -> tuple[str, str] | None:
    url = build_registry_url(info)
    if not url:
        return None
    source_url = _source_url(info)
    if source_url:
        return "Source", url
    if info.registry == RegistryType.DOCKERHUB:
        return "Hub", url
    return "Repo", url
