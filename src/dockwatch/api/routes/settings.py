"""Settings management endpoints."""

from __future__ import annotations

import asyncio
import ipaddress
import secrets
import socket
import threading
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from ...config import hooks_enabled, load_config, save_config
from ...integrations import AgentClient, AgentError, PortainerClient, PortainerError
from ...models import ContainerInfo, RegistryType, UpdateResult
from ...notifiers import send_configured_notifications
from ..deps import get_config, get_store
from ..rate_limit import rate_limit
from ..security import require_permission
from ..serializers import deserialize_settings, serialize_settings

router = APIRouter()
_mutate_limit = Depends(rate_limit(10, 60))

# PUT handlers run in FastAPI's threadpool; serialize the config
# read-modify-write cycle so concurrent saves cannot drop each other's changes.
_settings_write_lock = threading.Lock()


_HOOK_PHASES = ("pre_update", "post_update", "pre_stop", "pre_rollback", "post_rollback")


def _normalize_hooks(hooks: Any) -> Any:
    """Return ``hooks`` with blank commands filtered out of every phase list.

    The dashboard's ``cleanHooks`` rewrites stored empty-string commands to
    ``[]`` before saving; comparing blank-containing stored hooks against the
    blank-filtered payload would otherwise register a spurious change and trip
    the hooks gate. Filtering blanks from both sides makes the comparison robust
    to that transform regardless of which side carries the blanks.
    """
    if not isinstance(hooks, dict):
        return hooks
    normalized: dict[str, Any] = {}
    for name, raw_cfg in hooks.items():
        if not isinstance(raw_cfg, dict):
            normalized[name] = raw_cfg
            continue
        phases: dict[str, Any] = {}
        for key, value in raw_cfg.items():
            if key in _HOOK_PHASES and isinstance(value, list):
                phases[key] = [item for item in value if str(item).strip()]
            else:
                phases[key] = value
        normalized[name] = phases
    return normalized


def _hooks_changed(body: dict[str, Any], current: dict[str, Any]) -> bool:
    """True when the incoming hooks/hook_defaults differ from what is stored."""
    incoming_hooks = _normalize_hooks(body.get("hooks"))
    incoming_defaults = body.get("hook_defaults")
    if incoming_hooks is not None and incoming_hooks != _normalize_hooks(current.get("hooks")):
        return True
    if incoming_defaults is not None and incoming_defaults != current.get("hook_defaults"):
        return True
    return False


def _is_restricted_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validate_public_url(raw: str) -> str:
    """SSRF guard for URLs dockwatch's server will request (webhook/discord/
    ntfy notification URLs, Portainer URL). Rejects non-http(s) schemes, URLs
    whose literal host is a private/reserved address, and hostnames that
    resolve only to private/reserved addresses (e.g. cloud metadata or an
    internal service)."""
    url = raw.strip()
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail=f"Unsupported URL scheme: {parsed.scheme}")
    host = parsed.hostname
    if host is None:
        raise HTTPException(status_code=422, detail="URL must include a hostname.")
    try:
        ip = ipaddress.ip_address(host)
        if _is_restricted_ip(ip):
            raise HTTPException(
                status_code=422, detail=f"URL must not target private or loopback addresses: {host}"
            )
        return url
    except ValueError:
        pass
    # Hostname — resolve and block only when every address is restricted, so
    # a round-robin/CDN host that also has a public address still passes.
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"URL hostname does not resolve: {host}") from exc
    addresses = {info[4][0] for info in infos}
    ips = []
    for address in addresses:
        try:
            ips.append(ipaddress.ip_address(address))
        except ValueError:
            continue
    if not ips:
        raise HTTPException(status_code=422, detail=f"URL hostname does not resolve: {host}")
    if all(_is_restricted_ip(ip) for ip in ips):
        raise HTTPException(
            status_code=422, detail=f"URL must not target private or loopback addresses: {host}"
        )
    return url


