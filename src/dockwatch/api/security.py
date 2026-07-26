"""Session-cookie authentication for the dockwatch API and WebSocket."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import DockwatchConfig, load_config
from ..db import ManifestStore

_COOKIE_NAME = "dockwatch_session"
_MAX_AGE = 60 * 60 * 24 * 14  # 14 days


class _HasCookies(Protocol):
    cookies: dict[str, str]


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="dockwatch-session")


@dataclass(slots=True)
class AuthenticatedUser:
    user_id: int
    username: str
    role_name: str
    permissions: frozenset[str]


def issue_session_cookie(response: Response, username: str, user_id: int, secret_key: str) -> None:
    token = _serializer(secret_key).dumps({"u": username, "uid": user_id})
    # secure=False: this tool is commonly reached over plain HTTP on a LAN.
    # Put a TLS-terminating reverse proxy in front of it for internet exposure.
    response.set_cookie(
        _COOKIE_NAME, token, httponly=True, samesite="lax", max_age=_MAX_AGE,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(_COOKIE_NAME)


def _verify_raw_cookie(conn: _HasCookies, config: DockwatchConfig) -> dict:
    # Credentials live in the users table now, not config.auth — a fresh
    # install bootstraps its first admin via /auth/register, so an empty
    # config.auth.password_hash must not block cookie verification.
    token = conn.cookies.get(_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        data = _serializer(config.auth.secret_key).loads(token, max_age=_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    if "uid" not in data:
        raise HTTPException(status_code=401, detail="Session needs re-authentication.")
    return data


def verify_session_cookie(conn: _HasCookies, config: DockwatchConfig) -> str:
    """Returns the signed-in username, or raises HTTPException(401).
    Legacy method kept for backward compatibility.
    """
    data = _verify_raw_cookie(conn, config)
    return data["u"]


def require_auth(request: Request) -> AuthenticatedUser:
    config = load_config()
    data = _verify_raw_cookie(request, config)
    user_id = data["uid"]
    store = ManifestStore()
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User account no longer exists.")
    role = store.get_role(user.role_name)
    if role is None:
        raise HTTPException(status_code=401, detail="Role no longer exists.")
    return AuthenticatedUser(
        user_id=user.id,
        username=user.username,
        role_name=user.role_name,
        permissions=frozenset(role.permissions),
    )


def require_permission(permission: str):
    def _check(user: AuthenticatedUser = Depends(require_auth)) -> AuthenticatedUser:
        if permission not in user.permissions:
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return user
    return _check
