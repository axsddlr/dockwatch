"""Regression test for the check-results cache merge: a plain local check
must not erase or downgrade a container's Portainer identity, even when
the same container is also visible via the local Docker socket."""

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

    def test_all_source_replaces_cache_wholesale(self) -> None:
        cache = [_result("stale", source="local")]
        fresh_all = [_result("web", source="portainer", environment_id="1")]

        merged = _merge_check_results(cache, fresh_all, source="all")

        self.assertEqual(merged, fresh_all)


if __name__ == "__main__":
    unittest.main()
