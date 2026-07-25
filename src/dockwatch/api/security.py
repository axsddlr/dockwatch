"""Session-cookie authentication for the dockwatch API and WebSocket."""

from __future__ import annotations

from typing import Protocol

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import DockwatchConfig, load_config

_COOKIE_NAME = "dockwatch_session"
_MAX_AGE = 60 * 60 * 24 * 14  # 14 days


class _HasCookies(Protocol):
    cookies: dict[str, str]


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="dockwatch-session")


def issue_session_cookie(response: Response, username: str, secret_key: str) -> None:
    token = _serializer(secret_key).dumps({"u": username})
    # secure=False: this tool is commonly reached over plain HTTP on a LAN.
    # Put a TLS-terminating reverse proxy in front of it for internet exposure.
    response.set_cookie(
        _COOKIE_NAME, token, httponly=True, samesite="lax", max_age=_MAX_AGE,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(_COOKIE_NAME)


def verify_session_cookie(conn: _HasCookies, config: DockwatchConfig) -> str:
    """Returns the signed-in username, or raises HTTPException(401/503)."""
    if not config.auth.password_hash:
        raise HTTPException(status_code=503, detail="No dashboard credentials configured.")
    token = conn.cookies.get(_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        data = _serializer(config.auth.secret_key).loads(token, max_age=_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    return data["u"]


def require_auth(request: Request) -> str:
    return verify_session_cookie(request, load_config())
