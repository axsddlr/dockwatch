"""Safe local container update planning and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess

import docker
from docker.errors import DockerException
from docker.models.containers import Container

from .config import AgentConfig, ComposeProjectConfig, DockwatchConfig, resolve_compose_file, resolve_host_path
from .docker_client import DIGEST_PINNED_TAG, DockerConnectionError, get_docker_client
from .integrations import AgentClient, AgentError, PortainerClient, PortainerError
from .models import ContainerInfo, UpdateResult, deployed_display_result, remote_display

# Upper bound for docker compose pull/up; prevents a hung compose command
# from blocking the update path forever.
COMPOSE_COMMAND_TIMEOUT_SECONDS = 600

_FLOATING_TAGS = {"latest", "edge", "dev", "nightly"}


class UpdateExecutionError(RuntimeError):
    """Raised when an update plan cannot be executed safely."""


@dataclass(slots=True)
class UpdatePlan:
    container_name: str
    container_id: str
    source: str
    mode: str
    allowed: bool
    image_ref: str
    deployed_display: str
    remote_display: str
    reason: str | None = None
    compose_project: str | None = None
    compose_service: str | None = None
    current_tag: str | None = None
    remote_tag: str | None = None
    environment_id: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UpdateExecutionResult:
    success: bool
    mode: str
    message: str
    details: list[str] = field(default_factory=list)
    rollback_message: str | None = None


def _is_compose_managed(result: UpdateResult) -> bool:
    info = result.container_info
    return bool(info.compose_project and info.compose_service)


def _blocked_plan(result: UpdateResult, reason: str, *, mode: str = "blocked") -> UpdatePlan:
    return UpdatePlan(
        container_name=result.container_info.name,
        container_id=result.container_info.container_id,
        source=result.container_info.source,
        mode=mode,
        allowed=False,
        image_ref=result.container_info.image_ref,
        deployed_display=deployed_display_result(result),
        remote_display=remote_display(result),
        reason=reason,
        compose_project=result.container_info.compose_project,
        compose_service=result.container_info.compose_service,
    )


def _build_portainer_update_plan(result: UpdateResult) -> UpdatePlan:
    info = result.container_info
    if result.status == "PINNED":
        return _blocked_plan(result, "pinned containers cannot be updated from dockwatch")
    if result.check_error:
        return _blocked_plan(result, "container check failed; refresh the row before updating")
    if result.is_outdated is not True:
        return _blocked_plan(result, "container is not marked outdated")
    if not _is_compose_managed(result):
        return _blocked_plan(result, "only compose-managed Portainer stacks can be updated from dockwatch")
    if info.current_tag == DIGEST_PINNED_TAG or "@" in info.image_ref:
        return _blocked_plan(result, "digest-pinned images are blocked for safe updates")
    if info.current_tag.lower() in _FLOATING_TAGS and result.comparison_basis != "digest":
        return _blocked_plan(result, "floating tags require digest-backed outdated detection")

    remote_tag = result.remote_tag or result.latest_tag
    if (
        info.current_tag.lower() not in _FLOATING_TAGS
        and remote_tag
        and remote_tag != info.current_tag
        and not remote_tag.lower().startswith("sha256:")
    ):
        plan_remote_tag = remote_tag
    else:
        plan_remote_tag = None

    return UpdatePlan(
        container_name=info.name,
        container_id=info.container_id,
        source=info.source,
        mode="portainer-compose",
        allowed=True,
        image_ref=info.image_ref,
        deployed_display=deployed_display_result(result),
        remote_display=remote_display(result),
        compose_project=info.compose_project,
        compose_service=info.compose_service,
        current_tag=info.current_tag,
        remote_tag=plan_remote_tag,
        environment_id=info.environment_id,
    )


def _replace_ref_tag(image_ref: str, new_tag: str) -> str:
    """Return `image_ref` with its tag replaced by `new_tag`.

    Handles optional registry host:port prefixes by splitting on the last
    colon of the final path segment, and refs without any tag at all.
    """
    last_segment = image_ref.split("/")[-1]
    if ":" in last_segment:
        base, _ = image_ref.rsplit(":", 1)
        return f"{base}:{new_tag}"
    return f"{image_ref}:{new_tag}"


def _agent_target_ref(info: ContainerInfo, result: UpdateResult) -> str:
    """The image ref an agent should pull/recreate with.

    Floating tags keep their ref (re-pull fetches the new digest); pinned
    tags are rebuilt with the remote tag so the agent actually switches
    versions (unlike the local plain path, which can only re-pull the
    deployed ref).
    """
    remote_tag = result.remote_tag or result.latest_tag
    if (
        info.current_tag.lower() not in _FLOATING_TAGS
        and remote_tag
        and remote_tag != info.current_tag
        and not remote_tag.lower().startswith("sha256:")
    ):
        return _replace_ref_tag(info.image_ref, remote_tag)
    return info.image_ref


def _build_agent_update_plan(result: UpdateResult) -> UpdatePlan:
    info = result.container_info
    if result.status == "PINNED":
        return _blocked_plan(result, "pinned containers cannot be updated from dockwatch", mode="agent-update")
    if result.check_error:
        return _blocked_plan(result, "container check failed; refresh the row before updating", mode="agent-update")
    if result.is_outdated is not True:
        return _blocked_plan(result, "container is not marked outdated", mode="agent-update")
    if not info.image_ref:
        return _blocked_plan(result, "container image reference is missing", mode="agent-update")
    if info.current_tag == DIGEST_PINNED_TAG or "@" in info.image_ref:
        return _blocked_plan(result, "digest-pinned images are blocked for safe updates", mode="agent-update")
    if info.registry.value == "unknown":
        return _blocked_plan(result, "local-only or unsupported image references cannot be updated safely", mode="agent-update")
    if info.current_tag.lower() in _FLOATING_TAGS and result.comparison_basis != "digest":
        return _blocked_plan(result, "floating tags require digest-backed outdated detection", mode="agent-update")
    if _is_compose_managed(result):
        return _blocked_plan(
            result,
            "compose-managed containers cannot be updated through an agent (v1); manage them on the agent host directly",
            mode="agent-update",
        )

    return UpdatePlan(
        container_name=info.name,
        container_id=info.container_id,
        source=info.source,
        mode="agent-update",
        allowed=True,
        image_ref=_agent_target_ref(info, result),
        deployed_display=deployed_display_result(result),
        remote_display=remote_display(result),
        environment_id=info.environment_id,
    )


def _build_agent_rollback_plan(result: UpdateResult, *, old_tag: str, new_tag: str) -> UpdatePlan:
    info = result.container_info
    if info.current_tag != new_tag:
        return _blocked_plan(
            result,
            f"deployed tag is '{info.current_tag}', expected '{new_tag}' from history; refresh before rolling back",
            mode="agent-rollback",
        )
    if _is_compose_managed(result):
        return _blocked_plan(
            result,
            "compose-managed containers cannot be rolled back through an agent (v1)",
            mode="agent-rollback",
        )
    return UpdatePlan(
        container_name=info.name,
        container_id=info.container_id,
        source=info.source,
        mode="agent-rollback",
        allowed=True,
        image_ref=_replace_ref_tag(info.image_ref, old_tag),
        deployed_display=deployed_display_result(result),
        remote_display=old_tag,
        current_tag=new_tag,
        remote_tag=old_tag,
        environment_id=info.environment_id,
    )


def build_update_plan(result: UpdateResult, config: DockwatchConfig) -> UpdatePlan:
    info = result.container_info
    if info.source == "portainer":
        return _build_portainer_update_plan(result)
    if info.source == "agent":
        return _build_agent_update_plan(result)
    if info.source != "local":
        return _blocked_plan(result, "read-only source; only local Docker and Portainer stack updates are supported")
    if result.status == "PINNED":
        return _blocked_plan(result, "pinned containers cannot be updated from dockwatch")
    if result.check_error:
        return _blocked_plan(result, "container check failed; refresh the row before updating")
    if result.is_outdated is not True:
        return _blocked_plan(result, "container is not marked outdated")
    if not info.image_ref:
        return _blocked_plan(result, "container image reference is missing")
    if info.current_tag == DIGEST_PINNED_TAG or "@" in info.image_ref:
        return _blocked_plan(result, "digest-pinned images are blocked for safe updates")
    if info.registry.value == "unknown":
        return _blocked_plan(result, "local-only or unsupported image references cannot be updated safely")
    if info.current_tag.lower() in _FLOATING_TAGS and result.comparison_basis != "digest":
        return _blocked_plan(result, "floating tags require digest-backed outdated detection")

    if _is_compose_managed(result):
        project = info.compose_project or ""
        compose_cfg = config.compose_projects.get(project)
        if compose_cfg is None:
            return _blocked_plan(
                result,
                f"compose project '{project}' is missing from config.compose_projects",
                mode="compose",
            )
        if not compose_cfg.workdir.strip():
            return _blocked_plan(
                result,
                f"compose project '{project}' has no configured workdir",
                mode="compose",
            )
        remote_tag = result.remote_tag or result.latest_tag
        if (
            info.current_tag.lower() not in _FLOATING_TAGS
            and remote_tag
            and remote_tag != info.current_tag
            and not remote_tag.lower().startswith("sha256:")
        ):
            # Compose pins the image to an exact tag: `docker compose pull`
            # only re-fetches that same tag, so nothing actually changes
            # unless the compose file's tag is rewritten first.
            plan_remote_tag = remote_tag
        else:
            plan_remote_tag = None

        return UpdatePlan(
            container_name=info.name,
            container_id=info.container_id,
            source=info.source,
            mode="compose",
            allowed=True,
            image_ref=info.image_ref,
            deployed_display=deployed_display_result(result),
            remote_display=remote_display(result),
            compose_project=project,
            compose_service=info.compose_service,
            current_tag=info.current_tag,
            remote_tag=plan_remote_tag,
        )

    return UpdatePlan(
        container_name=info.name,
        container_id=info.container_id,
        source=info.source,
        mode="plain",
        allowed=True,
        image_ref=info.image_ref,
        deployed_display=deployed_display_result(result),
        remote_display=remote_display(result),
    )


def _build_portainer_rollback_plan(
    result: UpdateResult, *, old_tag: str, new_tag: str,
) -> UpdatePlan:
    info = result.container_info
    if info.current_tag != new_tag:
        return _blocked_plan(
            result,
            f"deployed tag is '{info.current_tag}', expected '{new_tag}' from history; refresh before rolling back",
            mode="portainer-compose",
        )
    return UpdatePlan(
        container_name=info.name,
        container_id=info.container_id,
        source=info.source,
        mode="portainer-compose",
        allowed=True,
        image_ref=info.image_ref,
        deployed_display=deployed_display_result(result),
        remote_display=old_tag,
        compose_project=info.compose_project,
        compose_service=info.compose_service,
        current_tag=new_tag,
        remote_tag=old_tag,
        environment_id=info.environment_id,
    )


def _build_local_compose_rollback_plan(
    result: UpdateResult, config: DockwatchConfig, *, old_tag: str, new_tag: str,
) -> UpdatePlan:
    info = result.container_info
    project = info.compose_project or ""
    compose_cfg = config.compose_projects.get(project)
    if compose_cfg is None:
        return _blocked_plan(
            result, f"compose project '{project}' is missing from config.compose_projects", mode="compose",
        )
    if not compose_cfg.workdir.strip():
        return _blocked_plan(result, f"compose project '{project}' has no configured workdir", mode="compose")
    if info.current_tag != new_tag:
        return _blocked_plan(
            result,
            f"deployed tag is '{info.current_tag}', expected '{new_tag}' from history; refresh before rolling back",
            mode="compose",
        )

    return UpdatePlan(
        container_name=info.name,
        container_id=info.container_id,
        source=info.source,
        mode="compose",
        allowed=True,
        image_ref=info.image_ref,
        deployed_display=deployed_display_result(result),
        remote_display=old_tag,
        compose_project=project,
        compose_service=info.compose_service,
        current_tag=new_tag,
        remote_tag=old_tag,
    )


def _build_plain_rollback_plan(
    result: UpdateResult, *, old_tag: str, new_tag: str,
) -> UpdatePlan:
    info = result.container_info
    if info.current_tag != new_tag:
        return _blocked_plan(
            result,
            f"deployed tag is '{info.current_tag}', expected '{new_tag}' from history; refresh before rolling back",
        )
    repo = info.image_ref.rsplit(":", 1)[0]
    return UpdatePlan(
        container_name=info.name,
        container_id=info.container_id,
        source=info.source,
        mode="plain",
        allowed=True,
        image_ref=f"{repo}:{old_tag}",
        deployed_display=deployed_display_result(result),
        remote_display=old_tag,
        current_tag=new_tag,
        remote_tag=old_tag,
    )


def build_rollback_plan(
    result: UpdateResult, config: DockwatchConfig, *, old_tag: str, new_tag: str,
) -> UpdatePlan:
    """Build a plan that reverts a container's image tag back to `old_tag`,
    reusing the same update machinery as a forward update (compose rewrite,
    Portainer stack redeploy, or plain recreate) just with current/remote
    tags swapped."""
    info = result.container_info
    if info.source == "portainer":
        if not _is_compose_managed(result):
            return _blocked_plan(result, "rollback is only supported for compose-managed containers")
        return _build_portainer_rollback_plan(result, old_tag=old_tag, new_tag=new_tag)
    if info.source == "agent":
        return _build_agent_rollback_plan(result, old_tag=old_tag, new_tag=new_tag)
    if info.source != "local":
        return _blocked_plan(result, "read-only source; only local Docker and Portainer stack rollbacks are supported")
    if _is_compose_managed(result):
        return _build_local_compose_rollback_plan(result, config, old_tag=old_tag, new_tag=new_tag)
    if not info.image_ref:
        return _blocked_plan(result, "container image reference is missing")
    return _build_plain_rollback_plan(result, old_tag=old_tag, new_tag=new_tag)


def describe_update_plan(plan: UpdatePlan) -> list[str]:
    lines = [
        f"Container: {plan.container_name}",
        f"Mode: {plan.mode}",
        f"Image: {plan.image_ref}",
        f"Deployed -> Remote: {plan.deployed_display} -> {plan.remote_display}",
    ]
    if plan.compose_project and plan.compose_service:
        lines.append(f"Compose target: {plan.compose_project}/{plan.compose_service}")
    if plan.reason:
        lines.append(f"Blocked: {plan.reason}")
    return lines


def _docker_client() -> docker.DockerClient:
    try:
        return get_docker_client()
    except DockerException as exc:
        raise DockerConnectionError(
            "Could not connect to Docker. Ensure the Docker daemon is running "
            "and the current user can access the Docker socket."
        ) from exc


def _create_host_config(container: Container, client: docker.DockerClient) -> dict:
    host = container.attrs.get("HostConfig", {}) or {}
    kwargs: dict[str, object] = {}
    if host.get("Binds"):
        kwargs["binds"] = host["Binds"]
    if host.get("PortBindings"):
        kwargs["port_bindings"] = host["PortBindings"]
    if host.get("RestartPolicy"):
        kwargs["restart_policy"] = host["RestartPolicy"]
    if host.get("NetworkMode"):
        kwargs["network_mode"] = host["NetworkMode"]
    if host.get("Privileged") is not None:
        kwargs["privileged"] = bool(host["Privileged"])
    if host.get("ExtraHosts"):
        kwargs["extra_hosts"] = host["ExtraHosts"]
    if host.get("CapAdd"):
        kwargs["cap_add"] = host["CapAdd"]
    if host.get("CapDrop"):
        kwargs["cap_drop"] = host["CapDrop"]
    if host.get("Dns"):
        kwargs["dns"] = host["Dns"]
    if host.get("DnsSearch"):
        kwargs["dns_search"] = host["DnsSearch"]
    if host.get("Devices"):
        kwargs["devices"] = host["Devices"]
    if host.get("Memory"):
        kwargs["mem_limit"] = host["Memory"]
    if host.get("NanoCpus"):
        kwargs["nano_cpus"] = host["NanoCpus"]
    if host.get("AutoRemove") is not None:
        kwargs["auto_remove"] = bool(host["AutoRemove"])
    return client.api.create_host_config(**kwargs)


def _create_networking_config(container: Container, client: docker.DockerClient) -> tuple[dict | None, list[tuple[str, list[str]]]]:
    network_mode = (container.attrs.get("HostConfig", {}) or {}).get("NetworkMode") or "default"
    networks = (container.attrs.get("NetworkSettings", {}) or {}).get("Networks", {}) or {}
    extras: list[tuple[str, list[str]]] = []
    if not networks or network_mode in {"host", "none", "container"}:
        return None, extras

    endpoint_configs: dict[str, dict] = {}
    aliases_by_network: dict[str, list[str]] = {}
    for network_name, network_info in networks.items():
        aliases = [
            alias
            for alias in (network_info.get("Aliases") or [])
            if alias and alias != container.name
        ]
        endpoint_configs[network_name] = client.api.create_endpoint_config(aliases=aliases or None)
        aliases_by_network[network_name] = aliases

    primary_name = network_mode if network_mode in endpoint_configs else next(iter(endpoint_configs))
    networking_config: dict | None = None
    for network_name, endpoint in endpoint_configs.items():
        if network_name == primary_name:
            networking_config = client.api.create_networking_config({network_name: endpoint})
            continue
        extras.append((network_name, aliases_by_network[network_name]))
    return networking_config, extras


def _create_replacement_container(container: Container, client: docker.DockerClient, image_ref: str, original_name: str) -> Container:
    attrs = container.attrs
    config = attrs.get("Config", {}) or {}
    host_config = _create_host_config(container, client)
    networking_config, extra_networks = _create_networking_config(container, client)
    volumes = [mount.get("Destination") for mount in attrs.get("Mounts", []) if mount.get("Destination")]
    ports = list((config.get("ExposedPorts") or {}).keys())

    created = client.api.create_container(
        image=image_ref,
        command=config.get("Cmd"),
        detach=True,
        entrypoint=config.get("Entrypoint"),
        environment=config.get("Env"),
        host_config=host_config,
        hostname=config.get("Hostname"),
        labels=config.get("Labels"),
        name=original_name,
        networking_config=networking_config,
        ports=ports or None,
        stdin_open=bool(config.get("OpenStdin")),
        tty=bool(config.get("Tty")),
        user=config.get("User") or None,
        volumes=volumes or None,
        working_dir=config.get("WorkingDir") or None,
    )
    new_container = client.containers.get(created["Id"])
    for network_name, aliases in extra_networks:
        network = client.networks.get(network_name)
        kwargs = {"aliases": aliases} if aliases else {}
        network.connect(new_container, **kwargs)
    return new_container


def _rollback_plain_update(
    *,
    original: Container,
    original_was_running: bool,
    original_name: str,
    replacement: Container | None,
) -> str:
    details: list[str] = []
    replacement_still_holds_name = False
    if replacement is not None:
        try:
            replacement.remove(force=True)
            details.append("removed failed replacement")
        except DockerException as exc:
            replacement_still_holds_name = True
            details.append(
                f"CRITICAL: failed to remove replacement container, it still occupies "
                f"the name '{original_name}' and the original is stranded under a backup "
                f"name until this is resolved manually: {exc}"
            )
    try:
        original.reload()
    except DockerException:
        pass
    if replacement_still_holds_name:
        details.append(
            f"skipped restoring original container name '{original_name}' "
            "because the replacement still holds it"
        )
    else:
        try:
            original.rename(original_name)
        except DockerException as exc:
            details.append(f"failed to restore original name: {exc}")
    if original_was_running:
        try:
            original.start()
            details.append("restarted original container")
        except DockerException as exc:
            details.append(f"failed to restart original container: {exc}")
    return "; ".join(details) or "rollback attempted"


def _execute_plain_update(plan: UpdatePlan) -> UpdateExecutionResult:
    client = _docker_client()
    try:
        return _execute_plain_update_with_client(plan, client)
    finally:
        client.close()


def _execute_plain_update_with_client(plan: UpdatePlan, client: docker.DockerClient) -> UpdateExecutionResult:
    try:
        container = client.containers.get(plan.container_name)
    except DockerException:
        try:
            container = client.containers.get(plan.container_id)
        except DockerException as exc:
            return UpdateExecutionResult(
                False, "plain",
                f"container '{plan.container_name}' not found: {exc}",
            )

    found_id = (container.attrs.get("Id", "") or "")[:12]
    plan_id = (plan.container_id or "")[:12]
    if plan_id and found_id != plan_id:
        return UpdateExecutionResult(
            False, "plain",
            f"container ID mismatch: plan expected {plan_id}, found {found_id}",
        )

    state = (container.attrs.get("State", {}) or {})
    was_running = bool(state.get("Running"))
    backup_name = f"{plan.container_name}-dockwatch-backup"
    replacement: Container | None = None

    try:
        client.images.pull(plan.image_ref)
    except DockerException as exc:
        return UpdateExecutionResult(False, "plain", f"image pull failed: {exc}")

    # Clear a stale leftover from a previous failed attempt: a container that
    # still owns the backup name but is not the one being updated. Without
    # this, retrying a failed plain update fails with a name-conflict 409.
    try:
        stale = client.containers.get(backup_name)
        if stale.id != container.id:
            stale.remove(force=True)
    except docker.errors.NotFound:
        pass
    except DockerException:
        pass

    try:
        if was_running:
            container.stop(timeout=10)
        container.rename(backup_name)
        replacement = _create_replacement_container(container, client, plan.image_ref, plan.container_name)
        if was_running:
            replacement.start()
            replacement.reload()
            new_state = replacement.attrs.get("State", {}) or {}
            if not bool(new_state.get("Running")):
                raise UpdateExecutionError("replacement container did not reach running state")
        container.remove(force=True)
        return UpdateExecutionResult(
            True,
            "plain",
            f"updated '{plan.container_name}' via recreate",
            details=[f"pulled {plan.image_ref}", "created replacement container"],
        )
    except (DockerException, UpdateExecutionError) as exc:
        rollback = _rollback_plain_update(
            original=container,
            original_was_running=was_running,
            original_name=plan.container_name,
            replacement=replacement,
        )
        return UpdateExecutionResult(
            False,
            "plain",
            f"update failed: {exc}",
            rollback_message=rollback,
        )


def _compose_command(project: ComposeProjectConfig, *args: str) -> list[str]:
    command = ["docker", "compose"]
    if project.project_name:
        command.extend(["-p", project.project_name])
    for file in project.files:
        command.extend(["-f", resolve_compose_file(file, project.workdir).as_posix()])
    command.extend(args)
    return command


def _write_compose_file(path: Path, text: str) -> None:
    """Write a compose file atomically (tmp + replace), matching save_config's
    pattern, so a process kill mid-write can't leave a truncated compose file
    on what's usually a bind-mounted host path."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _replace_service_image(text: str, service: str, old_image: str, new_image: str) -> str | None:
    """Replace `image: <old_image>` inside exactly one service's block.

    Scoped by indentation depth: a service's block ends at the first
    subsequent line whose indentation is <= the service key's own
    indentation (i.e. a sibling key or dedent), so this cannot walk into
    another service that happens to pin the same image. Returns the
    rewritten text, or None if the service/line wasn't found.
    """
    lines = text.splitlines(keepends=True)
    service_pattern = re.compile(rf"^(\s*){re.escape(service)}:\s*(?:#.*)?$")
    image_pattern = re.compile(rf"^(\s*)image:\s*{re.escape(old_image)}\s*(#.*)?$")

    in_block = False
    service_indent = 0
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if not in_block:
            match = service_pattern.match(stripped)
            if match:
                in_block = True
                service_indent = len(match.group(1))
            continue

        # Blank/comment-only lines don't end the block.
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip())
        if indent <= service_indent:
            in_block = False
            if service_pattern.match(stripped):
                in_block = True
                service_indent = len(match.group(1)) if (match := service_pattern.match(stripped)) else service_indent
            continue

        image_match = image_pattern.match(stripped)
        if image_match:
            comment = f" {image_match.group(2)}" if image_match.group(2) else ""
            newline = "\n" if line.endswith("\n") else ""
            lines[i] = f"{image_match.group(1)}image: {new_image}{comment}{newline}"
            return "".join(lines)

    return None


