"""Tests for the reverse-proxy-aware client IP resolver."""

from __future__ import annotations

from fastapi import Request

from dockwatch.api.client_ip import resolve_client_ip


def _make_request(peer: str, forwarded_for: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    scope = {
        "type": "http",
        "client": (peer, 12345),
        "headers": headers,
    }
    return Request(scope)


def test_no_trusted_proxies_uses_raw_peer(monkeypatch) -> None:
    monkeypatch.delenv("DOCKWATCH_TRUSTED_PROXIES", raising=False)
    request = _make_request("203.0.113.5", forwarded_for="9.9.9.9")
    assert resolve_client_ip(request) == "203.0.113.5"


def test_trusted_proxy_uses_forwarded_ip(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_TRUSTED_PROXIES", "172.18.0.0/16")
    request = _make_request("172.18.0.5", forwarded_for="9.9.9.9, 172.18.0.5")
    assert resolve_client_ip(request) == "9.9.9.9"


def test_untrusted_peer_ignores_forwarded_header(monkeypatch) -> None:
    monkeypatch.setenv("DOCKWATCH_TRUSTED_PROXIES", "172.18.0.0/16")
    request = _make_request("203.0.113.5", forwarded_for="9.9.9.9")
    assert resolve_client_ip(request) == "203.0.113.5"


if __name__ == "__main__":
    import os

    os.environ.pop("DOCKWATCH_TRUSTED_PROXIES", None)
    r = _make_request("203.0.113.5", forwarded_for="9.9.9.9")
    assert resolve_client_ip(r) == "203.0.113.5"

    os.environ["DOCKWATCH_TRUSTED_PROXIES"] = "172.18.0.0/16"
    r = _make_request("172.18.0.5", forwarded_for="9.9.9.9, 172.18.0.5")
    assert resolve_client_ip(r) == "9.9.9.9"

    r = _make_request("203.0.113.5", forwarded_for="9.9.9.9")
    assert resolve_client_ip(r) == "203.0.113.5"

    print("OK")
