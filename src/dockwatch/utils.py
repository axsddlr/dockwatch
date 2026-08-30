"""Small generic helpers shared across dockwatch modules.

Kept dependency-free (no imports from the rest of the package) so any module
can use these without pulling in domain code or risking circular imports.
"""

from __future__ import annotations

from typing import Any, overload


def unique_ordered(values: list[str]) -> list[str]:
    """Deduplicate a list of strings while preserving order, dropping empties."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def ensure_list(value: Any, fallback: list[Any]) -> list[Any]:
    """Coerce a list or comma-separated string into a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return list(fallback)


def parse_list(data: object) -> list[str]:
    """Coerce a TOML/JSON value into a deduplicated list of strings."""
    if not isinstance(data, list):
        return []
    return unique_ordered([str(item) for item in data])


@overload
def parse_bool(data: object, default: bool) -> bool: ...


@overload
def parse_bool(data: object, default: None = None) -> bool | None: ...


def parse_bool(data: object, default: bool | None = None) -> bool | None:
    """Parse a bool, or a truthy/falsy string, into a bool; else ``default``."""
    if isinstance(data, bool):
        return data
    if isinstance(data, str):
        normalized = data.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def parse_int(data: object, default: int, *, minimum: int) -> int:
    """Parse an integer, clamped to ``minimum``; else ``default``."""
    if not isinstance(data, (int, float, str)):
        return default
    try:
        value = int(data)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def parse_float(data: object, default: float, *, minimum: float) -> float:
    """Parse a float, clamped to ``minimum``; else ``default``."""
    if not isinstance(data, (int, float, str)):
        return default
    try:
        value = float(data)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def digest_of(ref: str | None) -> str | None:
    """Return the digest portion of an image ref like ``repo@sha256:...``."""
    if not ref:
        return None
    return ref.split("@", 1)[1] if "@" in ref else ref


def short_digest(digest: str | None) -> str | None:
    """Shorten a digest for display: ``sha256:abcd...`` -> 12 hex chars."""
    if not digest:
        return None
    normalized = digest_of(digest) or ""
    if normalized.startswith("sha256:"):
        return f"sha256:{normalized.removeprefix('sha256:')[:12]}"
    return normalized[:19]


def mask_secret(value: str) -> str:
    """Mask a secret for display, keeping the last four characters."""
    if not value:
        return ""
    return "****" + value[-4:] if len(value) > 4 else "****"


def is_masked(value: str) -> bool:
    """True if the value is already a masked secret (starts with '****')."""
    return bool(value) and value.startswith("****")
