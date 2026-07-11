"""Configuration management for dockwatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import tempfile
import tomllib

CONFIG_PATH = Path.home() / ".config" / "dockwatch" / "config.toml"
DEFAULT_NOTIFY_ON = ["update"]
VALID_NOTIFY_EVENTS = {"new", "update"}


@dataclass(slots=True)
class PortainerConfig:
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    environments: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ComposeProjectConfig:
    workdir: str = ""
    files: list[str] = field(default_factory=list)
    project_name: str = ""


@dataclass(slots=True)
class TrivyConfig:
    enabled: bool = False
    binary_path: str = "trivy"
    severity: list[str] = field(default_factory=lambda: ["CRITICAL", "HIGH"])
    scanners: list[str] = field(default_factory=lambda: ["vuln"])
    timeout_seconds: int = 300
    skip_db_update: bool = False
    cache_ttl_minutes: int = 60


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
    portainer: PortainerConfig = field(default_factory=PortainerConfig)
    compose_projects: dict[str, ComposeProjectConfig] = field(default_factory=dict)
    trivy: TrivyConfig = field(default_factory=TrivyConfig)


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
    portainer = (
        "\n[portainer]\n"
        f"enabled = {_bool_toml(config.portainer.enabled)}\n"
        f"url = {_toml_string(config.portainer.url)}\n"
        f"api_key = {_toml_string(config.portainer.api_key)}\n"
        f"environments = {_toml_array(config.portainer.environments)}\n"
    )
    trivy_section = (
        "\n[trivy]\n"
        f"enabled = {_bool_toml(config.trivy.enabled)}\n"
        f"binary_path = {_toml_string(config.trivy.binary_path)}\n"
        f"severity = {_toml_array(config.trivy.severity)}\n"
        f"scanners = {_toml_array(config.trivy.scanners)}\n"
        f"timeout_seconds = {config.trivy.timeout_seconds}\n"
        f"skip_db_update = {_bool_toml(config.trivy.skip_db_update)}\n"
        f"cache_ttl_minutes = {config.trivy.cache_ttl_minutes}\n"
    )
    compose_projects = ""
    if config.compose_projects:
        compose_projects = "\n[compose_projects]\n"
        for project, project_cfg in config.compose_projects.items():
            compose_projects += (
                f"\n[compose_projects.{_toml_string(project)}]\n"
                f"workdir = {_toml_string(project_cfg.workdir)}\n"
                f"files = {_toml_array(project_cfg.files)}\n"
                f"project_name = {_toml_string(project_cfg.project_name)}\n"
            )
    return base + notifications + portainer + trivy_section + compose_projects


def _parse_compose_projects(data: object) -> dict[str, ComposeProjectConfig]:
    if not isinstance(data, dict):
        return {}
    projects: dict[str, ComposeProjectConfig] = {}
    for name, raw_cfg in data.items():
        if not isinstance(raw_cfg, dict):
            continue
        key = str(name).strip()
        if not key:
            continue
        projects[key] = ComposeProjectConfig(
            workdir=str(raw_cfg.get("workdir", "")).strip(),
            files=_parse_list(raw_cfg.get("files")),
            project_name=str(raw_cfg.get("project_name", "")).strip(),
        )
    return projects


def host_mount_prefix() -> str:
    """Prefix under which the host's / is bind-mounted into dockwatch's own
    container (e.g. "/hostroot" if docker-compose.yml mounts "/:/hostroot").
    Empty string means dockwatch runs with the host's real paths directly
    (native install, or no host-root mount configured).
    """
    return os.environ.get("HOST_MOUNT_PREFIX", "").rstrip("/")


def resolve_host_path(path: str) -> Path:
    """Translate a host-real path (as recorded in Docker compose labels)
    into the path dockwatch's own process should use to reach it, applying
    HOST_MOUNT_PREFIX if configured.
    """
    prefix = host_mount_prefix()
    if not prefix or not path:
        return Path(path)
    return Path(prefix + path) if path.startswith("/") else Path(prefix) / path


def resolve_compose_file(file: str, workdir: str) -> Path:
    """Translate a compose file entry (host-real, absolute or workdir-relative)
    into the path dockwatch's own process should use, applying
    HOST_MOUNT_PREFIX if configured.
    """
    # startswith("/") not Path.is_absolute(): compose label paths are always
    # POSIX, and this must behave identically when tests run on Windows.
    if file.startswith("/"):
        return resolve_host_path(file)
    return resolve_host_path(workdir) / file


def validate_compose_project_config(cfg: ComposeProjectConfig) -> list[str]:
    """Best-effort sanity checks against dockwatch's own filesystem view.

    Does not raise. A container's compose labels record paths as seen by
    whatever ran `docker compose up` (host shell, Dockge, Dockhand, etc) —
    those paths may not exist inside dockwatch's own container/mount
    namespace even when they are perfectly correct from Compose's
    perspective. Callers decide whether to block or just warn.
    """
    warnings: list[str] = []
    workdir = cfg.workdir.strip()
    if not workdir:
        warnings.append("workdir is empty.")
    else:
        resolved_workdir = resolve_host_path(workdir)
        if not resolved_workdir.is_dir():
            warnings.append(
                f"workdir '{workdir}' is not a directory dockwatch can see "
                f"(looked at '{resolved_workdir}'). dockwatch needs a bind "
                "mount to this path to run compose commands."
            )
        else:
            for file in cfg.files:
                candidate = resolve_compose_file(file, workdir)
                if not candidate.is_file():
                    warnings.append(f"compose file '{file}' was not found at '{candidate}'.")
    if not cfg.project_name.strip():
        warnings.append("project_name is empty; compose commands will omit the -p flag.")
    return warnings


def _parse_trivy_config(data: object) -> TrivyConfig:
    if not isinstance(data, dict):
        return TrivyConfig()
    severity = _parse_list(data.get("severity"))
    return TrivyConfig(
        enabled=_parse_bool(data.get("enabled"), False),
        binary_path=str(data.get("binary_path", "trivy")).strip() or "trivy",
        severity=_unique_ordered(severity) if severity else ["CRITICAL", "HIGH"],
        scanners=_parse_list(data.get("scanners")) or ["vuln"],
        timeout_seconds=_parse_int(data.get("timeout_seconds"), 300, minimum=10),
        skip_db_update=_parse_bool(data.get("skip_db_update"), False),
        cache_ttl_minutes=_parse_int(data.get("cache_ttl_minutes"), 60, minimum=1),
    )


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
        portainer=PortainerConfig(
            enabled=bool(config.portainer.enabled),
            url=config.portainer.url.strip(),
            api_key=config.portainer.api_key.strip(),
            environments=_unique_ordered(config.portainer.environments),
        ),
        compose_projects={
            key: ComposeProjectConfig(
                workdir=value.workdir.strip(),
                files=_unique_ordered(value.files),
                project_name=value.project_name.strip(),
            )
            for key, value in config.compose_projects.items()
            if key.strip()
        },
        trivy=TrivyConfig(
            enabled=bool(config.trivy.enabled),
            binary_path=config.trivy.binary_path.strip() or "trivy",
            severity=_unique_ordered(config.trivy.severity) or ["CRITICAL", "HIGH"],
            scanners=_unique_ordered(config.trivy.scanners) or ["vuln"],
            timeout_seconds=max(10, int(config.trivy.timeout_seconds)),
            skip_db_update=bool(config.trivy.skip_db_update),
            cache_ttl_minutes=max(1, int(config.trivy.cache_ttl_minutes)),
        ),
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_to_toml(normalized), encoding="utf-8")
    tmp.replace(path)


def _fallback_config(path: Path) -> DockwatchConfig:
    default = DockwatchConfig()
    try:
        save_config(default, path)
    except OSError:
        pass
    return default


def load_config(path: Path = CONFIG_PATH) -> DockwatchConfig:
    if not path.exists():
        default_config = DockwatchConfig()
        save_config(default_config, path)
        return default_config

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _fallback_config(path)

    if not content.strip():
        return _fallback_config(path)

    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return _fallback_config(path)

    if not isinstance(data, dict):
        return _fallback_config(path)

    notifications = data.get("notifications", {}) if isinstance(data, dict) else {}
    portainer = data.get("portainer", {}) if isinstance(data, dict) else {}
    compose_projects = data.get("compose_projects", {}) if isinstance(data, dict) else {}
    trivy_raw = data.get("trivy", {}) if isinstance(data, dict) else {}
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
        portainer=PortainerConfig(
            enabled=_parse_bool(portainer.get("enabled"), False) if isinstance(portainer, dict) else False,
            url=str(portainer.get("url", "")) if isinstance(portainer, dict) else "",
            api_key=str(portainer.get("api_key", "")) if isinstance(portainer, dict) else "",
            environments=_parse_list(portainer.get("environments")) if isinstance(portainer, dict) else [],
        ),
        compose_projects=_parse_compose_projects(compose_projects),
        trivy=_parse_trivy_config(trivy_raw),
    )
    return config
