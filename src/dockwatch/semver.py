"""Best-effort semantic version helpers for dockwatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from packaging.version import InvalidVersion, Version

VersionBump = Literal["MAJOR", "MINOR", "PATCH", "PRE-RELEASE", "UNKNOWN"]


@dataclass(slots=True)
class VersionDiff:
    bump_type: VersionBump
    current_parsed: Version | None
    latest_parsed: Version | None
    current_raw: str
    latest_raw: str


def _normalize_tag(tag: str) -> str:
    normalized = tag.strip()
    if not normalized:
        return normalized
    if normalized.startswith("v") and len(normalized) > 1 and normalized[1].isdigit():
        normalized = normalized[1:]
    if "+" in normalized:
        idx = normalized.rfind("+")
        prefix = normalized[:idx]
        if prefix and any(c in prefix for c in (".", "-", "_")):
            normalized = prefix
        return normalized

    base, sep, suffix = normalized.partition("-")
    if not sep:
        return normalized
    if any(char.isdigit() for char in suffix):
        # packaging can parse rc/beta/dev style prereleases directly
        try:
            Version(normalized)
            return normalized
        except InvalidVersion:
            return f"{base}+{suffix.replace('-', '.')}"
    if suffix.lower().startswith(("a", "alpha", "b", "beta", "rc", "pre", "preview", "dev", "post")):
        return normalized
    return f"{base}+{suffix.replace('-', '.')}"


def parse_version(tag: str) -> Version | None:
    normalized = _normalize_tag(tag)
    if not normalized:
        return None
    try:
        return Version(normalized)
    except InvalidVersion:
        return None


def _strip_build_metadata(tag: str) -> str:
    idx = tag.rfind("+")
    if idx < 0:
        return tag
    prefix = tag[:idx]
    if not prefix:
        return tag
    if prefix.rfind(".") >= 0 or prefix.rfind("-") >= 0 or prefix.rfind("_") >= 0:
        return prefix
    return tag


def _normalize_formatting(tag: str) -> str:
    normalized = _strip_build_metadata(tag)
    if normalized.lower().startswith("v") and len(normalized) > 1 and normalized[1].isdigit():
        normalized = normalized[1:]
    return normalized


def compare_versions(current: str, latest: str) -> VersionDiff:
    current_parsed = parse_version(current)
    latest_parsed = parse_version(latest)
    if current_parsed is None or latest_parsed is None:
        return VersionDiff("UNKNOWN", current_parsed, latest_parsed, current, latest)

    if current_parsed == latest_parsed:
        if _normalize_formatting(current) == _normalize_formatting(latest):
            return VersionDiff("UNKNOWN", current_parsed, latest_parsed, current, latest)
        return VersionDiff("PRE-RELEASE", current_parsed, latest_parsed, current, latest)

    if current_parsed.major != latest_parsed.major:
        bump_type: VersionBump = "MAJOR"
    elif current_parsed.minor != latest_parsed.minor:
        bump_type = "MINOR"
    elif current_parsed.micro != latest_parsed.micro:
        bump_type = "PATCH"
    else:
        bump_type = "PRE-RELEASE"

    return VersionDiff(bump_type, current_parsed, latest_parsed, current, latest)


def format_diff(diff: VersionDiff) -> str:
    return f"{diff.current_raw} -> {diff.latest_raw} ({diff.bump_type})"
