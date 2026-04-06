from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from dockwatch.models import ContainerInfo, RegistryType
from dockwatch.registry import check_all, check_container, check_dockerhub, check_ghcr


class MockResponse:
    def __init__(self, status_code: int, payload: dict | None = None, url: str = "https://example.test"):
        self.status_code = status_code
        self._payload = payload or {}
        self.request = httpx.Request("GET", url)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self.request, response=httpx.Response(self.status_code))


class MockAsyncClient:
    def __init__(self, responses: list[MockResponse]):
        self._responses = responses
        self.calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, headers: dict | None = None) -> MockResponse:
        self.calls.append((url, headers))
        if not self._responses:
            raise AssertionError(f"no mock response configured for {url}")
        return self._responses.pop(0)


def make_container(*, registry: RegistryType, current_tag: str = "1.0.0") -> ContainerInfo:
    return ContainerInfo(
        name="svc",
        container_id="abc123",
        image_ref="example",
        registry=registry,
        namespace="owner",
        image_name="image",
        current_tag=current_tag,
    )


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_dockerhub_prefers_latest_semver(self) -> None:
        info = make_container(registry=RegistryType.DOCKERHUB, current_tag="1.0.0")
        payload = {
            "results": [
                {"name": "latest", "last_updated": "2026-01-01T00:00:00Z"},
                {"name": "1.1.0", "last_updated": "2026-01-02T00:00:00Z"},
                {"name": "1.2.3", "last_updated": "2026-01-03T00:00:00Z"},
            ]
        }

        mock_client = MockAsyncClient([MockResponse(200, payload)])
        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_dockerhub(info)

        self.assertEqual(result.latest_tag, "1.2.3")
        self.assertTrue(result.is_outdated)
        self.assertIsNone(result.check_error)

    async def test_check_dockerhub_falls_back_to_most_recent_non_floating(self) -> None:
        info = make_container(registry=RegistryType.DOCKERHUB, current_tag="foo")
        payload = {
            "results": [
                {"name": "latest", "last_updated": "2026-01-01T00:00:00Z"},
                {"name": "rolling", "last_updated": "2026-01-03T00:00:00Z"},
            ]
        }

        mock_client = MockAsyncClient([MockResponse(200, payload)])
        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_dockerhub(info)

        self.assertEqual(result.latest_tag, "rolling")
        self.assertTrue(result.is_outdated)

    async def test_check_ghcr_uses_token_and_tags(self) -> None:
        info = make_container(registry=RegistryType.GHCR, current_tag="1.0.0")
        token_payload = {"token": "abc-token"}
        tags_payload = {"tags": ["latest", "1.3.0", "1.2.0"]}

        mock_client = MockAsyncClient(
            [
                MockResponse(200, token_payload, url="https://ghcr.io/token"),
                MockResponse(200, tags_payload, url="https://ghcr.io/v2/owner/image/tags/list"),
            ]
        )
        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_ghcr(info)

        self.assertEqual(result.latest_tag, "1.3.0")
        self.assertTrue(result.is_outdated)
        self.assertIsNone(result.check_error)

        _, second_headers = mock_client.calls[1]
        self.assertEqual(second_headers, {"Authorization": "Bearer abc-token"})

    async def test_check_container_skips_latest_and_digest(self) -> None:
        latest_info = make_container(registry=RegistryType.DOCKERHUB, current_tag="latest")
        digest_info = make_container(registry=RegistryType.DOCKERHUB, current_tag="DIGEST_PINNED")

        latest_result = await check_container(latest_info)
        digest_result = await check_container(digest_info)

        self.assertIsNone(latest_result.is_outdated)
        self.assertIn("skipped", latest_result.check_error or "")
        self.assertIsNone(digest_result.is_outdated)
        self.assertIn("skipped", digest_result.check_error or "")

    async def test_check_all_runs_concurrently(self) -> None:
        infos = [
            make_container(registry=RegistryType.UNKNOWN, current_tag="1.0.0"),
            make_container(registry=RegistryType.UNKNOWN, current_tag="latest"),
        ]

        results = await check_all(infos)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.check_error for result in results))


if __name__ == "__main__":
    unittest.main()