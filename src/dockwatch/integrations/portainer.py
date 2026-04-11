"""Read-only Portainer integration."""

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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/endpoints", headers=self._headers)
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerError(f"portainer environments request failed: {exc}") from exc
        payload = response.json()
        if not isinstance(payload, list):
            raise PortainerError("portainer environments response was not a list")
        environments: list[PortainerEnvironment] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            environments.append(
                PortainerEnvironment(
                    id=int(item.get("Id")),
                    name=str(item.get("Name") or f"Environment {item.get('Id')}"),
                    url=str(item.get("URL")) if item.get("URL") else None,
                    group_id=int(item["GroupId"]) if item.get("GroupId") is not None else None,
                    status=int(item["Status"]) if item.get("Status") is not None else None,
                )
            )
        return environments

    async def list_containers(self, endpoint_id: int) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/endpoints/{endpoint_id}/docker/containers/json",
                headers=self._headers,
                params={"all": "true"},
            )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PortainerError(
                f"portainer containers request failed for environment {endpoint_id}: {exc}"
            ) from exc
        payload = response.json()
        if not isinstance(payload, list):
            raise PortainerError("portainer containers response was not a list")
        return [item for item in payload if isinstance(item, dict)]

    async def test_connection(self) -> list[PortainerEnvironment]:
        return await self.list_environments()
