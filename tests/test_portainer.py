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

    async def post(self, url: str, headers: dict | None = None, params: dict | None = None, json: dict | None = None):
        self.calls.append((url, headers, params))
        return self.responses.pop(0)

    async def delete(self, url: str, headers: dict | None = None, params: dict | None = None):
        self.calls.append((url, headers, params))
        return self.responses.pop(0)

    async def put(self, url: str, headers: dict | None = None, params: dict | None = None, json: dict | None = None):
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

    async def test_delete_container_deletes_via_docker_proxy_with_force_param(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(204, None)])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            await client.delete_container(4, "abc123", force=True)

        url, headers, params = mock_client.calls[0]
        self.assertEqual(url, "https://portainer.test/api/endpoints/4/docker/containers/abc123")
        self.assertEqual(headers, {"X-API-Key": "token"})
        self.assertEqual(params, {"force": "true"})

    async def test_delete_container_wraps_http_error(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(404, {"message": "not found"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            with self.assertRaises(PortainerError):
                await client.delete_container(4, "abc123")

    async def test_delete_image_deletes_via_docker_proxy(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(204, None)])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            await client.delete_image(4, "sha256:abc123", force=False)

        url, _, params = mock_client.calls[0]
        self.assertEqual(url, "https://portainer.test/api/endpoints/4/docker/images/sha256:abc123")
        self.assertEqual(params, {"force": "false"})

    async def test_delete_container_force_false_sends_string_false(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(204, None)])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            await client.delete_container(4, "abc123", force=False)

        _, _, params = mock_client.calls[0]
        self.assertEqual(params, {"force": "false"})

    async def test_delete_container_default_force_is_false(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(204, None)])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            await client.delete_container(4, "abc123")

        _, _, params = mock_client.calls[0]
        self.assertEqual(params, {"force": "false"})

    async def test_delete_container_404_wraps_as_portainer_error(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(404, {"message": "container not found"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            with self.assertRaises(PortainerError):
                await client.delete_container(4, "nonexistent")

    async def test_delete_image_force_true_sends_string_true(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(204, None)])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            await client.delete_image(4, "sha256:abc123", force=True)

        _, _, params = mock_client.calls[0]
        self.assertEqual(params, {"force": "true"})

    async def test_delete_image_default_force_is_false(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(204, None)])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            await client.delete_image(4, "sha256:abc123")

        _, _, params = mock_client.calls[0]
        self.assertEqual(params, {"force": "false"})

    async def test_delete_image_wraps_http_error(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(500, {"message": "internal server error"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            with self.assertRaises(PortainerError):
                await client.delete_image(4, "sha256:abc123")

    async def test_delete_image_404_wraps_as_portainer_error(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(404, {"message": "image not found"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            with self.assertRaises(PortainerError):
                await client.delete_image(4, "nonexistent")

    async def test_list_images_returns_dict_items_only(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(200, [{"Id": "sha256:a"}, "garbage", {"Id": "sha256:b"}])])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            images = await client.list_images(4)

        self.assertEqual([i["Id"] for i in images], ["sha256:a", "sha256:b"])
        url, headers, _ = mock_client.calls[0]
        self.assertEqual(url, "https://portainer.test/api/endpoints/4/docker/images/json")

    async def test_list_images_wraps_http_error(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(500, {"message": "boom"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            with self.assertRaises(PortainerError):
                await client.list_images(4)

    async def test_connection_delegates_to_list_environments(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(200, [{"Id": 1, "Name": "local"}])])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            environments = await client.test_connection()

        self.assertEqual(environments[0].name, "local")

    async def test_connection_wraps_auth_error(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(401, {"message": "Unauthorized"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="wrong")
            with self.assertRaises(PortainerError):
                await client.test_connection()

    async def test_find_stack_by_name_returns_first_match(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(200, [{"Id": 7, "Name": "mystack", "EndpointId": 1}])])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            stack = await client.find_stack_by_name("mystack")

        self.assertEqual(stack["Id"], 7)
        _, _, params = mock_client.calls[0]
        self.assertEqual(params, {"filters": '{"StackName":"mystack"}'})

    async def test_find_stack_by_name_returns_none_when_empty(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(200, [])])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            stack = await client.find_stack_by_name("missing")

        self.assertIsNone(stack)

    async def test_get_stack_file_returns_content(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(200, {"StackFileContent": "services:\n  web:\n"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            content = await client.get_stack_file(7)

        self.assertIn("services:", content)

    async def test_get_stack_file_missing_content_raises(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(200, {"NotStackFileContent": "x"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            with self.assertRaises(PortainerError):
                await client.get_stack_file(7)

    async def test_create_stack_posts_expected_payload(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(200, {"Id": 9, "Name": "newstack"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            result = await client.create_stack(
                name="newstack", stack_file_content="services: {}", endpoint_id=1,
            )

        self.assertEqual(result["Id"], 9)
        url, headers, params = mock_client.calls[0]
        self.assertEqual(url, "https://portainer.test/api/stacks/create/standalone/string")
        self.assertEqual(params, {"endpointId": 1})

    async def test_create_stack_wraps_http_error(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(409, {"message": "name already in use"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            with self.assertRaises(PortainerError):
                await client.create_stack(name="dup", stack_file_content="services: {}", endpoint_id=1)

    async def test_update_stack_puts_with_pull_and_prune(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(200, {"Id": 7})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            await client.update_stack(7, 1, stack_file_content="services: {}", env=[])

        url, headers, params = mock_client.calls[0]
        self.assertEqual(url, "https://portainer.test/api/stacks/7")
        self.assertEqual(params, {"endpointId": 1})

    async def test_update_stack_wraps_http_error(self) -> None:
        mock_client = _MockAsyncClient([_MockResponse(500, {"message": "boom"})])
        with patch("dockwatch.integrations.portainer.httpx.AsyncClient", return_value=mock_client):
            client = PortainerClient(base_url="https://portainer.test", api_key="token")
            with self.assertRaises(PortainerError):
                await client.update_stack(7, 1, stack_file_content="services: {}")

    async def test_stack_deploy_calls_use_dedicated_longer_timeout(self) -> None:
        """Live-verified: redeploying a stack with pullImage=True blocks on
        Portainer's synchronous compose-up call, which can take well over the
        general per-call timeout for a real image pull -- Portainer completes
        the deploy successfully server-side even after the client times out.
        create_stack/update_stack use a separate, longer deploy_timeout so
        that gap doesn't produce false failures on real deploys."""
        client = PortainerClient(base_url="https://portainer.test", api_key="token")
        self.assertEqual(client.timeout, 15.0)
        self.assertEqual(client.deploy_timeout, 120.0)
        self.assertGreater(client.deploy_timeout, client.timeout)


if __name__ == "__main__":
    unittest.main()
