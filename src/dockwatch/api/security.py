"""Session-cookie authentication for the dockwatch API and WebSocket."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import DockwatchConfig, load_config
from ..db import ManifestStore
from .client_ip import is_trusted_peer

logger = logging.getLogger("dockwatch.auth")

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


def _request_is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    # X-Forwarded-Proto is only trustworthy if DOCKWATCH_TRUSTED_PROXIES is
    # configured and the immediate peer is in it — otherwise any client can
    # set this header themselves. If no trusted-proxy list is configured we
    # fall back to trusting it unconditionally (same as before), since that's
    # the common single-hop/no-proxy deployment and we have no better signal.
    if os.environ.get("DOCKWATCH_TRUSTED_PROXIES", "").strip() and not is_trusted_peer(request):
        return False
    return request.headers.get("x-forwarded-proto", "").strip().lower() == "https"


def issue_session_cookie(
    response: Response,
    username: str,
    user_id: int,
    secret_key: str,
    request: Request,
    session_version: int = 0,
) -> None:
    token = _serializer(secret_key).dumps({"u": username, "uid": user_id, "sv": session_version})
    override = os.environ.get("DOCKWATCH_SECURE_COOKIE", "").strip().lower()
    if override == "true":
        secure = True
    elif override == "false":
        secure = False
    else:
        secure = _request_is_https(request)
        if not secure:
            logger.warning(
                "session cookie issued without Secure flag: no HTTPS detected "
                "(request scheme=%s, X-Forwarded-Proto=%r). If this instance sits "
                "behind a TLS-terminating reverse proxy, set "
                "DOCKWATCH_SECURE_COOKIE=true in .env.",
                request.url.scheme, request.headers.get("x-forwarded-proto"),
            )
    response.set_cookie(
        _COOKIE_NAME, token, httponly=True, secure=secure, samesite="lax", max_age=_MAX_AGE,
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
    except (BadSignature, SignatureExpired) as exc:
        logger.warning("rejected session cookie: %s", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    if "uid" not in data:
        raise HTTPException(status_code=401, detail="Session needs re-authentication.")
    return data


def require_auth(request: Request) -> AuthenticatedUser:
    config = load_config()
    data = _verify_raw_cookie(request, config)
    user_id = data["uid"]
    store = ManifestStore()
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User account no longer exists.")
    if data.get("sv") != user.session_version:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
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
            logger.warning(
                "permission denied: user %r (role=%s) missing %r",
                user.username, user.role_name, permission,
            )
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return user
    return _check
