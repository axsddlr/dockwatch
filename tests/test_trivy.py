"""Tests for Trivy integration module."""

from __future__ import annotations

import json
import unittest

from dockwatch.config import TrivyConfig
from dockwatch.models import TrivyFinding, TrivyScanResult
from dockwatch.trivy import _parse_trivy_json, _build_cmd, _TrivyScanArgs, check_trivy_available


SAMPLE_TRIVY_JSON = json.dumps({
    "Results": [
        {
            "Target": "alpine:latest (alpine 3.20.5)",
            "Class": "os-pkgs",
            "Type": "alpine",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2024-12797",
                    "PkgName": "libcrypto3",
                    "InstalledVersion": "3.3.2-r1",
                    "FixedVersion": "3.3.3-r0",
                    "Status": "fixed",
                    "Severity": "HIGH",
                    "Title": "openssl: RFC7250 handshakes issue",
                    "PrimaryURL": "https://avd.aquasec.com/nvd/cve-2024-12797",
                },
                {
                    "VulnerabilityID": "CVE-2024-13176",
                    "PkgName": "libssl3",
                    "InstalledVersion": "3.3.2-r1",
                    "FixedVersion": "3.3.2-r2",
                    "Status": "fixed",
                    "Severity": "MEDIUM",
                    "Title": "openssl: Timing side-channel in ECDSA",
                    "PrimaryURL": "https://avd.aquasec.com/nvd/cve-2024-13176",
                },
                {
                    "VulnerabilityID": "CVE-2025-001",
                    "PkgName": "musl",
                    "InstalledVersion": "1.2.5-r0",
                    "FixedVersion": "1.2.5-r1",
                    "Status": "fixed",
                    "Severity": "CRITICAL",
                    "Title": "musl: buffer overflow",
                    "PrimaryURL": "https://avd.aquasec.com/nvd/cve-2025-001",
                },
            ],
        },
        {
            "Target": "usr/local/bin/app",
            "Class": "lang-pkgs",
            "Type": "gobinary",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2025-22866",
                    "PkgName": "stdlib",
                    "InstalledVersion": "v1.22.11",
                    "FixedVersion": "1.22.12",
                    "Status": "fixed",
                    "Severity": "MEDIUM",
                    "Title": "golang: Timing sidechannel for P-256",
                    "PrimaryURL": "https://avd.aquasec.com/nvd/cve-2025-22866",
                },
            ],
        },
    ]
})

SAMPLE_CLEAN_JSON = json.dumps({
    "Results": [
        {
            "Target": "scratch:latest",
            "Class": "os-pkgs",
            "Type": "scratch",
            "Vulnerabilities": [],
        }
    ]
})

SAMPLE_ERROR_JSON = json.dumps({
    "Results": [
        {
            "Target": "bad:image",
            "Class": "os-pkgs",
            "Type": "alpine",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-2025-ABC",
                    "PkgName": "badlib",
                    "InstalledVersion": "1.0",
                    "Severity": "LOW",
                    "Title": "minor issue",
                    "PrimaryURL": "https://example.com",
                },
            ],
        }
    ]
})


class TrivyParseTests(unittest.TestCase):
    def test_parse_vulnerabilities_json(self) -> None:
        result = _parse_trivy_json("alpine:latest", SAMPLE_TRIVY_JSON)
        self.assertIsNone(result.error)
        self.assertEqual(result.image_ref, "alpine:latest")
        self.assertEqual(result.critical_count, 1)
        self.assertEqual(result.high_count, 1)
        self.assertEqual(result.medium_count, 2)
        self.assertEqual(result.low_count, 0)
        self.assertEqual(result.total_count, 4)
        self.assertEqual(len(result.findings), 4)

    def test_findings_have_expected_fields(self) -> None:
        result = _parse_trivy_json("alpine:latest", SAMPLE_TRIVY_JSON)
        first = result.findings[0]
        self.assertEqual(first.vulnerability_id, "CVE-2024-12797")
        self.assertEqual(first.pkg_name, "libcrypto3")
        self.assertEqual(first.installed_version, "3.3.2-r1")
        self.assertEqual(first.fixed_version, "3.3.3-r0")
        self.assertEqual(first.severity, "HIGH")
        self.assertEqual(first.target, "alpine:latest (alpine 3.20.5)")
        self.assertEqual(first.class_type, "os-pkgs")
        self.assertTrue(first.primary_url.startswith("https://"))

    def test_critical_finding_is_first(self) -> None:
        result = _parse_trivy_json("alpine:latest", SAMPLE_TRIVY_JSON)
        self.assertEqual(result.critical_count, 1)
        critical = [f for f in result.findings if f.severity == "CRITICAL"]
        self.assertEqual(len(critical), 1)
        self.assertEqual(critical[0].vulnerability_id, "CVE-2025-001")

    def test_clean_image_no_vulnerabilities(self) -> None:
        result = _parse_trivy_json("scratch:latest", SAMPLE_CLEAN_JSON)
        self.assertIsNone(result.error)
        self.assertEqual(result.total_count, 0)
        self.assertEqual(len(result.findings), 0)

    def test_vulnerabilities_without_fixed_version(self) -> None:
        result = _parse_trivy_json("bad:image", SAMPLE_ERROR_JSON)
        finding = result.findings[0]
        self.assertIsNone(finding.fixed_version)
        self.assertEqual(finding.severity, "LOW")
        self.assertEqual(result.low_count, 1)

    def test_invalid_json_returns_error(self) -> None:
        result = _parse_trivy_json("broken:image", "not valid json")
        self.assertIsNotNone(result.error)
        self.assertIn("invalid JSON", result.error)
        self.assertEqual(len(result.findings), 0)
        self.assertEqual(result.total_count, 0)

    def test_empty_results_list(self) -> None:
        result = _parse_trivy_json("empty:image", json.dumps({"Results": []}))
        self.assertIsNone(result.error)
        self.assertEqual(len(result.findings), 0)

    def test_severity_order_property(self) -> None:
        self.assertEqual(TrivyFinding("", "", "", None, "CRITICAL", "", "", "", "").severity_order, 4)
        self.assertEqual(TrivyFinding("", "", "", None, "HIGH", "", "", "", "").severity_order, 3)
        self.assertEqual(TrivyFinding("", "", "", None, "MEDIUM", "", "", "", "").severity_order, 2)
        self.assertEqual(TrivyFinding("", "", "", None, "LOW", "", "", "", "").severity_order, 1)
        self.assertEqual(TrivyFinding("", "", "", None, "UNKNOWN", "", "", "", "").severity_order, 0)


