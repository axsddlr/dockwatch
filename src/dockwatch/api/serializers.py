"""JSON serializers for dockwatch data models."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from packaging.version import Version

from ..config import DockwatchConfig, PortainerConfig, TrivyConfig, ComposeProjectConfig
from ..db import ManifestStore
from ..models import (
    ContainerInfo,
    RegistryType,
    UpdateResult,
    VersionDiff,
    deployed_display_result,
    remote_display,
)


def _serialize_enum(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Version):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value, dict_factory=_custom_dict)
    return value


def _custom_dict(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key.startswith("_"):
            continue
        result[key] = _serialize_enum(value)
    return result


def serialize_container_info(info: ContainerInfo) -> dict[str, Any]:
    return _custom_dict([
        (f.name, getattr(info, f.name))
        for f in info.__dataclass_fields__.values()  # noqa: SLF001
    ])


def serialize_version_diff(diff: VersionDiff) -> dict[str, Any] | None:
    if diff is None:
        return None
    return {
        "bump_type": diff.bump_type,
        "current_parsed": str(diff.current_parsed) if diff.current_parsed else None,
        "latest_parsed": str(diff.latest_parsed) if diff.latest_parsed else None,
        "current_raw": diff.current_raw,
        "latest_raw": diff.latest_raw,
    }


def serialize_update_result(result: UpdateResult) -> dict[str, Any]:
    data: dict[str, Any] = {}
    data["container_info"] = serialize_container_info(result.container_info)
    data["latest_tag"] = result.latest_tag
    data["latest_version"] = result.latest_version
    data["is_outdated"] = result.is_outdated
    data["check_error"] = result.check_error
    data["status"] = result.status
    data["event"] = result.event
    data["deployed_tag"] = result.deployed_tag
    data["deployed_version"] = result.deployed_version
    data["deployed_display"] = deployed_display_result(result)
    data["remote_display"] = remote_display(result)
    data["deployed_digest"] = result.deployed_digest
    data["remote_tag"] = result.remote_tag
    data["remote_digest"] = result.remote_digest
    data["comparison_basis"] = result.comparison_basis
    data["comparison_reason"] = result.comparison_reason
    data["version_status"] = result.version_status
    data["version_diff"] = serialize_version_diff(result.version_diff)
    return data


def serialize_update_results(results: list[UpdateResult]) -> list[dict[str, Any]]:
    return [serialize_update_result(r) for r in results]


def _mask_api_key(key: str) -> str:
    if not key:
        return ""
    return "****" + key[-4:] if len(key) > 4 else "****"


def _ensure_list(value: Any, fallback: list[Any]) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return list(fallback)


def serialize_settings(config: DockwatchConfig, store: ManifestStore) -> dict[str, Any]:
    return {
        "pinned": store.get_pinned(),
        "ignored": store.get_ignored(),
        "notify_only": config.notify_only,
        "include_tags": config.include_tags,
        "exclude_tags": config.exclude_tags,
        "notify_on": config.notify_on,
        "first_check_notify": config.first_check_notify,
        "webhook_url": config.webhook_url,
        "discord_webhook": config.discord_webhook,
        "ntfy_url": config.ntfy_url,
        "schedule_interval_seconds": config.schedule_interval_seconds,
        "schedule_jitter_seconds": config.schedule_jitter_seconds,
        "run_on_startup": config.run_on_startup,
        "max_concurrent_checks": config.max_concurrent_checks,
        "portainer": {
            "enabled": config.portainer.enabled,
            "url": config.portainer.url,
            "api_key": _mask_api_key(config.portainer.api_key),
            "environments": config.portainer.environments,
        },
        "trivy": {
            "enabled": config.trivy.enabled,
            "binary_path": config.trivy.binary_path,
            "severity": config.trivy.severity,
            "scanners": config.trivy.scanners,
            "timeout_seconds": config.trivy.timeout_seconds,
            "skip_db_update": config.trivy.skip_db_update,
            "cache_ttl_minutes": config.trivy.cache_ttl_minutes,
        },
        "compose_projects": {
            key: {
                "workdir": value.workdir,
                "files": value.files,
                "project_name": value.project_name,
            }
            for key, value in config.compose_projects.items()
        },
    }


def deserialize_settings(data: dict[str, Any], existing: DockwatchConfig, store: ManifestStore) -> DockwatchConfig:
    if "pinned" in data:
        store.set_pinned(_ensure_list(data.get("pinned"), store.get_pinned()))
    if "ignored" in data:
        store.set_ignored(_ensure_list(data.get("ignored"), store.get_ignored()))
    existing.notify_only = _ensure_list(data.get("notify_only", existing.notify_only), existing.notify_only)
    existing.include_tags = _ensure_list(data.get("include_tags", existing.include_tags), existing.include_tags)
    existing.exclude_tags = _ensure_list(data.get("exclude_tags", existing.exclude_tags), existing.exclude_tags)
    existing.notify_on = _ensure_list(data.get("notify_on", existing.notify_on), existing.notify_on)
    existing.first_check_notify = data.get("first_check_notify", existing.first_check_notify)
    existing.webhook_url = str(data.get("webhook_url", existing.webhook_url))
    existing.discord_webhook = str(data.get("discord_webhook", existing.discord_webhook))
    existing.ntfy_url = str(data.get("ntfy_url", existing.ntfy_url))
    existing.schedule_interval_seconds = int(data.get("schedule_interval_seconds", existing.schedule_interval_seconds))
    existing.schedule_jitter_seconds = int(data.get("schedule_jitter_seconds", existing.schedule_jitter_seconds))
    existing.run_on_startup = bool(data.get("run_on_startup", existing.run_on_startup))
    existing.max_concurrent_checks = int(data.get("max_concurrent_checks", existing.max_concurrent_checks))

    portainer_data = data.get("portainer", {})
    if isinstance(portainer_data, dict):
        existing.portainer.enabled = bool(portainer_data.get("enabled", existing.portainer.enabled))
        existing.portainer.url = str(portainer_data.get("url", existing.portainer.url))
        existing.portainer.api_key = str(portainer_data.get("api_key", existing.portainer.api_key))
        existing.portainer.environments = _ensure_list(
            portainer_data.get("environments", existing.portainer.environments),
            existing.portainer.environments,
        )

    trivy_data = data.get("trivy", {})
    if isinstance(trivy_data, dict):
        existing.trivy.enabled = bool(trivy_data.get("enabled", existing.trivy.enabled))
        existing.trivy.binary_path = str(trivy_data.get("binary_path", existing.trivy.binary_path))
        existing.trivy.severity = _ensure_list(trivy_data.get("severity", existing.trivy.severity), existing.trivy.severity)
        existing.trivy.scanners = _ensure_list(trivy_data.get("scanners", existing.trivy.scanners), existing.trivy.scanners)
        existing.trivy.timeout_seconds = int(trivy_data.get("timeout_seconds", existing.trivy.timeout_seconds))
        existing.trivy.skip_db_update = bool(trivy_data.get("skip_db_update", existing.trivy.skip_db_update))
        existing.trivy.cache_ttl_minutes = int(trivy_data.get("cache_ttl_minutes", existing.trivy.cache_ttl_minutes))

    compose_data = data.get("compose_projects", None)
    if isinstance(compose_data, dict):
        projects: dict[str, ComposeProjectConfig] = {}
        for key, raw_cfg in compose_data.items():
            if not isinstance(raw_cfg, dict):
                continue
            project_key = str(key).strip()
            if not project_key:
                continue
            projects[project_key] = ComposeProjectConfig(
                workdir=str(raw_cfg.get("workdir", "")),
                files=_ensure_list(raw_cfg.get("files", []), []),
                project_name=str(raw_cfg.get("project_name", "")),
            )
        existing.compose_projects = projects

    return existing
