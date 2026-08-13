"""Container discovery sources for dockwatch."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import DockwatchConfig
from .docker_client import DockerConnectionError, get_running_containers, parse_image_ref, _detect_portainer_source
from .integrations import PortainerClient, PortainerEnvironment, PortainerError
from .models import ContainerInfo


@dataclass(slots=True)
class SourceDiscoveryResult:
    containers: list[ContainerInfo] = field(default_factory=list)
    environments: list[PortainerEnvironment] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _clean_container_name(payload: dict) -> str:
    names = payload.get("Names")
    if isinstance(names, list) and names:
        return str(names[0]).lstrip("/")
    return str(payload.get("Names") or payload.get("Id") or "unknown").lstrip("/")


def _build_image_digest_map(images: list[dict]) -> dict[str, str]:
    """Map an image ID to its first RepoDigest, so container listings (which
    only carry an ImageID, not RepoDigests) can resolve a real registry
    digest the same way local Docker SDK discovery does."""
    digest_map: dict[str, str] = {}
    for image in images:
        image_id = image.get("Id")
        repo_digests = image.get("RepoDigests") or []
        if image_id and repo_digests:
            digest_map[image_id] = repo_digests[0]
    return digest_map


def _map_portainer_container(
    payload: dict, environment: PortainerEnvironment, image_digests: dict[str, str],
) -> ContainerInfo:
    labels = dict(payload.get("Labels") or {})
    image_ref = str(payload.get("Image") or "")
    info = parse_image_ref(
        image_ref,
        name=_clean_container_name(payload),
        container_id=str(payload.get("Id") or "")[:12],
        labels=labels,
        compose_image_digest=labels.get("com.docker.compose.image"),
        repo_digest=image_digests.get(str(payload.get("ImageID") or "")),
    )
    # When labels can't determine the deployment source, trust Portainer
    # discovery: a container only visible through Portainer's Docker proxy
    # (no compose labels at all, e.g. a standalone `docker run` container)
    # is assumed Portainer-managed.  But when labels definitively identify
    # a local compose project, don't override -- the container was deployed
    # outside Portainer and is merely visible through it.
    detected = _detect_portainer_source(labels)
    if detected is None or detected == "portainer":
        info.source = "portainer"
    info.environment_id = str(environment.id)
    info.environment_name = environment.name
    return info


async def discover_portainer(
    config: DockwatchConfig,
    *,
    selected_environment: str | None = None,
) -> SourceDiscoveryResult:
    if not config.portainer.enabled:
        return SourceDiscoveryResult(errors=["portainer is disabled"])
    try:
        client = PortainerClient(
            base_url=config.portainer.url,
            api_key=config.portainer.api_key,
        )
    except PortainerError as exc:
        return SourceDiscoveryResult(errors=[str(exc)])

    try:
        environments = await client.list_environments()
    except PortainerError as exc:
        return SourceDiscoveryResult(errors=[str(exc)])

    configured_ids = {str(item) for item in config.portainer.environments}
    target_environments = environments
    if configured_ids:
        target_environments = [env for env in environments if str(env.id) in configured_ids]
    if selected_environment:
        target_environments = [env for env in target_environments if str(env.id) == str(selected_environment)]

    result = SourceDiscoveryResult(environments=target_environments)
    for environment in target_environments:
        try:
            payload = await client.list_containers(environment.id)
        except PortainerError as exc:
            result.errors.append(str(exc))
            continue
        try:
            images = await client.list_images(environment.id)
        except PortainerError:
            images = []
        image_digests = _build_image_digest_map(images)
        result.containers.extend(
            _map_portainer_container(item, environment, image_digests) for item in payload
        )
    return result


async def discover_containers(
    config: DockwatchConfig,
    *,
    source: str = "local",
    selected_environment: str | None = None,
) -> SourceDiscoveryResult:
    result = SourceDiscoveryResult()
    if source in {"local", "all"}:
        try:
            result.containers.extend(get_running_containers())
        except DockerConnectionError as exc:
            result.errors.append(str(exc))
            if source == "local":
                return result
    if source in {"portainer", "all"}:
        portainer_result = await discover_portainer(config, selected_environment=selected_environment)
        result.containers.extend(portainer_result.containers)
        result.environments = portainer_result.environments
        result.errors.extend(portainer_result.errors)

    # Deduplicate: when source=all and the same container name appears
    # from both local Docker and Portainer, keep the Portainer identity
    # and discard the local one.  This prevents double-checking and
    # ensures a single authoritative source per container.
    seen: dict[str, ContainerInfo] = {}
    for c in result.containers:
        existing = seen.get(c.name)
        if existing is None:
            seen[c.name] = c
        elif c.source == "portainer" and (
            existing.source != "portainer"
            or (not existing.environment_id and c.environment_id)
        ):
            seen[c.name] = c
    result.containers = list(seen.values())

    return result


async def discover_environments(config: DockwatchConfig) -> list[PortainerEnvironment]:
    result = await discover_portainer(config)
    if result.errors:
        raise PortainerError("; ".join(result.errors))
    return result.environments
