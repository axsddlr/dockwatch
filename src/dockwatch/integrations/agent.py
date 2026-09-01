"""Dockwatch agent integration: a remote agent exposes another host's Docker
daemon through a small token-authenticated API. The central instance uses this
client to discover that host's containers and to proxy update/rollback/restart/
delete/log actions back to the agent (which executes them with the same local
machinery the central uses for its own Docker socket)."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

import httpx

_AGENT_PREFIX = "/api/agent/v1"
_T = TypeVar("_T")

# A single retry after a short backoff for connection-level failures only
# (refused/reset/timed-out connections) -- not for 4xx/5xx application
# errors, which are never transient. Absorbs one flaky moment (agent host
# briefly unreachable, slow TCP handshake) instead of failing an entire
# scheduled check cycle over it.
_RETRYABLE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)
_RETRY_BACKOFF_SECONDS = 1.0


async def _with_retry(call: Callable[[], Awaitable[_T]]) -> _T:
    try:
        return await call()
    except _RETRYABLE:
        await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
        return await call()


class AgentError(RuntimeError):
    """Raised when agent configuration or API access fails."""


class AgentClient:
    def __init__(
        self, *, base_url: str, token: str, timeout: float = 15.0, deploy_timeout: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout
        # Image pulls + container recreates routinely exceed the short
        # per-call timeout, even though the operation succeeds server-side.
        self.deploy_timeout = deploy_timeout
        if not self.base_url:
            raise AgentError("agent URL is not configured")
        if not self.token:
            raise AgentError("agent token is not configured")

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def health(self) -> dict:
        async def _call() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.get(f"{self.base_url}{_AGENT_PREFIX}/health", headers=self._headers)

        try:
            response = await _with_retry(_call)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AgentError(f"agent health request failed: {exc}") from exc
        return self._json_dict(response, "health")

    async def list_containers(self) -> list[dict]:
        async def _call() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.get(f"{self.base_url}{_AGENT_PREFIX}/containers", headers=self._headers)

        try:
            response = await _with_retry(_call)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AgentError(f"agent containers request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise AgentError(f"agent returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("containers"), list):
            raise AgentError("agent containers response was missing the 'containers' list")
        return [item for item in payload["containers"] if isinstance(item, dict)]

    async def update_container(self, container_id: str, image_ref: str) -> dict:
        return await self._action("update", container_id, image_ref)

    async def rollback_container(self, container_id: str, image_ref: str) -> dict:
        return await self._action("rollback", container_id, image_ref)

    async def _action(self, action: str, container_id: str, image_ref: str) -> dict:
        async def _call() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.deploy_timeout) as client:
                return await client.post(
                    f"{self.base_url}{_AGENT_PREFIX}/containers/{container_id}/{action}",
                    headers=self._headers,
                    json={"image_ref": image_ref},
                )

        try:
            response = await _with_retry(_call)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AgentError(f"agent {action} failed for container {container_id}: {exc}") from exc
        return self._json_dict(response, f"{action} response")

    async def restart_container(self, container_id: str) -> None:
        async def _call() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.post(
                    f"{self.base_url}{_AGENT_PREFIX}/containers/{container_id}/restart",
                    headers=self._headers,
                )

        try:
            response = await _with_retry(_call)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AgentError(f"agent restart failed for container {container_id}: {exc}") from exc

    async def delete_container(self, container_id: str, *, force: bool = False) -> None:
        async def _call() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.delete(
                    f"{self.base_url}{_AGENT_PREFIX}/containers/{container_id}",
                    headers=self._headers,
                    params={"force": "true" if force else "false"},
                )

        try:
            response = await _with_retry(_call)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AgentError(f"agent delete failed for container {container_id}: {exc}") from exc

    async def delete_image(self, image_id: str, *, force: bool = False) -> None:
        async def _call() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.delete(
                    f"{self.base_url}{_AGENT_PREFIX}/images/{image_id}",
                    headers=self._headers,
                    params={"force": "true" if force else "false"},
                )

        try:
            response = await _with_retry(_call)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AgentError(f"agent image delete failed for {image_id}: {exc}") from exc

    async def get_logs(self, container_id: str, *, tail: int = 200) -> str:
        async def _call() -> httpx.Response:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.get(
                    f"{self.base_url}{_AGENT_PREFIX}/containers/{container_id}/logs",
                    headers=self._headers,
                    params={"tail": tail},
                )

        try:
            response = await _with_retry(_call)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AgentError(f"agent logs request failed for container {container_id}: {exc}") from exc
        payload = self._json_dict(response, "logs response")
        logs = payload.get("logs")
        if not isinstance(logs, str):
            raise AgentError("agent logs response was missing the 'logs' string")
        return logs

    def _json_dict(self, response: httpx.Response, what: str) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AgentError(f"agent returned invalid JSON for {what}: {exc}") from exc
        if not isinstance(payload, dict):
            raise AgentError(f"agent {what} was not a JSON object")
        return payload