def _rewrite_compose_image_tag(
    project: ComposeProjectConfig, workdir: Path, plan: UpdatePlan,
) -> str | None:
    """Rewrite the pinned tag in the service's `image:` line to plan.remote_tag.

    Compose pins the deployed tag literally in the file, so `docker compose
    pull` alone re-fetches the same tag forever. Returns an error message on
    failure, or None on success (including when no rewrite was needed).
    """
    if not plan.current_tag or not plan.remote_tag:
        return None
    repo = plan.image_ref.rsplit(":", 1)[0]
    old_image = f"{repo}:{plan.current_tag}"
    new_image = f"{repo}:{plan.remote_tag}"

    for file in project.files:
        path = resolve_compose_file(file, project.workdir)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if old_image not in text:
            continue
        new_text = _replace_service_image(text, plan.compose_service, old_image, new_image)
        if new_text is None:
            continue
        _write_compose_file(path, new_text)
        return None

    return f"could not find 'image: {old_image}' for service '{plan.compose_service}' in compose files"


def _execute_compose_update(plan: UpdatePlan, config: DockwatchConfig) -> UpdateExecutionResult:
    if not plan.compose_project or not plan.compose_service:
        return UpdateExecutionResult(False, "compose", "compose project metadata is incomplete")
    project = config.compose_projects.get(plan.compose_project)
    if project is None:
        return UpdateExecutionResult(False, "compose", f"compose project '{plan.compose_project}' is not configured")

    workdir = resolve_host_path(project.workdir)
    if not workdir.is_dir():
        return UpdateExecutionResult(False, "compose", f"compose workdir is not a directory or does not exist: {workdir}")

    if plan.remote_tag:
        rewrite_error = _rewrite_compose_image_tag(project, workdir, plan)
        if rewrite_error:
            return UpdateExecutionResult(False, "compose", rewrite_error)

    pull_cmd = _compose_command(project, "pull", plan.compose_service)
    up_cmd = _compose_command(project, "up", "-d", plan.compose_service)

    try:
        pull = subprocess.run(
            pull_cmd, cwd=workdir, capture_output=True, text=True, check=False,
            timeout=COMPOSE_COMMAND_TIMEOUT_SECONDS,
        )
        if pull.returncode != 0:
            return UpdateExecutionResult(
                False,
                "compose",
                f"compose pull failed for '{plan.compose_service}'",
                details=[pull.stderr.strip() or pull.stdout.strip()],
            )
        up = subprocess.run(
            up_cmd, cwd=workdir, capture_output=True, text=True, check=False,
            timeout=COMPOSE_COMMAND_TIMEOUT_SECONDS,
        )
        if up.returncode != 0:
            return UpdateExecutionResult(
                False,
                "compose",
                f"compose up failed for '{plan.compose_service}'",
                details=[up.stderr.strip() or up.stdout.strip()],
            )
    except subprocess.TimeoutExpired as exc:
        return UpdateExecutionResult(
            False,
            "compose",
            f"docker compose command timed out after {exc.timeout:.0f}s",
        )
    except OSError as exc:
        return UpdateExecutionResult(False, "compose", f"failed to run docker compose: {exc}")

    details = []
    if plan.remote_tag:
        details.append(f"rewrote compose image tag: {plan.current_tag} -> {plan.remote_tag}")
    details.extend(["docker compose pull completed", "docker compose up -d completed"])
    return UpdateExecutionResult(
        True,
        "compose",
        f"updated compose service '{plan.compose_service}'",
        details=details,
    )


