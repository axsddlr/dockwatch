"""Trivy vulnerability scanner integration."""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass

from .config import TrivyConfig
from .models import TrivyFinding, TrivyScanResult


class TrivyNotFoundError(RuntimeError):
    """Trivy binary is not installed or not executable."""


class TrivyScanError(RuntimeError):
    """Trivy scan failed with an error."""


@dataclass(slots=True)
class _TrivyScanArgs:
    image_ref: str
    binary: str
    severity: list[str]
    scanners: list[str]
    timeout_seconds: int
    skip_db_update: bool


def check_trivy_available(custom_path: str = "trivy") -> bool:
    return shutil.which(custom_path) is not None


def _build_cmd(args: _TrivyScanArgs) -> list[str]:
    cmd = [
        args.binary,
        "image",
        "--format", "json",
        "--no-progress",
        "--scanners", ",".join(args.scanners),
        "--severity", ",".join(args.severity),
        args.image_ref,
    ]
    if args.skip_db_update:
        cmd.insert(1, "--skip-db-update")
    return cmd


def _parse_trivy_json(image_ref: str, raw_json: str) -> TrivyScanResult:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return TrivyScanResult(image_ref=image_ref, findings=[], error=f"invalid JSON: {exc}")

    findings: list[TrivyFinding] = []
    counts: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}

    results = data.get("Results", []) if isinstance(data, dict) else []
    for result in results:
        if not isinstance(result, dict):
            continue
        target = result.get("Target", "")
        class_type = result.get("Class", "")
        vulns = result.get("Vulnerabilities", [])
        if not isinstance(vulns, list):
            continue
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            severity = str(vuln.get("Severity", "UNKNOWN")).upper()
            finding = TrivyFinding(
                vulnerability_id=str(vuln.get("VulnerabilityID", "")),
                pkg_name=str(vuln.get("PkgName", "")),
                installed_version=str(vuln.get("InstalledVersion", "")),
                fixed_version=vuln.get("FixedVersion"),
                severity=severity,
                title=str(vuln.get("Title", "")),
                primary_url=str(vuln.get("PrimaryURL", "")),
                target=str(target),
                class_type=str(class_type),
            )
            findings.append(finding)
            key = severity if severity in counts else "LOW"
            counts[key] += 1

    return TrivyScanResult(
        image_ref=image_ref,
        findings=findings,
        critical_count=counts["CRITICAL"],
        high_count=counts["HIGH"],
        medium_count=counts["MEDIUM"],
        low_count=counts["LOW"],
    )


async def _scan_one(args: _TrivyScanArgs) -> TrivyScanResult:
    cmd = _build_cmd(args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=args.timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return TrivyScanResult(
            image_ref=args.image_ref,
            findings=[],
            error=f"scan timed out after {args.timeout_seconds}s",
        )
    except FileNotFoundError:
        raise TrivyNotFoundError(f"trivy binary not found at '{args.binary}'")

    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace") if stderr else ""
        return TrivyScanResult(
            image_ref=args.image_ref,
            findings=[],
            error=f"trivy exited with code {proc.returncode}: {err_text.strip()}" if err_text else f"trivy exited with code {proc.returncode}",
        )

    raw = stdout.decode("utf-8", errors="replace")
    return _parse_trivy_json(args.image_ref, raw)


async def scan_image(
    image_ref: str,
    trivy_config: TrivyConfig,
    *,
    timeout_override: int | None = None,
) -> TrivyScanResult:
    if not check_trivy_available(trivy_config.binary_path):
        raise TrivyNotFoundError(f"trivy binary not found at '{trivy_config.binary_path}'")

    args = _TrivyScanArgs(
        image_ref=image_ref,
        binary=trivy_config.binary_path,
        severity=list(trivy_config.severity) if trivy_config.severity else ["CRITICAL", "HIGH"],
        scanners=list(trivy_config.scanners) if trivy_config.scanners else ["vuln"],
        timeout_seconds=timeout_override or trivy_config.timeout_seconds,
        skip_db_update=trivy_config.skip_db_update,
    )
    return await _scan_one(args)
