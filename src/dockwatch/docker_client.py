"""Docker client utilities for container discovery and image parsing."""

from __future__ import annotations

from functools import lru_cache

import docker
from docker.errors import DockerException

from .config import ComposeProjectConfig
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


_PORTAINER_COMPOSE_CONFIG_PREFIX = "/data/compose/"


def _detect_portainer_source(labels: dict[str, str]) -> str | None:
    """Check container labels for Portainer deployment markers.

    Portainer stores compose files under /data/compose/{stack_id}/, so a
    container whose ``com.docker.compose.project.config_files`` label starts
    with that prefix was deployed via Portainer.

    Returns ``"portainer"`` when labels indicate Portainer deployment,
    ``"local"`` when labels indicate a local (non-Portainer) compose
    project, or ``None`` when the source cannot be determined from labels
    alone (caller should decide based on the discovery mechanism).
    """
    config_files = labels.get("com.docker.compose.project.config_files", "")
    project_name = labels.get("com.docker.compose.project", "")
    if config_files and config_files.startswith(_PORTAINER_COMPOSE_CONFIG_PREFIX):
        return "portainer"
    if project_name and project_name.startswith(_PORTAINER_COMPOSE_CONFIG_PREFIX):
        return "portainer"
    # If there are compose labels but they DON'T point to Portainer's
    # storage prefix, the container was deployed from a local workdir.
    if project_name and config_files:
        return "local"
    return None


def compose_labels_to_project_config(
    labels: dict[str, str], *, project_name: str | None = None
) -> ComposeProjectConfig:
    """Best-effort derivation of a ComposeProjectConfig from a container's
    own com.docker.compose.* labels. Caller is responsible for validating
    the resulting workdir against dockwatch's own filesystem before saving.
    """
    workdir = str(labels.get("com.docker.compose.project.working_dir", "")).strip()
    files = _parse_label_list(labels, "com.docker.compose.project.config_files") or []
    return ComposeProjectConfig(
        workdir=workdir,
        files=files,
        project_name=(project_name or labels.get("com.docker.compose.project", "") or "").strip(),
    )


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
    detected_source = _detect_portainer_source(labels)
    source = detected_source if detected_source is not None else "local"
    # When labels definitively say "local", trust them over any discovery
    # mechanism -- a locally-deployed container visible via Portainer's
    # Docker proxy should still be tagged as local.
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
        source=source,
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
            tag = repo_part.rsplit(":", 1)[1]
            repo_part = repo_part.rsplit(":", 1)[0]
            current_tag = tag or "latest"

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


@lru_cache(maxsize=1)
def get_local_platform() -> tuple[str, str] | None:
    """Return (os, architecture) for the local Docker daemon, e.g. ("linux", "amd64").

    Used to pick the correct entry out of a multi-arch manifest list instead of
    comparing the list's own digest, which changes whenever *any* platform's
    image is rebuilt even if the platform actually deployed is unchanged.

    Cached for the process lifetime: the daemon's own architecture cannot
    change without a restart, and this avoids a `docker.from_env()` round
    trip on every registry check.
    """
    try:
        client = docker.from_env()
    except DockerException:
        return None
    try:
        arch = client.version().get("Arch")
    except DockerException:
        return None
    finally:
        client.close()
    return ("linux", arch) if arch else None


def get_running_containers() -> list[ContainerInfo]:
    """Return Docker containers, including non-running ones, with normalized image metadata."""
    try:
        client = docker.from_env()
    except DockerException as exc:
        raise DockerConnectionError(
            "Could not connect to Docker. Ensure the Docker daemon is running "
            "and the current user can access the Docker socket."
        ) from exc

    try:
        try:
            raw_containers = client.containers.list(all=True)
        except DockerException as exc:
            raise DockerConnectionError(
                "Could not connect to Docker. Ensure the Docker daemon is running "
                "and the current user can access the Docker socket."
            ) from exc

        containers: list[ContainerInfo] = []
        for container in raw_containers:
            try:
                config = container.attrs.get("Config", {}) or {}
                labels = dict(config.get("Labels", {}) or {})
                image_attrs = container.image.attrs if container.image else {}
                image_attrs = dict(image_attrs) if image_attrs else {}
            except DockerException:
                continue
            repo_digests = image_attrs.get("RepoDigests", []) or []
            repo_digest = repo_digests[0] if repo_digests else None
            image_ref = (
                config.get("Image")
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
    finally:
        client.close()


def get_image_id(container_name: str) -> str | None:
    """Return the Docker image ID for a running container by name."""
    try:
        client = docker.from_env()
    except Exception:  # noqa: BLE001
        return None
    try:
        container = client.containers.get(container_name)
        image_id = container.image.id
        return image_id.removeprefix("sha256:") if image_id else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        client.close()


def delete_container(name: str, *, force: bool = False) -> None:
    """Stop (if running) and remove a local container by name or ID.

    Raises DockerException on failure (not found, still running without
    force, etc.) so the caller can surface a specific error message.
    """
    client = docker.from_env()
    try:
        container = client.containers.get(name)
        container.remove(force=force)
    finally:
        client.close()


def delete_image(image_id: str, *, force: bool = False) -> None:
    """Remove a local image by ID. Raises DockerException if the image is
    still in use by another container and `force` is not set."""
    client = docker.from_env()
    try:
        client.images.remove(image_id, force=force)
    finally:
        client.close()
