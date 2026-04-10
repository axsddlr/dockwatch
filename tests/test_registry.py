from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from dockwatch.config import DockwatchConfig
from dockwatch.models import ContainerInfo, RegistryType
from dockwatch.registry import _compile_tag_patterns, _select_latest_from_tags, check_all, check_container, check_dockerhub, check_ghcr


class MockResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict | None = None,
        url: str = "https://example.test",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self._payload = payload or {}
        self.request = httpx.Request("GET", url)
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self.request, response=httpx.Response(self.status_code))


class MockAsyncClient:
    def __init__(self, responses: list[MockResponse]):
        self._responses = responses
        self.calls: list[tuple[str, dict | None]] = []
        self.enter_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, headers: dict | None = None) -> MockResponse:
        self.calls.append((url, headers))
        if not self._responses:
            raise AssertionError(f"no mock response configured for {url}")
        return self._responses.pop(0)

    async def head(self, url: str, headers: dict | None = None) -> MockResponse:
        self.calls.append((url, headers))
        if not self._responses:
            raise AssertionError(f"no mock response configured for HEAD {url}")
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
    def test_select_latest_from_tags_honors_include_regex(self) -> None:
        include_patterns, error = _compile_tag_patterns([r"^1\."])
        self.assertIsNone(error)

        latest = _select_latest_from_tags(
            ["latest", "1.2.0", "2.0.0"],
            include_patterns=include_patterns,
            exclude_patterns=[],
        )

        self.assertEqual(latest, "1.2.0")

    def test_select_latest_from_tags_honors_exclude_regex(self) -> None:
        exclude_patterns, error = _compile_tag_patterns([r"-rc$"])
        self.assertIsNone(error)

        latest = _select_latest_from_tags(
            ["latest", "1.2.0-rc", "1.1.0"],
            include_patterns=[],
            exclude_patterns=exclude_patterns,
        )

        self.assertEqual(latest, "1.1.0")

    async def test_check_dockerhub_returns_unknown_for_invalid_tag_regex(self) -> None:
        info = make_container(registry=RegistryType.DOCKERHUB, current_tag="1.0.0")

        result = await check_dockerhub(info, config=DockwatchConfig(include_tags=["["]))

        self.assertIsNone(result.is_outdated)
        self.assertIn("invalid tag regex", result.check_error or "")

    async def test_check_dockerhub_retries_transient_status(self) -> None:
        info = make_container(registry=RegistryType.DOCKERHUB, current_tag="1.0.0")
        token_payload = {"token": "dh-token"}
        tags_payload = {"tags": ["1.2.0"]}

        mock_client = MockAsyncClient(
            [
                MockResponse(503, {}, url="https://auth.docker.io/token"),
                MockResponse(200, token_payload, url="https://auth.docker.io/token"),
                MockResponse(200, tags_payload, url="https://registry-1.docker.io/v2/owner/image/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://registry-1.docker.io/v2/owner/image/manifests/1.2.0",
                    headers={"Docker-Content-Digest": "sha256:dh-digest"},
                ),
            ]
        )

        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_dockerhub(info, config=DockwatchConfig())

        self.assertEqual(result.latest_tag, "1.2.0")
        self.assertTrue(result.is_outdated)
        self.assertIsNone(result.check_error)

    async def test_container_label_tag_filters_override_config(self) -> None:
        info = ContainerInfo(
            name="svc",
            container_id="abc123",
            image_ref="example",
            registry=RegistryType.DOCKERHUB,
            namespace="owner",
            image_name="image",
            current_tag="1.0.0",
            include_tags_override=[r"^2\."],
            exclude_tags_override=[],
        )
        token_payload = {"token": "dh-token"}
        tags_payload = {"tags": ["1.2.0", "2.1.0"]}

        mock_client = MockAsyncClient(
            [
                MockResponse(200, token_payload, url="https://auth.docker.io/token"),
                MockResponse(200, tags_payload, url="https://registry-1.docker.io/v2/owner/image/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://registry-1.docker.io/v2/owner/image/manifests/2.1.0",
                    headers={"Docker-Content-Digest": "sha256:dh-digest"},
                ),
            ]
        )
        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_dockerhub(info, config=DockwatchConfig(include_tags=[r"^1\."]))

        self.assertEqual(result.latest_tag, "2.1.0")
        self.assertTrue(result.is_outdated)
        self.assertIsNone(result.check_error)

    async def test_check_dockerhub_prefers_latest_semver(self) -> None:
        info = make_container(registry=RegistryType.DOCKERHUB, current_tag="1.0.0")
        token_payload = {"token": "dh-token"}
        tags_payload = {"tags": ["latest", "1.1.0", "1.2.3"]}

        mock_client = MockAsyncClient(
            [
                MockResponse(200, token_payload, url="https://auth.docker.io/token"),
                MockResponse(200, tags_payload, url="https://registry-1.docker.io/v2/owner/image/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://registry-1.docker.io/v2/owner/image/manifests/1.2.3",
                    headers={"Docker-Content-Digest": "sha256:dh-digest"},
                ),
            ]
        )
        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_dockerhub(info, config=DockwatchConfig(include_tags=[r"^1\."]))

        self.assertEqual(result.latest_tag, "1.2.3")
        self.assertTrue(result.is_outdated)
        self.assertIsNone(result.check_error)

    async def test_check_dockerhub_falls_back_to_most_recent_non_floating(self) -> None:
        info = make_container(registry=RegistryType.DOCKERHUB, current_tag="foo")
        token_payload = {"token": "dh-token"}
        tags_payload = {"tags": ["latest", "rolling"]}

        mock_client = MockAsyncClient(
            [
                MockResponse(200, token_payload, url="https://auth.docker.io/token"),
                MockResponse(200, tags_payload, url="https://registry-1.docker.io/v2/owner/image/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://registry-1.docker.io/v2/owner/image/manifests/rolling",
                    headers={"Docker-Content-Digest": "sha256:dh-digest"},
                ),
            ]
        )
        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_dockerhub(info, config=DockwatchConfig(exclude_tags=[r"^rolling$"]))

        self.assertIsNone(result.latest_tag)
        self.assertIn("matched configured tag filters", result.check_error or "")

    async def test_check_ghcr_uses_token_and_tags(self) -> None:
        info = make_container(registry=RegistryType.GHCR, current_tag="1.0.0")
        token_payload = {"token": "abc-token"}
        tags_payload = {"tags": ["latest", "1.3.0", "1.2.0"]}

        mock_client = MockAsyncClient(
            [
                MockResponse(200, token_payload, url="https://ghcr.io/token"),
                MockResponse(200, tags_payload, url="https://ghcr.io/v2/owner/image/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://ghcr.io/v2/owner/image/manifests/1.3.0",
                    headers={"Docker-Content-Digest": "sha256:ghcr-digest"},
                ),
            ]
        )
        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_ghcr(info)

        self.assertEqual(result.latest_tag, "1.3.0")
        self.assertTrue(result.is_outdated)
        self.assertIsNone(result.check_error)

        _, second_headers = mock_client.calls[1]
        self.assertEqual(second_headers, {"Authorization": "Bearer abc-token"})

    async def test_check_container_tracks_latest_tag(self) -> None:
        latest_info = ContainerInfo(
            name="bazarr",
            container_id="abc123",
            image_ref="lscr.io/linuxserver/bazarr:latest",
            registry=RegistryType.LSCR,
            namespace="linuxserver",
            image_name="bazarr",
            current_tag="latest",
            labels={"org.opencontainers.image.version": "v1.5.4-ls334"},
            compose_image_digest="sha256:local-digest",
        )
        payload = {
            "tags": [
                "latest",
                "v1.5.4-ls334",
                "v1.5.5-ls335",
            ]
        }

        mock_client = MockAsyncClient(
            [
                MockResponse(200, payload, url="https://lscr.io/v2/linuxserver/bazarr/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://lscr.io/v2/linuxserver/bazarr/manifests/v1.5.5-ls335",
                    headers={"Docker-Content-Digest": "sha256:remote-digest"},
                ),
            ]
        )
        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            latest_result = await check_container(latest_info)

        self.assertEqual(latest_result.latest_tag, "v1.5.5-ls335")
        self.assertTrue(latest_result.is_outdated)
        self.assertIsNone(latest_result.check_error)
        self.assertEqual(latest_result.comparison_basis, "digest")
        self.assertEqual(latest_result.remote_tag, "v1.5.5-ls335")
        self.assertEqual(latest_result.deployed_tag, "latest")
        self.assertEqual(latest_result.deployed_version, "v1.5.4-ls334")
        self.assertEqual(latest_result.latest_version, "v1.5.5-ls335")
        self.assertEqual(latest_result.version_status, "behind")
        self.assertIsNotNone(latest_result.version_diff)
        self.assertEqual(latest_result.version_diff.bump_type, "PATCH")

    async def test_check_container_skips_digest(self) -> None:
        digest_info = make_container(registry=RegistryType.DOCKERHUB, current_tag="DIGEST_PINNED")

        digest_result = await check_container(digest_info)

        self.assertIsNone(digest_result.is_outdated)
        self.assertIn("skipped", digest_result.check_error or "")

    async def test_check_container_skips_local_unknown_images(self) -> None:
        local_info = make_container(registry=RegistryType.UNKNOWN, current_tag="dev")

        result = await check_container(local_info)

        self.assertIsNone(result.is_outdated)
        self.assertEqual(result.check_error, "local-only or unsupported image reference")

    async def test_check_lscr_uses_digest_for_exact_match(self) -> None:
        info = ContainerInfo(
            name="bazarr",
            container_id="abc123",
            image_ref="lscr.io/linuxserver/bazarr:latest",
            registry=RegistryType.LSCR,
            namespace="linuxserver",
            image_name="bazarr",
            current_tag="latest",
            labels={"org.opencontainers.image.version": "v1.5.4-ls334"},
            compose_image_digest="sha256:exact-match",
        )
        payload = {
            "tags": [
                "latest",
                "v1.5.4-ls334",
            ]
        }

        mock_client = MockAsyncClient(
            [
                MockResponse(200, payload, url="https://lscr.io/v2/linuxserver/bazarr/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://lscr.io/v2/linuxserver/bazarr/manifests/v1.5.4-ls334",
                    headers={"Docker-Content-Digest": "sha256:exact-match"},
                ),
            ]
        )
        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_container(info)

        self.assertEqual(result.latest_tag, "v1.5.4-ls334")
        self.assertFalse(result.is_outdated)
        self.assertIsNone(result.check_error)
        self.assertEqual(result.comparison_basis, "digest")
        self.assertEqual(result.comparison_reason, "digest matches (v1.5.4-ls334)")
        self.assertEqual(result.latest_version, "v1.5.4-ls334")
        self.assertEqual(result.version_status, "equal")
        self.assertIsNotNone(result.version_diff)

    async def test_check_container_reports_same_tag_digest_drift(self) -> None:
        info = ContainerInfo(
            name="gluetun",
            container_id="abc123",
            image_ref="qmcgaw/gluetun:latest",
            registry=RegistryType.DOCKERHUB,
            namespace="qmcgaw",
            image_name="gluetun",
            current_tag="latest",
            labels={"org.opencontainers.image.version": "v3.39.0"},
            compose_image_digest="sha256:local-digest",
        )
        mock_client = MockAsyncClient(
            [
                MockResponse(200, {"token": "dh-token"}, url="https://auth.docker.io/token"),
                MockResponse(200, {"tags": ["latest"]}, url="https://registry-1.docker.io/v2/qmcgaw/gluetun/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://registry-1.docker.io/v2/qmcgaw/gluetun/manifests/latest",
                    headers={"Docker-Content-Digest": "sha256:remote-digest"},
                ),
            ]
        )

        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_container(info)

        self.assertEqual(result.remote_tag, "latest")
        self.assertTrue(result.is_outdated)
        self.assertEqual(result.comparison_basis, "digest")
        self.assertEqual(result.comparison_reason, "digest changed behind same tag")
        self.assertEqual(result.version_status, "equal")

    async def test_check_dockerhub_non_floating_tag_records_version_status(self) -> None:
        info = make_container(registry=RegistryType.DOCKERHUB, current_tag="1.0.0")
        token_payload = {"token": "dh-token"}
        tags_payload = {"tags": ["1.2.3"]}

        mock_client = MockAsyncClient(
            [
                MockResponse(200, token_payload, url="https://auth.docker.io/token"),
                MockResponse(200, tags_payload, url="https://registry-1.docker.io/v2/owner/image/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://registry-1.docker.io/v2/owner/image/manifests/1.2.3",
                    headers={"Docker-Content-Digest": "sha256:dh-digest"},
                ),
            ]
        )

        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_dockerhub(info)

        self.assertEqual(result.deployed_version, "1.0.0")
        self.assertEqual(result.latest_version, "1.2.3")
        self.assertEqual(result.version_status, "behind")
        self.assertIn("1.0.0 -> 1.2.3", result.comparison_reason or "")
        self.assertIsNotNone(result.version_diff)
        self.assertEqual(result.version_diff.bump_type, "MINOR")

    async def test_check_ghcr_floating_tag_prefers_same_tag_digest_for_non_semver_tags(self) -> None:
        info = ContainerInfo(
            name="byparr",
            container_id="abc123",
            image_ref="ghcr.io/thephaseless/byparr",
            registry=RegistryType.GHCR,
            namespace="thephaseless",
            image_name="byparr",
            current_tag="latest",
            labels={"org.opencontainers.image.version": "d4cf60e268281fae7db4556636bb55884d530960-amd64"},
            compose_image_digest="sha256:deployed-digest",
        )
        mock_client = MockAsyncClient(
            [
                MockResponse(200, {"token": "ghcr-token"}, url="https://ghcr.io/token"),
                MockResponse(
                    200,
                    {
                        "tags": [
                            "latest",
                            "d4cf60e268281fae7db4556636bb55884d530960-amd64",
                            "7a7f4fd59ff9652545404a4a9f65031f5ba7f4d3-amd64",
                        ]
                    },
                    url="https://ghcr.io/v2/thephaseless/byparr/tags/list",
                ),
                MockResponse(
                    200,
                    {},
                    url="https://ghcr.io/v2/thephaseless/byparr/manifests/latest",
                    headers={"Docker-Content-Digest": "sha256:deployed-digest"},
                ),
            ]
        )

        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            result = await check_ghcr(info)

        self.assertEqual(result.latest_tag, "d4cf60e268281fae7db4556636bb55884d530960-amd64")
        self.assertEqual(result.remote_tag, "latest")
        self.assertFalse(result.is_outdated)
        self.assertEqual(result.comparison_basis, "digest")
        self.assertEqual(result.comparison_reason, "digest matches")

    async def test_check_all_runs_concurrently(self) -> None:
        infos = [
            make_container(registry=RegistryType.UNKNOWN, current_tag="1.0.0"),
            make_container(registry=RegistryType.UNKNOWN, current_tag="latest"),
        ]

        results = await check_all(infos)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.check_error for result in results))

    async def test_check_all_isolates_container_exceptions(self) -> None:
        infos = [
            make_container(registry=RegistryType.UNKNOWN, current_tag="1.0.0"),
            make_container(registry=RegistryType.UNKNOWN, current_tag="latest"),
        ]

        async def boom(*args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("boom")

        with patch("dockwatch.registry.check_container", side_effect=boom):
            results = await check_all(infos)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.check_error and "container check failed" in result.check_error for result in results))

    async def test_check_all_reuses_one_http_client_for_entire_run(self) -> None:
        infos = [
            make_container(registry=RegistryType.DOCKERHUB, current_tag="1.0.0"),
            make_container(registry=RegistryType.DOCKERHUB, current_tag="2.0.0"),
        ]
        mock_client = MockAsyncClient(
            [
                MockResponse(200, {"token": "dh-token"}, url="https://auth.docker.io/token"),
                MockResponse(200, {"tags": ["1.2.0"]}, url="https://registry-1.docker.io/v2/owner/image/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://registry-1.docker.io/v2/owner/image/manifests/1.2.0",
                    headers={"Docker-Content-Digest": "sha256:dh-digest"},
                ),
                MockResponse(200, {"token": "dh-token"}, url="https://auth.docker.io/token"),
                MockResponse(200, {"tags": ["2.3.0"]}, url="https://registry-1.docker.io/v2/owner/image/tags/list"),
                MockResponse(
                    200,
                    {},
                    url="https://registry-1.docker.io/v2/owner/image/manifests/2.3.0",
                    headers={"Docker-Content-Digest": "sha256:dh-digest-2"},
                ),
            ]
        )

        with patch("dockwatch.registry.httpx.AsyncClient", return_value=mock_client):
            await check_all(infos)

        self.assertEqual(mock_client.enter_count, 1)


if __name__ == "__main__":
    unittest.main()
