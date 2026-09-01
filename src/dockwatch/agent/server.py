"""Standalone dockwatch agent server.

Runs on a Docker host (same image as the central instance) and exposes that
host's containers through a small token-authenticated API. The agent is
stateless: discovery reuses the local Docker client, and container actions
reuse the same plain-recreate machinery the central uses for its own socket.
"""

from __future__ import annotations

import hmac
import logging
from typing import Annotated

import docker
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

from .. import __version__
from ..docker_client import DockerConnectionError, get_docker_client, get_running_containers, parse_image_ref
from ..models import ContainerInfo
from ..updater import UpdateExecutionError, UpdatePlan, _execute_plain_update
from .protocol import serialize_container_info

_PREFIX = "/api/agent/v1"
_logger = logging.getLogger(__name__)


class ActionBody(BaseModel):
    image_ref: str


def create_agent_app(token: str) -> FastAPI:
    if not token:
        raise ValueError("agent token must not be empty")
    app = FastAPI(title="dockwatch agent", version=__version__)

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        supplied = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied, token):
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
        return _run_recreate(container_id, body.image_ref)

    @router.post("/containers/{container_id}/rollback")
    def rollback_container(container_id: str, body: ActionBody) -> dict:
        return _run_recreate(container_id, body.image_ref)

    def _run_recreate(container_id: str, image_ref: str) -> dict:
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
        )
        try:
            result = _execute_plain_update(plan)
        except UpdateExecutionError as exc:
            _logger.error("agent: update of '%s' failed: %s", container_id, exc)
            raise HTTPException(status_code=502, detail="container update failed") from exc
        return {
            "ok": result.success,
            "message": result.message,
            "details": result.details,
            "rollback_message": result.rollback_message,
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
        except Exception as exc:  # noqa: BLE001
            _logger.error("agent: delete of image '%s' failed: %s", image_id, exc)
            raise HTTPException(status_code=502, detail="image delete failed") from exc
        finally:
            client.close()
        return {"ok": True}

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
