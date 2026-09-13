"""Standalone dockwatch agent server.

Runs on a Docker host (same image as the central instance) and exposes that
host's containers through a small token-authenticated API. The agent is
stateless: discovery reuses the local Docker client, and container actions
reuse the same plain-recreate machinery the central uses for its own socket.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
from collections import defaultdict
from typing import Annotated

import docker
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import __version__, docker_client
from ..config import MAX_HOOK_TIMEOUT_SECONDS, VALID_PRUNE_MODES, DockwatchConfig
from ..docker_client import DockerConnectionError, get_docker_client, get_running_containers, parse_image_ref
from ..models import ContainerInfo
from ..prune import execute_prune, plan_prune
from ..updater import UpdateExecutionError, UpdatePlan, _execute_plain_update
from .protocol import MIN_AGENT_TOKEN_LENGTH, serialize_container_info

_PREFIX = "/api/agent/v1"
_logger = logging.getLogger(__name__)
_AUTH_FAIL_LIMIT = 10
_AUTH_FAIL_WINDOW_SECONDS = 60.0

_EXEC_ENABLE_ENV = "DOCKWATCH_AGENT_ENABLE_EXEC"


def _exec_enabled() -> bool:
    """Whether the exec endpoint is enabled (opt-in, defense in depth).

    The agent is already token-authenticated, but exec is an arbitrary-command
    remote execution primitive, so it stays opt-in behind this environment
    variable independent of the token gate.
    """
    return os.environ.get(_EXEC_ENABLE_ENV, "").strip().lower() == "true"


class ActionBody(BaseModel):
    image_ref: str
    operation: str = "update"


class ExecBody(BaseModel):
    command: str
    timeout_seconds: int = Field(default=60, ge=1, le=MAX_HOOK_TIMEOUT_SECONDS)
    user: str | None = None
    workdir: str | None = None


class PruneBody(BaseModel):
    mode: str = "dangling"
    keep_recent: int = Field(default=3, ge=0)


def create_agent_app(token: str) -> FastAPI:
    if not token:
        raise ValueError("agent token must not be empty")
    if len(token) < MIN_AGENT_TOKEN_LENGTH:
        raise ValueError(f"agent token must be at least {MIN_AGENT_TOKEN_LENGTH} characters")
    app = FastAPI(title="dockwatch agent", version=__version__)

    auth_failures: dict[str, list[float]] = defaultdict(list)

    def _locked_out(client_ip: str) -> bool:
        now = time.monotonic()
        attempts = [t for t in auth_failures[client_ip] if now - t < _AUTH_FAIL_WINDOW_SECONDS]
        auth_failures[client_ip] = attempts
        return len(attempts) >= _AUTH_FAIL_LIMIT

    def require_token(
        request: Request, authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        client_ip = request.client.host if request.client else "unknown"
        if _locked_out(client_ip):
            raise HTTPException(status_code=429, detail="too many failed auth attempts")
        if authorization is None or not authorization.startswith("Bearer "):
            auth_failures[client_ip].append(time.monotonic())
            raise HTTPException(status_code=401, detail="missing bearer token")
        supplied = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied, token):
            auth_failures[client_ip].append(time.monotonic())
            raise HTTPException(status_code=401, detail="invalid agent token")

    router = APIRouter(prefix=_PREFIX, dependencies=[Depends(require_token)])

    def _open_client() -> docker.DockerClient:
        try:
            return get_docker_client()
        except DockerConnectionError as exc:
            _logger.error("agent: docker connection failed: %s", exc)
            raise HTTPException(status_code=502, detail="docker connection failed") from exc

    def _lookup(
        client: docker.DockerClient, container_id: str,
    ) -> tuple[ContainerInfo, docker.models.containers.Container] | None:
        try:
            container = client.containers.get(container_id)
        except docker.errors.NotFound:
            return None
        attrs = container.attrs
        config = attrs.get("Config", {}) or {}
        labels = dict(config.get("Labels", {}) or {})
        image_attrs = container.image.attrs if container.image else {}
        image_attrs = dict(image_attrs) if image_attrs else {}
        repo_digests = image_attrs.get("RepoDigests", []) or []
        image_ref = config.get("Image") or ""
        info = parse_image_ref(
            image_ref,
            name=(container.name or ""),
            container_id=(container.id or "")[:12],
            labels=labels,
            compose_image_digest=labels.get("com.docker.compose.image"),
            repo_digest=repo_digests[0] if repo_digests else None,
        )
        return info, container

    def _require_container(
        client: docker.DockerClient, container_id: str,
    ) -> tuple[ContainerInfo, docker.models.containers.Container]:
        found = _lookup(client, container_id)
        if found is None:
            raise HTTPException(status_code=404, detail=f"container '{container_id}' not found")
        return found

    @router.get("/health")
    def health() -> dict:
        docker_ok = "ok"
        try:
            client = get_docker_client()
            try:
                client.ping()
            finally:
                client.close()
        except Exception:  # noqa: BLE001
            docker_ok = "error"
        return {"ok": True, "version": __version__, "docker": docker_ok}

    @router.get("/containers")
    def list_containers() -> dict:
        try:
            infos = get_running_containers()
        except DockerConnectionError as exc:
            _logger.error("agent: list containers failed: %s", exc)
            raise HTTPException(status_code=502, detail="docker connection failed") from exc
        return {"containers": [serialize_container_info(info) for info in infos]}

    @router.post("/containers/{container_id}/update")
    def update_container(container_id: str, body: ActionBody) -> dict:
        return _run_recreate(container_id, body.image_ref, operation="update")

    @router.post("/containers/{container_id}/rollback")
    def rollback_container(container_id: str, body: ActionBody) -> dict:
        return _run_recreate(container_id, body.image_ref, operation="rollback")

    def _run_recreate(container_id: str, image_ref: str, *, operation: str = "update") -> dict:
        target = image_ref.strip()
        if not target:
            raise HTTPException(status_code=422, detail="image_ref must not be empty")
        client = _open_client()
        try:
            info, _container = _require_container(client, container_id)
        finally:
            client.close()
        if info.compose_project and info.compose_service:
            raise HTTPException(
                status_code=422,
                detail="compose-managed containers cannot be updated through an agent (v1); "
                "manage them on the agent host directly",
            )
        plan = UpdatePlan(
            container_name=info.name,
            container_id=info.container_id,
            source="local",
            mode="plain",
            allowed=True,
            image_ref=target,
            deployed_display=info.current_tag or "-",
            remote_display=target,
            operation=operation,
        )
        try:
            # No hook_runner is passed here: for an agent-managed container the
            # central already ran the hooks via AgentClient.exec_container. If the
            # agent re-ran label-based hooks here (it can see labels even though
            # it has no config file), they would fire a second time.
            result = _execute_plain_update(plan)
        except UpdateExecutionError as exc:
            _logger.error("agent: update of '%s' failed: %s", container_id, exc)
            raise HTTPException(status_code=502, detail="container update failed") from exc
        return {
            "ok": result.success,
            "message": result.message,
            "details": result.details,
            "rollback_message": result.rollback_message,
            "operation": operation,
        }

    @router.post("/containers/{container_id}/restart")
    def restart_container(container_id: str) -> dict:
        client = _open_client()
        try:
            _info, container = _require_container(client, container_id)
            container.restart(timeout=10)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            _logger.error("agent: restart of '%s' failed: %s", container_id, exc)
            raise HTTPException(status_code=502, detail="restart failed") from exc
        finally:
            client.close()
        return {"ok": True}

    @router.post("/containers/{container_id}/exec")
    def exec_container(container_id: str, body: ExecBody) -> dict:
        if not _exec_enabled():
            raise HTTPException(
                status_code=422,
                detail="exec is disabled (set DOCKWATCH_AGENT_ENABLE_EXEC=true)",
            )
        command = body.command.strip()
        if not command:
            raise HTTPException(status_code=422, detail="command must not be empty")
        client = _open_client()
        try:
            _info, _container = _require_container(client, container_id)
            result = docker_client.exec_in_container(
                container_id,
                command,
                timeout_seconds=body.timeout_seconds,
                user=body.user,
                workdir=body.workdir,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            _logger.error("agent: exec in '%s' failed: %s", container_id, exc)
            raise HTTPException(status_code=502, detail="exec failed") from exc
        finally:
            client.close()
        return {
            "exit_code": result.exit_code,
            "output": result.output,
            "truncated": result.truncated,
        }

    @router.delete("/containers/{container_id}")
    def delete_container(container_id: str, force: bool = Query(default=False)) -> dict:
        client = _open_client()
        try:
            _info, container = _require_container(client, container_id)
            container.remove(force=force)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            _logger.error("agent: delete of container '%s' failed: %s", container_id, exc)
            raise HTTPException(status_code=502, detail="delete failed") from exc
        finally:
            client.close()
        return {"ok": True}

    @router.delete("/images/{image_id}")
    def delete_image(image_id: str, force: bool = Query(default=False)) -> dict:
        client = _open_client()
        try:
            client.images.remove(image_id, force=force)
        except docker.errors.ImageNotFound as exc:
            raise HTTPException(status_code=404, detail=f"image '{image_id}' not found") from exc
        except Exception as exc:  # noqa: BLE001
            _logger.error("agent: delete of image '%s' failed: %s", image_id, exc)
            raise HTTPException(status_code=502, detail="image delete failed") from exc
        finally:
            client.close()
        return {"ok": True}

    @router.post("/images/prune")
    async def prune_images(body: PruneBody) -> dict:
        if body.mode not in VALID_PRUNE_MODES:
            raise HTTPException(status_code=422, detail=f"mode must be one of {sorted(VALID_PRUNE_MODES)}")
        try:
            images = await asyncio.to_thread(docker_client.list_images)
            in_use = await asyncio.to_thread(docker_client.in_use_image_ids)
        except Exception as exc:  # noqa: BLE001
            _logger.error("agent: image prune listing failed: %s", exc)
            raise HTTPException(status_code=502, detail="docker connection failed") from exc

        preview = plan_prune(images, in_use, mode=body.mode, keep_recent=body.keep_recent)
        # The agent is stateless: no config file and no notifiers, so it passes a
        # bare config (prune.notify defaults False) and no audit store. It runs the
        # exact same retention-guarded algorithm the central uses for its own socket.
        config = DockwatchConfig()
        try:
            result = await execute_prune(preview, config=config, store=None, source="local")
        except Exception as exc:  # noqa: BLE001
            _logger.error("agent: image prune failed: %s", exc)
            raise HTTPException(status_code=502, detail="image prune failed") from exc

        # Never return raw Docker daemon exception text over the network: log it
        # here and hand back a generic per-image reason, mirroring the sibling
        # delete/restart/exec endpoints' 502 detail.
        failed: list[tuple[str, str]] = []
        for image_id, error in result.failed:
            _logger.error("agent: prune removal of '%s' failed: %s", image_id, error)
            failed.append((image_id, "removal failed"))
        return {
            "ok": True,
            "removed": result.removed,
            "failed": failed,
            "reclaimed_bytes": result.reclaimed_bytes,
        }

    @router.get("/containers/{container_id}/logs")
    def container_logs(container_id: str, tail: int = Query(default=200, ge=1, le=2000)) -> dict:
        client = _open_client()
        try:
            _info, container = _require_container(client, container_id)
            logs = container.logs(tail=tail, timestamps=True)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            _logger.error("agent: logs request for '%s' failed: %s", container_id, exc)
            raise HTTPException(status_code=502, detail="logs request failed") from exc
        finally:
            client.close()
        return {"logs": _decode_logs(logs)}

    app.include_router(router)
    return app


def _decode_logs(logs: bytes | str) -> str:
    if isinstance(logs, bytes):
        return logs.decode("utf-8", errors="replace")
    return logs
