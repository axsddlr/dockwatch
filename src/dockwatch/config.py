"""Configuration management for dockwatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib

CONFIG_PATH = Path.home() / ".config" / "dockwatch" / "config.toml"


@dataclass(slots=True)
class DockwatchConfig:
    pinned: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    notify_only: list[str] = field(default_factory=list)


def _unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _parse_list(data: object) -> list[str]:
    if not isinstance(data, list):
        return []
    return _unique_ordered([str(item) for item in data])


def _to_toml(config: DockwatchConfig) -> str:
    pinned = ", ".join(f'"{item}"' for item in config.pinned)
    ignored = ", ".join(f'"{item}"' for item in config.ignored)
    notify_only = ", ".join(f'"{item}"' for item in config.notify_only)
    return (
        "pinned = [" + pinned + "]\n"
        "ignored = [" + ignored + "]\n"
        "notify_only = [" + notify_only + "]\n"
    )


def save_config(config: DockwatchConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = DockwatchConfig(
        pinned=_unique_ordered(config.pinned),
        ignored=_unique_ordered(config.ignored),
        notify_only=_unique_ordered(config.notify_only),
    )
    path.write_text(_to_toml(normalized), encoding="utf-8")


def load_config(path: Path = CONFIG_PATH) -> DockwatchConfig:
    if not path.exists():
        default_config = DockwatchConfig()
        save_config(default_config, path)
        return default_config

    content = path.read_text(encoding="utf-8")
    data = tomllib.loads(content) if content.strip() else {}
    config = DockwatchConfig(
        pinned=_parse_list(data.get("pinned")),
        ignored=_parse_list(data.get("ignored")),
        notify_only=_parse_list(data.get("notify_only")),
    )
    save_config(config, path)
    return config