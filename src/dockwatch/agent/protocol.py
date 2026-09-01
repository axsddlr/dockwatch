"""Wire protocol between a dockwatch agent and the central instance.

The agent serializes its locally discovered containers into plain dicts;
the central deserializes them and stamps its own source/environment
identity onto them. Field set matches ContainerInfo minus the
source/environment fields, which are central-side concerns.
"""

from __future__ import annotations

from ..models import ContainerInfo, RegistryType

# Enforced both when an agent process boots (server.py) and when the central
# instance saves an agent's token (api/serializers.py), so a weak token is
# rejected at save-time instead of failing later at connection time.
MIN_AGENT_TOKEN_LENGTH = 16


def serialize_container_info(info: ContainerInfo) -> dict:
    return {
        "name": info.name,
        "container_id": info.container_id,
        "image_ref": info.image_ref,
        "registry": info.registry.value,
        "namespace": info.namespace,
        "image_name": info.image_name,
        "current_tag": info.current_tag,
        "labels": dict(info.labels),
        "version_label": info.version_label,
        "compose_image_digest": info.compose_image_digest,
        "repo_digest": info.repo_digest,
        "watch_enabled": info.watch_enabled,
        "pinned_override": info.pinned_override,
        "ignored_override": info.ignored_override,
        "notify_enabled": info.notify_enabled,
        "include_tags_override": (
            list(info.include_tags_override) if info.include_tags_override is not None else None
        ),
        "exclude_tags_override": (
            list(info.exclude_tags_override) if info.exclude_tags_override is not None else None
        ),
        "update_delay_days_override": info.update_delay_days_override,
        "compose_project": info.compose_project,
        "compose_service": info.compose_service,
    }


def deserialize_container_info(payload: dict) -> ContainerInfo:
    registry_raw = str(payload.get("registry") or "")
    try:
        registry = RegistryType(registry_raw)
    except ValueError:
        registry = RegistryType.UNKNOWN
    return ContainerInfo(
        name=str(payload.get("name") or ""),
        container_id=str(payload.get("container_id") or ""),
        image_ref=str(payload.get("image_ref") or ""),
        registry=registry,
        namespace=str(payload.get("namespace") or ""),
        image_name=str(payload.get("image_name") or ""),
        current_tag=str(payload.get("current_tag") or ""),
        labels=dict(payload.get("labels") or {}),
        version_label=_opt_str(payload.get("version_label")),
        compose_image_digest=_opt_str(payload.get("compose_image_digest")),
        repo_digest=_opt_str(payload.get("repo_digest")),
        watch_enabled=_opt_bool(payload.get("watch_enabled")),
        pinned_override=_opt_bool(payload.get("pinned_override")),
        ignored_override=_opt_bool(payload.get("ignored_override")),
        notify_enabled=_opt_bool(payload.get("notify_enabled")),
        include_tags_override=_opt_list(payload.get("include_tags_override")),
        exclude_tags_override=_opt_list(payload.get("exclude_tags_override")),
        update_delay_days_override=_opt_int(payload.get("update_delay_days_override")),
        compose_project=_opt_str(payload.get("compose_project")),
        compose_service=_opt_str(payload.get("compose_service")),
    )


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _opt_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _opt_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _opt_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    return None