class TrivyConfigTests(unittest.TestCase):
    def test_default_config(self) -> None:
        cfg = TrivyConfig()
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.binary_path, "trivy")
        self.assertEqual(cfg.severity, ["CRITICAL", "HIGH"])
        self.assertEqual(cfg.scanners, ["vuln"])
        self.assertEqual(cfg.timeout_seconds, 300)
        self.assertFalse(cfg.skip_db_update)
        self.assertEqual(cfg.cache_ttl_minutes, 60)

    def test_config_fields_are_independent(self) -> None:
        cfg = TrivyConfig(enabled=True, timeout_seconds=600)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.timeout_seconds, 600)
        self.assertEqual(cfg.severity, ["CRITICAL", "HIGH"])


class TrivyCmdBuilderTests(unittest.TestCase):
    def test_build_cmd_basic(self) -> None:
        args = _TrivyScanArgs(
            image_ref="alpine:latest",
            binary="trivy",
            severity=["CRITICAL", "HIGH"],
            scanners=["vuln"],
            timeout_seconds=300,
            skip_db_update=False,
        )
        cmd = _build_cmd(args)
        self.assertEqual(cmd[0], "trivy")
        self.assertEqual(cmd[1], "image")
        self.assertIn("--format", cmd)
        self.assertIn("json", cmd)
        self.assertIn("--severity", cmd)
        self.assertIn("CRITICAL,HIGH", cmd)
        self.assertIn("--scanners", cmd)
        self.assertIn("vuln", cmd)
        self.assertIn("alpine:latest", cmd)

    def test_build_cmd_skip_db_update(self) -> None:
        args = _TrivyScanArgs(
            image_ref="nginx:latest",
            binary="/usr/local/bin/trivy",
            severity=["HIGH"],
            scanners=["vuln", "secret"],
            timeout_seconds=120,
            skip_db_update=True,
        )
        cmd = _build_cmd(args)
        self.assertIn("--skip-db-update", cmd)
        self.assertIn("/usr/local/bin/trivy", cmd)
        self.assertEqual(cmd[1], "--skip-db-update")


class TrivyAvailableTests(unittest.TestCase):
    def test_check_trivy_not_found_for_fake_path(self) -> None:
        self.assertFalse(check_trivy_available("__nonexistent_trivy_binary__"))

    def test_check_trivy_available_default(self) -> None:
        result = check_trivy_available()
        self.assertIsInstance(result, bool)


class TrivyScanResultTests(unittest.TestCase):
    def test_scan_result_total(self) -> None:
        sr = TrivyScanResult(
            image_ref="test:1.0",
            findings=[],
            critical_count=2,
            high_count=1,
            medium_count=3,
            low_count=0,
        )
        self.assertEqual(sr.total_count, 6)

    def test_scan_result_with_error(self) -> None:
        sr = TrivyScanResult(
            image_ref="bad:image",
            findings=[],
            error="something went wrong",
        )
        self.assertEqual(sr.total_count, 0)
        self.assertEqual(sr.error, "something went wrong")

    def test_scan_result_image_id_stored(self) -> None:
        sr = TrivyScanResult(
            image_ref="test:1.0",
            findings=[],
            image_id="abc123",
        )
        self.assertEqual(sr.image_id, "abc123")


if __name__ == "__main__":
    unittest.main()
