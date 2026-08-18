"""Per-IP+route rate limiting for mutating API endpoints."""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

from .client_ip import resolve_client_ip

_buckets: dict[str, list[float]] = defaultdict(list)


def rate_limit(max_calls: int, window_seconds: int):
    """FastAPI dependency: allow `max_calls` per `window_seconds`, per client IP + path."""

    def _check(request: Request) -> None:
        client = resolve_client_ip(request)
        key = f"{client}:{request.url.path}"
        now = time.monotonic()
        calls = [t for t in _buckets[key] if now - t < window_seconds]
        if len(calls) >= max_calls:
            raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
        calls.append(now)
        _buckets[key] = calls

    return _check
