"""Docker client utilities for container discovery and image parsing."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import lru_cache

import docker
from docker.errors import DockerException

from .config import ComposeProjectConfig
from .models import ContainerInfo, RegistryType
from .utils import parse_bool, unique_ordered

DIGEST_PINNED_TAG = "DIGEST_PINNED"

# Exec output is capped at 8 KiB; hook output is rendered into audit rows and
# notifications, so a noisy command must not be able to carry an unbounded
# payload around with it.
EXEC_OUTPUT_LIMIT = 8192

# Seconds the timeout path gives the worker thread to stop after the exec
# stream is closed before raising anyway. CancellableStream.close() normally
# unblocks the worker immediately, but a transport edge can leave it stuck;
# the deadline must still hold even if the worker then outlives the call.
_EXEC_WORKER_JOIN_GRACE_SECONDS = 1.0


@dataclass(slots=True)
class ExecResult:
    """Outcome of a command executed inside a local container."""

    exit_code: int
    output: str
    truncated: bool


@dataclass(slots=True)
class ImageInfo:
    """Summary of one local Docker image."""

    image_id: str
    repo_tags: list[str]
    created: int
    size_bytes: int


class DockerConnectionError(RuntimeError):
    """Raised when the Docker daemon cannot be reached."""


def get_docker_client() -> docker.DockerClient:
    """Create a Docker client from the environment (socket or context)."""
    return docker.from_env()


def _parse_label_flag(labels: dict[str, str], key: str) -> bool | None:
    return parse_bool(labels.get(key), None)


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
    return unique_ordered(items)


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


def _parse_label_int(labels: dict[str, str], key: str) -> int | None:
    raw_value = labels.get(key)
    if raw_value is None:
        return None
    try:
        return int(str(raw_value).strip())
    except ValueError:
        return None


def _tag_override_kwargs(labels: dict[str, str]) -> dict[str, list[str] | int | None]:
    return {
        "include_tags_override": _parse_label_list(labels, "dockwatch.include_tags"),
        "exclude_tags_override": _parse_label_list(labels, "dockwatch.exclude_tags"),
        "update_delay_days_override": _parse_label_int(labels, "dockwatch.update_delay_days"),
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
    state: str | None = None,
    health_status: str | None = None,
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
        health_restart_override=_parse_label_flag(labels, "dockwatch.health.auto_restart"),
        compose_project=labels.get("com.docker.compose.project"),
        compose_service=labels.get("com.docker.compose.service"),
        source=source,
        state=state,
        health_status=health_status,
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
    state: str | None = None,
    health_status: str | None = None,
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
            state=state,
            health_status=health_status,
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
            state=state,
            health_status=health_status,
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
            state=state,
            health_status=health_status,
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
        state=state,
        health_status=health_status,
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
        client = get_docker_client()
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
        client = get_docker_client()
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
                state_attrs = container.attrs.get("State", {}) or {}
            except DockerException:
                continue
            repo_digests = image_attrs.get("RepoDigests", []) or []
            repo_digest = repo_digests[0] if repo_digests else None
            image_ref = (
                config.get("Image")
                or ""
            )
            # Docker inspect shape: State.Status, plus State.Health.Status only
            # when the image declares a HEALTHCHECK. Absent Health (the common
            # case) must stay None -- never "none" and never a KeyError. Raw
            # values are passed through unvalidated.
            raw_state = state_attrs.get("Status")
            state = str(raw_state) if raw_state is not None else None
            health_attrs = state_attrs.get("Health") or {}
            raw_health = health_attrs.get("Status")
            health_status = str(raw_health) if raw_health is not None else None
            info = parse_image_ref(
                image_ref,
                name=(container.name or ""),
                container_id=(container.id or "")[:12],
                labels=labels,
                compose_image_digest=labels.get("com.docker.compose.image"),
                repo_digest=repo_digest,
                state=state,
                health_status=health_status,
            )
            containers.append(info)

        return containers
    finally:
        client.close()


def get_image_id(container_name: str) -> str | None:
    """Return the Docker image ID for a running container by name."""
    try:
        client = get_docker_client()
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
    client = get_docker_client()
    try:
        container = client.containers.get(name)
        container.remove(force=force)
    finally:
        client.close()


def delete_image(image_id: str, *, force: bool = False) -> None:
    """Remove a local image by ID. Raises DockerException if the image is
    still in use by another container and `force` is not set."""
    client = get_docker_client()
    try:
        client.images.remove(image_id, force=force)
    finally:
        client.close()


def get_logs(name: str, *, tail: int = 200) -> str:
    """Return the last `tail` lines of a local container's logs.

    Raises DockerException if the container is not found.
    """
    client = get_docker_client()
    try:
        container = client.containers.get(name)
        raw = container.logs(tail=tail, timestamps=True)
        return raw.decode("utf-8", errors="replace")
    finally:
        client.close()


def restart_container(name: str, *, timeout: int = 10) -> None:
    """Restart a local container by name or ID.

    `timeout` is how many seconds Docker waits for the container to stop
    before killing it. Raises DockerException on failure (not found, daemon
    refuses to restart, etc.) so the caller can surface a specific error.
    """
    client = get_docker_client()
    try:
        container = client.containers.get(name)
        container.restart(timeout=timeout)
    finally:
        client.close()


def _exec_start_with_timeout(
    client: docker.DockerClient, exec_id: str, timeout_seconds: int
) -> tuple[bytes, bool]:
    """Start `exec_id` and collect its output, giving up after `timeout_seconds`.

    docker-py has no timeout for exec: neither `APIClient.exec_start` nor the
    Engine's ``POST /exec/{id}/start`` accepts one, so the deadline is enforced
    on our side. `exec_start(stream=True)` returns a `CancellableStream`; a
    worker thread drains it one frame at a time while the caller joins the
    worker with a timeout.

    Output is retained up to `EXEC_OUTPUT_LIMIT` bytes; once that budget is
    filled the worker keeps consuming the stream and *discards* the surplus
    until EOF rather than stopping early. This keeps the retained memory
    bounded while still letting the caller's `exec_inspect` observe the real
    exit code (stopping early would leave the command running, report
    ``ExitCode=None`` → ``-1``, and risk killing it when the stream is closed
    mid-flight).

    On expiry the caller calls `stream.close()`, which shuts down and closes
    the underlying socket and so unblocks the worker's blocked read, then joins
    the worker for a short grace period and raises regardless of whether the
    worker stopped. Docker exposes no way to cancel a running exec, so after a
    timeout the in-container process keeps running until it exits on its own;
    only our read of its output is abandoned.

    Returns ``(output, truncated)`` where ``output`` is at most
    `EXEC_OUTPUT_LIMIT` bytes and ``truncated`` reports whether the command
    produced more.
    """
    stream = client.api.exec_start(exec_id, stream=True)
    output = bytearray()
    truncated = False
    failure: list[Exception] = []

    def _run() -> None:
        nonlocal truncated
        try:
            for frame in stream:
                remaining = EXEC_OUTPUT_LIMIT - len(output)
                if remaining <= 0:
                    # Budget already filled: keep consuming to EOF so the
                    # caller's exec_inspect sees the command finish and reports
                    # its real exit code, but discard the surplus.
                    truncated = True
                    continue
                if len(frame) > remaining:
                    truncated = True
                    frame = frame[:remaining]
                output.extend(frame)
        except Exception as exc:  # noqa: BLE001 -- re-raised on the caller's thread
            failure.append(exc)

    worker = threading.Thread(target=_run, name="dockwatch-exec", daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        # The command outlived its deadline. Closing the stream shuts down the
        # socket, which normally unblocks the worker's read and lets the thread
        # finish; the daemon-side exec keeps running unattended. If close()
        # fails to unblock the worker (a transport edge), the bounded join below
        # still returns and we raise anyway -- in that case the worker thread
        # may outlive this call.
        stream.close()
        worker.join(_EXEC_WORKER_JOIN_GRACE_SECONDS)
        raise DockerException(f"Docker exec timed out after {timeout_seconds}s")
    # The worker finished: the stream was drained to EOF (the byte budget only
    # causes surplus frames to be discarded, never an early stop) or it hit a
    # read error stored in `failure`. Closing is a harmless no-op at EOF and
    # releases the socket on the error path.
    stream.close()
    if failure:
        raise failure[0]
    return bytes(output), truncated


def exec_in_container(
    name: str,
    command: str,
    *,
    timeout_seconds: int = 60,
    user: str | None = None,
    workdir: str | None = None,
) -> ExecResult:
    """Run a shell command inside a local container and capture its output.

    Uses the low-level exec API rather than `container.exec_run` so the
    deadline and the full result (exit code, stderr merged into stdout,
    truncation flag) stay under our control. Output is decoded like
    `get_logs` and capped at EXEC_OUTPUT_LIMIT bytes, keeping the head.

    The timeout is enforced client-side: Docker exposes no way to cancel a
    running exec, so after a timeout the in-container process may still be
    running while we abandon our read of its output.

    Raises DockerException on failure (container not found, the command
    outlived `timeout_seconds`, daemon error) so the caller can surface it.
    """
    client = get_docker_client()
    try:
        create_kwargs: dict[str, object] = {
            "cmd": ["/bin/sh", "-lc", command],
            "stdout": True,
            "stderr": True,
        }
        # Some Docker API versions reject an empty-string user, so only send
        # these when the caller actually asked for them.
        if user:
            create_kwargs["user"] = user
        if workdir:
            create_kwargs["workdir"] = workdir

        exec_id = client.api.exec_create(name, **create_kwargs)["Id"]
        raw, truncated = _exec_start_with_timeout(client, exec_id, timeout_seconds)
        inspect = client.api.exec_inspect(exec_id)

        exit_code = inspect["ExitCode"]
        output = raw.decode("utf-8", errors="replace")
        return ExecResult(
            exit_code=-1 if exit_code is None else int(exit_code),
            output=output,
            truncated=truncated,
        )
    finally:
        client.close()


def list_images() -> list[ImageInfo]:
    """Return local Docker images as lightweight summaries.

    Raises DockerException if the daemon cannot be reached.
    """
    client = get_docker_client()
    try:
        images: list[ImageInfo] = []
        for image in client.images.list():
            attrs = image.attrs or {}
            image_id = str(image.id or "")
            if not image_id:
                # A record with no ID cannot be removed later, so it is not
                # worth handing to a caller that prunes by ID.
                continue
            try:
                created = int(attrs.get("Created"))
            except (TypeError, ValueError):
                created = 0
            repo_tags = attrs.get("RepoTags") or []
            images.append(
                ImageInfo(
                    image_id=image_id,
                    repo_tags=list(repo_tags),
                    created=created,
                    size_bytes=int(attrs.get("Size") or 0),
                )
            )
        return images
    finally:
        client.close()


def in_use_image_ids() -> set[str]:
    """Return the image id of every container (running *or* stopped).

    Normalization matches :func:`list_images`: both keep the ``sha256:``
    prefix Docker reports, so an id returned here compares directly against
    ``ImageInfo.image_id``. A container whose image has already been removed
    (so ``container.image`` resolves to ``None`` or fails) contributes nothing,
    because it cannot be using an image that is itself missing.
    """
    client = get_docker_client()
    try:
        ids: set[str] = set()
        for container in client.containers.list(all=True):
            try:
                image = container.image
            except DockerException:
                continue
            if image is None:
                continue
            image_id = image.id
            if image_id:
                ids.add(str(image_id))
        return ids
    finally:
        client.close()


def remove_image(image_id: str) -> None:
    """Remove a local image by ID without forcing it.

    Never forces, so pruning fails safely instead of ripping an image out
    from under a container that is still using it. Raises DockerException
    when the image is missing or in use.
    """
    client = get_docker_client()
    try:
        client.images.remove(image_id)
    finally:
        client.close()
