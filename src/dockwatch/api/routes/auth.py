"""Login/logout/session-status/registration endpoints."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ...config import hash_password, load_config, verify_password
from ...db import ManifestStore
from ..client_ip import resolve_client_ip
from ..security import (
    AuthenticatedUser,
    clear_session_cookie,
    issue_session_cookie,
    require_auth,
)

router = APIRouter()
logger = logging.getLogger("dockwatch.auth")

_failed_attempts: dict[str, list[float]] = {}
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_WINDOW_SECONDS = 300
_REGISTRATION_RATE_LIMIT = 3
_REGISTRATION_RATE_WINDOW = 60

_cleanup_counter = 0
_CLEANUP_EVERY_N = 100


def _client_key(request: Request) -> str:
    return resolve_client_ip(request)


def _sweep_stale() -> None:
    global _cleanup_counter
    _cleanup_counter += 1
    if _cleanup_counter % _CLEANUP_EVERY_N != 0:
        return
    now = time.monotonic()
    stale = [
        k for k, v in _failed_attempts.items()
        if not v or all(now - t >= _LOCKOUT_WINDOW_SECONDS for t in v)
    ]
    for k in stale:
        del _failed_attempts[k]


def _is_locked_out(key: str, threshold: int = _LOCKOUT_THRESHOLD, window: int = _LOCKOUT_WINDOW_SECONDS) -> bool:
    _sweep_stale()
    now = time.monotonic()
    attempts = [t for t in _failed_attempts.get(key, []) if now - t < window]
    _failed_attempts[key] = attempts
    locked = len(attempts) >= threshold
    if locked:
        logger.warning("lockout active for %s (%d attempts in window)", key, len(attempts))
    return locked


def _record_failure(key: str) -> None:
    _failed_attempts.setdefault(key, []).append(time.monotonic())
    logger.warning("failed attempt from %s", key)


@router.post("/auth/login")
def login(body: dict[str, str], request: Request, response: Response) -> Any:
    config = load_config()
    store = ManifestStore()

    key = _client_key(request)
    if _is_locked_out(key):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

    username = body.get("username", "")
    password = body.get("password", "")

    user = store.get_user_by_username(username)
    if user is None or not verify_password(password, user.password_hash):
        _record_failure(key)
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    issue_session_cookie(response, user.username, user.id, config.auth.secret_key, request)
    logger.info("login success for %r from %s", user.username, key)
    role = store.get_role(user.role_name)
    permissions = role.permissions if role else []
    return {"ok": True, "username": user.username, "role": user.role_name, "permissions": permissions}


@router.post("/auth/logout")
def logout(response: Response) -> Any:
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/session")
def session_status(user: AuthenticatedUser = Depends(require_auth)) -> Any:
    return {
        "authenticated": True,
        "username": user.username,
        "role": user.role_name,
        "permissions": list(user.permissions),
    }


@router.get("/auth/registration-enabled")
def registration_enabled() -> Any:
    store = ManifestStore()
    if store.count_users() == 0:
        return {"enabled": True}
    enabled = os.environ.get("DOCKWATCH_ALLOW_REGISTRATION", "false").strip().lower() == "true"
    return {"enabled": enabled}


@router.post("/auth/register")
def register(body: dict[str, str], request: Request, response: Response) -> Any:
    store = ManifestStore()
    config = load_config()
    total_users = store.count_users()

    if total_users == 0:
        role_name = "admin"
    elif os.environ.get("DOCKWATCH_ALLOW_REGISTRATION", "false").strip().lower() == "true":
        role_name = "viewer"
    else:
        raise HTTPException(status_code=403, detail="Registration is disabled.")

    key = "reg:" + _client_key(request)
    if _is_locked_out(key, threshold=_REGISTRATION_RATE_LIMIT, window=_REGISTRATION_RATE_WINDOW):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Try again later.")

    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=422, detail="Username and password are required.")
    if len(username) < 2:
        raise HTTPException(status_code=422, detail="Username must be at least 2 characters.")
    if len(password) < 4:
        raise HTTPException(status_code=422, detail="Password must be at least 4 characters.")

    try:
        user_id = store.create_user(username, hash_password(password), role_name)
    except ValueError as exc:
        _record_failure(key)
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    issue_session_cookie(response, username, user_id, config.auth.secret_key, request)
    logger.info("new user registered: %r (role=%s) from %s", username, role_name, key)
    role = store.get_role(role_name)
    permissions = role.permissions if role else []
    return {"ok": True, "username": username, "role": role_name, "permissions": permissions}
