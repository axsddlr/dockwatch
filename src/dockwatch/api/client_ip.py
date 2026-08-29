"""Resolve the client IP to use for rate-limiting/lockout keys.

Reverse-proxy-aware: only trusts X-Forwarded-For when the immediate TCP
peer is a configured trusted proxy, so an untrusted client can't spoof
the header to evade rate limiting or frame another IP.
"""

from __future__ import annotations

import ipaddress
import os

from fastapi import Request


def _trusted_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.environ.get("DOCKWATCH_TRUSTED_PROXIES", "").strip()
    if not raw:
        return []
    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return networks


def is_trusted_peer(request: Request) -> bool:
    """True if the immediate TCP peer is in DOCKWATCH_TRUSTED_PROXIES.

    Shared by resolve_client_ip (X-Forwarded-For) and security.py
    (X-Forwarded-Proto) — both headers are only meaningful if they were
    set by a proxy we actually trust, not forwarded verbatim from an
    untrusted client.
    """
    peer = request.client.host if request.client else "unknown"
    trusted = _trusted_networks()
    if not trusted or peer == "unknown":
        return False
    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(peer_addr in net for net in trusted)


def resolve_client_ip(request: Request) -> str:
    """Return the client IP to use for rate-limiting/lockout keys.

    Only trusts X-Forwarded-For when the immediate TCP peer is in the
    configured trusted-proxy set (DOCKWATCH_TRUSTED_PROXIES env var,
    comma-separated CIDRs or IPs). Otherwise falls back to the raw peer
    IP. Never trusts X-Forwarded-For unconditionally — an untrusted
    peer could spoof it to evade rate limiting or frame another IP.
    """
    peer = request.client.host if request.client else "unknown"

    if not is_trusted_peer(request):
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer

    first = forwarded.split(",")[0].strip()
    return first or peer
