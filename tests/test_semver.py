from __future__ import annotations

import unittest

from dockwatch.semver import compare_versions, parse_version


class SemverTests(unittest.TestCase):
    def test_major_bump(self) -> None:
        diff = compare_versions("1.0.0", "2.0.0")
        self.assertEqual(diff.bump_type, "MAJOR")

    def test_minor_bump(self) -> None:
        diff = compare_versions("1.2.3", "1.3.0")
        self.assertEqual(diff.bump_type, "MINOR")

    def test_patch_bump(self) -> None:
        diff = compare_versions("1.2.3", "1.2.4")
        self.assertEqual(diff.bump_type, "PATCH")

    def test_v_prefixed_tags(self) -> None:
        diff = compare_versions("v1.2.3", "v1.3.0")
        self.assertEqual(diff.bump_type, "MINOR")

    def test_suffixed_tags(self) -> None:
        diff = compare_versions("1.2.3-alpine", "1.2.4-alpine")
        self.assertEqual(diff.bump_type, "PATCH")

    def test_prerelease_suffix_change(self) -> None:
        diff = compare_versions("1.2.3-beta", "1.2.3")
        self.assertEqual(diff.bump_type, "PRE-RELEASE")

    def test_non_semver_is_unknown(self) -> None:
        diff = compare_versions("latest", "latest")
        self.assertEqual(diff.bump_type, "UNKNOWN")

    def test_mixed_non_semver_is_unknown(self) -> None:
        diff = compare_versions("1.2.3", "latest")
        self.assertEqual(diff.bump_type, "UNKNOWN")

    def test_parse_version_returns_none_for_empty(self) -> None:
        self.assertIsNone(parse_version(""))


if __name__ == "__main__":
    unittest.main()