def execute_update(plan: UpdatePlan, config: DockwatchConfig) -> UpdateExecutionResult:
    if not plan.allowed:
        return UpdateExecutionResult(False, plan.mode, plan.reason or "update is blocked")
    if plan.mode == "compose":
        return _execute_compose_update(plan, config)
    return _execute_plain_update(plan)


def _find_agent(config: DockwatchConfig, plan: UpdatePlan) -> AgentConfig | None:
    name = plan.environment_id
    for agent in config.agents:
        if agent.enabled and agent.name == name:
            return agent
    return None


async def execute_agent_update(plan: UpdatePlan, config: DockwatchConfig) -> UpdateExecutionResult:
    if not plan.allowed:
        return UpdateExecutionResult(False, plan.mode, plan.reason or "update is blocked")
    agent = _find_agent(config, plan)
    if agent is None:
        return UpdateExecutionResult(False, plan.mode, f"agent '{plan.environment_id}' is not configured")
    try:
        client = AgentClient(base_url=agent.url, token=agent.token)
        payload = await client.update_container(plan.container_id, plan.image_ref)
    except AgentError as exc:
        return UpdateExecutionResult(False, plan.mode, f"agent update failed: {exc}")
    return _agent_result(payload, plan.mode)


async def execute_agent_rollback(plan: UpdatePlan, config: DockwatchConfig) -> UpdateExecutionResult:
    if not plan.allowed:
        return UpdateExecutionResult(False, plan.mode, plan.reason or "rollback is blocked")
    agent = _find_agent(config, plan)
    if agent is None:
        return UpdateExecutionResult(False, plan.mode, f"agent '{plan.environment_id}' is not configured")
    try:
        client = AgentClient(base_url=agent.url, token=agent.token)
        payload = await client.rollback_container(plan.container_id, plan.image_ref)
    except AgentError as exc:
        return UpdateExecutionResult(False, plan.mode, f"agent rollback failed: {exc}")
    return _agent_result(payload, plan.mode)


