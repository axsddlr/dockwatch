from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from dockwatch.integrations.portainer import PortainerClient, PortainerError


class _MockResponse:
    def __init__(self, status_code: int, payload, url: str = "https://portainer.test/api/endpoints") -> None:
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("GET", url)

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self.request, response=httpx.Response(self.status_code))


class _MockAsyncClient:
    def __init__(self, responses: list[_MockResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict | None, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, headers: dict | None = None, params: dict | None = None):
        self.calls.append((url, headers, params))
        return self.responses.pop(0)

    async def post(self, url: str, headers: dict | None = None, params: dict | None = None):
        self.calls.append((url, headers, params))
        return self.responses.pop(0)


class PortainerTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_environments_uses_api_key_header(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(200, [{"Id": 1, "Name": "local"}])])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            environments = await client.list_environments()

        self.assertEqual(environments[0].id, 1)
        self.assertEqual(mock_client.calls[0][1], {"X-API-Key": "token"})

    async def test_list_containers_passes_all_true(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(200, [{"Id": "abc"}])])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            payload = await client.list_containers(4)

        self.assertEqual(len(payload), 1)
        self.assertEqual(mock_client.calls[0][2], {"all": "true"})

    async def test_http_error_is_wrapped(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(401, {"message": "Unauthorized"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            with self.assertRaises(PortainerError):
                await client.list_environments()

    async def test_restart_container_posts_to_docker_proxy(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(204, None)])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            await client.restart_container(4, "abc123")

        url, headers, _ = mock_client.calls[0]
        self.assertEqual(url, "https://portainer.test/api/endpoints/4/docker/containers/abc123/restart")
        self.assertEqual(headers, {"X-API-Key": "token"})

    async def test_restart_container_wraps_http_error(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(404, {"message": "not found"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            with self.assertRaises(PortainerError):
                await client.restart_container(4, "abc123")


if __name__ == "__main__":
    unittest.main()
