"""Safe local container update planning and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess

import docker
from docker.errors import DockerException
from docker.models.containers import Container

from .config import ComposeProjectConfig, DockwatchConfig
from .docker_client import DIGEST_PINNED_TAG, DockerConnectionError
from .models import UpdateResult, deployed_display_result, remote_display

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


def build_update_plan(result: UpdateResult, config: DockwatchConfig) -> UpdatePlan:
    info = result.container_info
    if info.source != "local":
        return _blocked_plan(result, "read-only source; only local Docker updates are supported")
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
        return docker.from_env()
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

    endpoint_configs: dict[str, docker.types.EndpointConfig] = {}
    for network_name, network_info in networks.items():
        aliases = [
            alias
            for alias in (network_info.get("Aliases") or [])
            if alias and alias != container.name
        ]
        endpoint_configs[network_name] = docker.types.EndpointConfig(aliases=aliases or None)

    primary_name = network_mode if network_mode in endpoint_configs else next(iter(endpoint_configs))
    networking_config: dict | None = None
    for network_name, endpoint in endpoint_configs.items():
        if network_name == primary_name:
            networking_config = client.api.create_networking_config({network_name: endpoint})
            continue
        extras.append((network_name, endpoint.aliases or []))
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
        open_stdin=bool(config.get("OpenStdin")),
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
    if replacement is not None:
        try:
            replacement.remove(force=True)
            details.append("removed failed replacement")
        except DockerException as exc:
            details.append(f"failed to remove replacement: {exc}")
    try:
        original.reload()
    except DockerException:
        pass
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
        container = client.containers.get(plan.container_name)
    except DockerException:
        container = client.containers.get(plan.container_id)

    state = (container.attrs.get("State", {}) or {})
    was_running = bool(state.get("Running"))
    backup_name = f"{plan.container_name}-dockwatch-backup"
    replacement: Container | None = None

    try:
        client.images.pull(plan.image_ref)
    except DockerException as exc:
        return UpdateExecutionResult(False, "plain", f"image pull failed: {exc}")

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
        command.extend(["-f", file])
    command.extend(args)
    return command


def _execute_compose_update(plan: UpdatePlan, config: DockwatchConfig) -> UpdateExecutionResult:
    if not plan.compose_project or not plan.compose_service:
        return UpdateExecutionResult(False, "compose", "compose project metadata is incomplete")
    project = config.compose_projects.get(plan.compose_project)
    if project is None:
        return UpdateExecutionResult(False, "compose", f"compose project '{plan.compose_project}' is not configured")

    workdir = Path(project.workdir)
    if not workdir.exists():
        return UpdateExecutionResult(False, "compose", f"compose workdir does not exist: {workdir}")

    pull_cmd = _compose_command(project, "pull", plan.compose_service)
    up_cmd = _compose_command(project, "up", "-d", plan.compose_service)

    try:
        pull = subprocess.run(pull_cmd, cwd=workdir, capture_output=True, text=True, check=False)
        if pull.returncode != 0:
            return UpdateExecutionResult(
                False,
                "compose",
                f"compose pull failed for '{plan.compose_service}'",
                details=[pull.stderr.strip() or pull.stdout.strip()],
            )
        up = subprocess.run(up_cmd, cwd=workdir, capture_output=True, text=True, check=False)
        if up.returncode != 0:
            return UpdateExecutionResult(
                False,
                "compose",
                f"compose up failed for '{plan.compose_service}'",
                details=[up.stderr.strip() or up.stdout.strip()],
            )
    except OSError as exc:
        return UpdateExecutionResult(False, "compose", f"failed to run docker compose: {exc}")

    return UpdateExecutionResult(
        True,
        "compose",
        f"updated compose service '{plan.compose_service}'",
        details=["docker compose pull completed", "docker compose up -d completed"],
    )


def execute_update(plan: UpdatePlan, config: DockwatchConfig) -> UpdateExecutionResult:
    if not plan.allowed:
        return UpdateExecutionResult(False, plan.mode, plan.reason or "update is blocked")
    if plan.mode == "compose":
        return _execute_compose_update(plan, config)
    return _execute_plain_update(plan)