def _agent_result(payload: dict, mode: str) -> UpdateExecutionResult:
    return UpdateExecutionResult(
        bool(payload.get("ok")),
        mode,
        str(payload.get("message") or "agent operation completed"),
        details=[str(detail) for detail in payload.get("details") or [] if isinstance(detail, str)],
        rollback_message=str(payload["rollback_message"]) if payload.get("rollback_message") else None,
    )


async def execute_portainer_compose_update(plan: UpdatePlan, config: DockwatchConfig) -> UpdateExecutionResult:
    """Update a Portainer-managed compose stack: rewrite the service's image
    tag in the stack's compose file and redeploy with pullImage=True so
    Portainer pulls the new image and recreates the changed service.
    """
    if not plan.allowed:
        return UpdateExecutionResult(False, plan.mode, plan.reason or "update is blocked")
    if not config.portainer.enabled:
        return UpdateExecutionResult(False, plan.mode, "Portainer integration is disabled")
    if not plan.compose_project or not plan.compose_service:
        return UpdateExecutionResult(False, plan.mode, "Portainer stack metadata is incomplete")

    client = PortainerClient(
        base_url=config.portainer.url,
        api_key=config.portainer.api_key,
        deploy_timeout=config.portainer.deploy_timeout,
    )
    try:
        stack = await client.find_stack_by_name(plan.compose_project)
        if stack is None:
            return UpdateExecutionResult(
                False, plan.mode, f"no Portainer stack found named '{plan.compose_project}'",
            )
        stack_id = stack["Id"]
        # The stack's EndpointId is the authoritative environment id.  A
        # Portainer-managed container discovered through the local Docker
        # socket carries source="portainer" (from its /data/compose/ labels)
        # but no environment_id, so resolve it from the stack here.
        environment_id = plan.environment_id
        if not environment_id:
            raw_endpoint = stack.get("EndpointId")
            if raw_endpoint is None:
                return UpdateExecutionResult(
                    False, plan.mode,
                    f"no Portainer environment found for stack '{plan.compose_project}'",
                )
            environment_id = str(raw_endpoint)
        text = await client.get_stack_file(stack_id)

        new_text = text
        if plan.remote_tag and plan.current_tag:
            repo = plan.image_ref.rsplit(":", 1)[0]
            old_image = f"{repo}:{plan.current_tag}"
            new_image = f"{repo}:{plan.remote_tag}"
            rewritten = _replace_service_image(text, plan.compose_service, old_image, new_image)
            if rewritten is None:
                return UpdateExecutionResult(
                    False, plan.mode,
                    f"could not find 'image: {old_image}' for service '{plan.compose_service}' in stack file",
                )
            new_text = rewritten

        await client.update_stack(
            stack_id, int(environment_id), stack_file_content=new_text, env=stack.get("Env"),
        )
    except PortainerError as exc:
        return UpdateExecutionResult(False, plan.mode, f"Portainer stack update failed: {exc}")

    details = []
    if plan.remote_tag:
        details.append(f"rewrote stack image tag: {plan.current_tag} -> {plan.remote_tag}")
    details.append("Portainer stack redeployed with pullImage=true")
    return UpdateExecutionResult(
        True, plan.mode, f"updated Portainer stack service '{plan.compose_service}'", details=details,
    )