def _validate_agent_url(raw: str) -> str:
    """Loose URL check for agent endpoints.

    Agents are explicitly trusted by the admin (and usually live on
    LAN/VPN/private networks), so unlike notification URLs this does NOT
    apply the SSRF private-address restriction — only scheme + hostname
    sanity.
    """
    url = raw.strip()
    if not url:
        raise HTTPException(status_code=422, detail="Agent URL must not be empty.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail=f"Unsupported agent URL scheme: {parsed.scheme}")
    if parsed.hostname is None:
        raise HTTPException(status_code=422, detail="Agent URL must include a hostname.")
    return url


@router.get("/settings", dependencies=[Depends(require_permission("manage_settings"))])
def get_settings() -> Any:
    config = get_config()
    store = get_store()
    return serialize_settings(config, store)


@router.put("/settings", dependencies=[Depends(require_permission("manage_settings")), _mutate_limit])
def put_settings(body: dict[str, Any]) -> Any:
    with _settings_write_lock:
        existing = load_config()
        store = get_store()
        current = serialize_settings(existing, store)
        # Hooks master gate: hook execution is inert unless the operator opts
        # in via DOCKWATCH_ENABLE_HOOKS=true. Only reject when the hook config
        # actually changes, so echoed-back hooks never break unrelated saves.
        # This must run BEFORE deserialize_settings, which mutates the store
        # (pinned/ignored/auto_update), so a rejected request has no side
        # effects at all.
        if not hooks_enabled() and _hooks_changed(body, current):
            raise HTTPException(
                status_code=422,
                detail="Hooks are disabled. Set DOCKWATCH_ENABLE_HOOKS=true to configure hooks.",
            )
        try:
            updated = deserialize_settings(body, existing, store)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"invalid settings value: {exc}") from exc
        # SSRF guard: notification URLs must not target private/reserved networks.
        for field in ("webhook_url", "discord_webhook", "ntfy_url"):
            value = getattr(updated, field)
            if value:
                _validate_public_url(value)
        save_config(updated)
    return serialize_settings(updated, store)


@router.post("/settings/test-notification", dependencies=[Depends(require_permission("manage_settings"))])
async def test_notification() -> Any:
    config = load_config()
    test_result = UpdateResult(
        container_info=ContainerInfo(
            name="dockwatch-test",
            container_id="test",
            image_ref="ghcr.io/example/app:1.0.0",
            registry=RegistryType.GHCR,
            namespace="example",
            image_name="app",
            current_tag="1.0.0",
        ),
        latest_tag="1.1.0",
        is_outdated=True,
        status=None,
        event="update",
        deployed_tag="1.0.0",
        remote_tag="1.1.0",
        comparison_basis="version",
        comparison_reason="remote version 1.1.0 is newer than deployed 1.0.0",
    )
    errors = await send_configured_notifications([test_result], config, apply_filters=False)
    if errors:
        raise HTTPException(status_code=502, detail="; ".join(errors))
    return {"ok": True, "message": "Test notification sent."}


@router.post("/settings/generate-agent-token", dependencies=[Depends(require_permission("manage_settings"))])
def generate_agent_token() -> Any:
    return {"token": secrets.token_hex(32)}


@router.post("/settings/test-agent", dependencies=[Depends(require_permission("manage_settings")), _mutate_limit])
def test_agent(body: dict[str, str]) -> Any:
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=422, detail="'name' is required.")
    config = load_config()
    agent = next((a for a in config.agents if a.name == name), None)
    if agent is None:
        raise HTTPException(status_code=422, detail=f"agent '{name}' is not configured.")
    if not agent.enabled:
        raise HTTPException(status_code=422, detail=f"agent '{name}' is disabled.")
    _validate_agent_url(agent.url)
    try:
        client = AgentClient(base_url=agent.url, token=agent.token)
        health = asyncio.run(client.health())
        containers = asyncio.run(client.list_containers())
    except AgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        "ok": True,
        "name": name,
        "version": health.get("version"),
        "docker": health.get("docker"),
        "containers": len(containers),
    }


@router.post("/settings/test-portainer", dependencies=[Depends(require_permission("manage_settings")), _mutate_limit])
def test_portainer(body: dict[str, str]) -> Any:
    url = body.get("url", "").strip()
    api_key = body.get("api_key", "").strip()
    if not url or not api_key:
        raise HTTPException(status_code=422, detail="Both 'url' and 'api_key' are required.")

    url = _validate_public_url(url)

    try:
        client = PortainerClient(base_url=url, api_key=api_key)
    except PortainerError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        environments = asyncio.run(client.test_connection())
    except PortainerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"ok": True, "environments": [{"id": e.id, "name": e.name} for e in environments]}
