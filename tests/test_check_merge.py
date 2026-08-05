"""Tests for the check-results cache merge: a plain local check must not
erase or downgrade a container's Portainer identity, even when the same
container is also visible via the local Docker socket. An "all" source
check must deduplicate same-name containers across sources (Portainer
wins) and preserve stale cache entries rather than replacing wholesale."""

from __future__ import annotations

import unittest

from dockwatch.api.routes.containers import _merge_check_results
from dockwatch.models import ContainerInfo, RegistryType, UpdateResult


def _result(name: str, *, source: str, environment_id: str | None = None) -> UpdateResult:
    info = ContainerInfo(
        name=name,
        container_id="abc123",
        image_ref=f"{name}:latest",
        registry=RegistryType.DOCKERHUB,
        namespace="library",
        image_name=name,
        current_tag="latest",
        source=source,
        environment_id=environment_id,
        environment_name="local" if environment_id else None,
    )
    return UpdateResult(container_info=info)


class MergeCheckResultsTests(unittest.TestCase):
    def test_local_check_does_not_downgrade_existing_portainer_entry(self) -> None:
        cache = [_result("web", source="portainer", environment_id="1")]
        fresh_local = [_result("web", source="local")]

        merged = _merge_check_results(cache, fresh_local, source="local")

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].container_info.source, "portainer")
        self.assertEqual(merged[0].container_info.environment_id, "1")

    def test_local_check_preserves_portainer_only_containers(self) -> None:
        cache = [_result("stack-only", source="portainer", environment_id="1")]
        fresh_local = [_result("other", source="local")]

        merged = _merge_check_results(cache, fresh_local, source="local")

        names = {r.container_info.name for r in merged}
        self.assertEqual(names, {"stack-only", "other"})
        stack_only = next(r for r in merged if r.container_info.name == "stack-only")
        self.assertEqual(stack_only.container_info.source, "portainer")

    def test_portainer_check_replaces_local_entry_for_same_name(self) -> None:
        cache = [_result("web", source="local")]
        fresh_portainer = [_result("web", source="portainer", environment_id="1")]

        merged = _merge_check_results(cache, fresh_portainer, source="portainer")

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].container_info.source, "portainer")

    def test_all_source_merge_keeps_stale_cache_entries(self) -> None:
        cache = [
            _result("stale-local", source="local"),
            _result("stale-portainer", source="portainer", environment_id="1"),
        ]
        fresh_all = [_result("web", source="portainer", environment_id="1")]

        merged = _merge_check_results(cache, fresh_all, source="all")

        names = {r.container_info.name for r in merged}
        self.assertEqual(names, {"stale-local", "stale-portainer", "web"})

    def test_all_source_dedupes_by_name_preferring_portainer(self) -> None:
        cache: list[UpdateResult] = []
        fresh_all = [
            _result("web", source="local"),
            _result("web", source="portainer", environment_id="1"),
        ]

        merged = _merge_check_results(cache, fresh_all, source="all")

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].container_info.source, "portainer")
        self.assertEqual(merged[0].container_info.environment_id, "1")

    def test_all_source_dedupes_keeps_local_only_when_no_portainer_match(self) -> None:
        cache: list[UpdateResult] = []
        fresh_all = [
            _result("local-only", source="local"),
            _result("portainer-only", source="portainer", environment_id="1"),
        ]

        merged = _merge_check_results(cache, fresh_all, source="all")
        merged.sort(key=lambda r: r.container_info.source)

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].container_info.source, "local")
        self.assertEqual(merged[0].container_info.name, "local-only")
        self.assertEqual(merged[1].container_info.source, "portainer")
        self.assertEqual(merged[1].container_info.name, "portainer-only")

    def test_portainer_check_preserves_stale_local_entries(self) -> None:
        cache = [_result("local-only", source="local")]
        fresh_portainer = [_result("web", source="portainer", environment_id="1")]

        merged = _merge_check_results(cache, fresh_portainer, source="portainer")

        names = {r.container_info.name for r in merged}
        self.assertEqual(names, {"local-only", "web"})

    def test_local_check_preserves_portainer_identity_across_cycles(self) -> None:
        cache = [_result("web", source="portainer", environment_id="1")]
        first_local = [_result("web", source="local")]
        merged1 = _merge_check_results(cache, first_local, source="local")
        self.assertEqual(merged1[0].container_info.source, "portainer")

        second_local = [_result("web", source="local")]
        merged2 = _merge_check_results(merged1, second_local, source="local")
        self.assertEqual(merged2[0].container_info.source, "portainer")


if __name__ == "__main__":
    unittest.main()
