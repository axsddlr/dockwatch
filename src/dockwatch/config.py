"""Configuration management for dockwatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib

CONFIG_PATH = Path.home() / ".config" / "dockwatch" / "config.toml"
DEFAULT_NOTIFY_ON = ["update"]
VALID_NOTIFY_EVENTS = {"new", "update"}


@dataclass(slots=True)
class DockwatchConfig:
    pinned: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    notify_only: list[str] = field(default_factory=list)
    include_tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)
    notify_on: list[str] = field(default_factory=lambda: DEFAULT_NOTIFY_ON.copy())
    first_check_notify: bool = False
    webhook_url: str = ""
    discord_webhook: str = ""
    ntfy_url: str = ""
    schedule_interval_seconds: int = 300
    schedule_jitter_seconds: int = 30
    run_on_startup: bool = True
    max_concurrent_checks: int = 5


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


def _parse_notify_events(data: object) -> list[str]:
    values = [item.lower() for item in _parse_list(data)]
    filtered = [item for item in values if item in VALID_NOTIFY_EVENTS]
    return filtered or DEFAULT_NOTIFY_ON.copy()


def _parse_bool(data: object, default: bool) -> bool:
    if isinstance(data, bool):
        return data
    if isinstance(data, str):
        normalized = data.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _parse_int(data: object, default: int, *, minimum: int) -> int:
    try:
        value = int(data)
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _bool_toml(value: bool) -> str:
    return "true" if value else "false"


def _toml_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\b", "\\b")
        .replace("\f", "\\f")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(item) for item in values) + "]"


def _to_toml(config: DockwatchConfig) -> str:
    base = (
        f"pinned = {_toml_array(config.pinned)}\n"
        f"ignored = {_toml_array(config.ignored)}\n"
        f"notify_only = {_toml_array(config.notify_only)}\n"
        f"include_tags = {_toml_array(config.include_tags)}\n"
        f"exclude_tags = {_toml_array(config.exclude_tags)}\n"
        f"notify_on = {_toml_array(config.notify_on)}\n"
        f"first_check_notify = {_bool_toml(config.first_check_notify)}\n"
        f"schedule_interval_seconds = {config.schedule_interval_seconds}\n"
        f"schedule_jitter_seconds = {config.schedule_jitter_seconds}\n"
        f"run_on_startup = {_bool_toml(config.run_on_startup)}\n"
        f"max_concurrent_checks = {config.max_concurrent_checks}\n"
    )
    notifications = (
        "\n[notifications]\n"
        f"webhook_url = {_toml_string(config.webhook_url)}\n"
        f"discord_webhook = {_toml_string(config.discord_webhook)}\n"
        f"ntfy_url = {_toml_string(config.ntfy_url)}\n"
    )
    return base + notifications


def save_config(config: DockwatchConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = DockwatchConfig(
        pinned=_unique_ordered(config.pinned),
        ignored=_unique_ordered(config.ignored),
        notify_only=_unique_ordered(config.notify_only),
        include_tags=_unique_ordered(config.include_tags),
        exclude_tags=_unique_ordered(config.exclude_tags),
        notify_on=_parse_notify_events(config.notify_on),
        first_check_notify=bool(config.first_check_notify),
        webhook_url=config.webhook_url.strip(),
        discord_webhook=config.discord_webhook.strip(),
        ntfy_url=config.ntfy_url.strip(),
        schedule_interval_seconds=max(10, int(config.schedule_interval_seconds)),
        schedule_jitter_seconds=max(0, int(config.schedule_jitter_seconds)),
        run_on_startup=bool(config.run_on_startup),
        max_concurrent_checks=max(1, int(config.max_concurrent_checks)),
    )
    path.write_text(_to_toml(normalized), encoding="utf-8")


def load_config(path: Path = CONFIG_PATH) -> DockwatchConfig:
    if not path.exists():
        default_config = DockwatchConfig()
        save_config(default_config, path)
        return default_config

    content = path.read_text(encoding="utf-8")
    data = tomllib.loads(content) if content.strip() else {}
    notifications = data.get("notifications", {}) if isinstance(data, dict) else {}
    config = DockwatchConfig(
        pinned=_parse_list(data.get("pinned")),
        ignored=_parse_list(data.get("ignored")),
        notify_only=_parse_list(data.get("notify_only")),
        include_tags=_parse_list(data.get("include_tags")),
        exclude_tags=_parse_list(data.get("exclude_tags")),
        notify_on=_parse_notify_events(data.get("notify_on")),
        first_check_notify=_parse_bool(data.get("first_check_notify"), False),
        webhook_url=str(notifications.get("webhook_url", "")) if isinstance(notifications, dict) else "",
        discord_webhook=str(notifications.get("discord_webhook", "")) if isinstance(notifications, dict) else "",
        ntfy_url=str(notifications.get("ntfy_url", "")) if isinstance(notifications, dict) else "",
        schedule_interval_seconds=_parse_int(data.get("schedule_interval_seconds"), 300, minimum=10),
        schedule_jitter_seconds=_parse_int(data.get("schedule_jitter_seconds"), 30, minimum=0),
        run_on_startup=_parse_bool(data.get("run_on_startup"), True),
        max_concurrent_checks=_parse_int(data.get("max_concurrent_checks"), 5, minimum=1),
    )
    return config
