"""Portainer integration: read-only discovery plus a small set of write actions
(currently just container restart) proxied through Portainer's Docker API."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class PortainerError(RuntimeError):
    """Raised when Portainer configuration or API access fails."""


@dataclass(slots=True)
class PortainerEnvironment:
    id: int
    name: str
    url: str | None = None
    group_id: int | None = None
    status: int | None = None


class PortainerClient:
    def __init__(self, *, base_url: str, api_key: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        if not self.base_url:
            raise PortainerError("portainer URL is not configured")
        if not self.api_key:
            raise PortainerError("portainer API key is not configured")

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    async def list_environments(self) -> list[PortainerEnvironment]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/api/endpoints", headers=self._headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerError(f"portainer environments request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise PortainerError(f"portainer returned invalid JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise PortainerError("portainer environments response was not a list")
        environments: list[PortainerEnvironment] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("Id")
            if raw_id is None:
                continue
            environments.append(
                PortainerEnvironment(
                    id=int(raw_id),
                    name=str(item.get("Name") or f"Environment {raw_id}"),
                    url=str(item.get("URL")) if item.get("URL") else None,
                    group_id=int(item["GroupId"]) if item.get("GroupId") is not None else None,
                    status=int(item["Status"]) if item.get("Status") is not None else None,
                )
            )
        return environments

    async def list_containers(self, endpoint_id: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/endpoints/{endpoint_id}/docker/containers/json",
                    headers=self._headers,
                    params={"all": "true"},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerError(
                f"portainer containers request failed for environment {endpoint_id}: {exc}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise PortainerError(f"portainer returned invalid JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise PortainerError("portainer containers response was not a list")
        return [item for item in payload if isinstance(item, dict)]

    async def test_connection(self) -> list[PortainerEnvironment]:
        return await self.list_environments()

    async def restart_container(self, endpoint_id: int, container_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/endpoints/{endpoint_id}/docker/containers/{container_id}/restart",
                    headers=self._headers,
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerError(
                f"portainer restart request failed for container {container_id} on environment {endpoint_id}: {exc}"
            ) from exc

    async def delete_container(self, endpoint_id: int, container_id: str, *, force: bool = False) -> None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.delete(
                    f"{self.base_url}/api/endpoints/{endpoint_id}/docker/containers/{container_id}",
                    headers=self._headers,
                    params={"force": "true" if force else "false"},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerError(
                f"portainer delete request failed for container {container_id} on environment {endpoint_id}: {exc}"
            ) from exc

    async def delete_image(self, endpoint_id: int, image_id: str, *, force: bool = False) -> None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.delete(
                    f"{self.base_url}/api/endpoints/{endpoint_id}/docker/images/{image_id}",
                    headers=self._headers,
                    params={"force": "true" if force else "false"},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerError(
                f"portainer delete request failed for image {image_id} on environment {endpoint_id}: {exc}"
            ) from exc
