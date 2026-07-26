"""Login/logout/session-status/registration endpoints."""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from ...config import hash_password, load_config, verify_password
from ...db import ManifestStore
from ..security import (
    clear_session_cookie,
    issue_session_cookie,
    verify_session_cookie,
)

router = APIRouter()

_failed_attempts: dict[str, list[float]] = {}
_LOCKOUT_THRESHOLD = 5
_LOCKOUT_WINDOW_SECONDS = 300


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_locked_out(key: str) -> bool:
    now = time.monotonic()
    attempts = [t for t in _failed_attempts.get(key, []) if now - t < _LOCKOUT_WINDOW_SECONDS]
    _failed_attempts[key] = attempts
    return len(attempts) >= _LOCKOUT_THRESHOLD


def _record_failure(key: str) -> None:
    _failed_attempts.setdefault(key, []).append(time.monotonic())


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

    issue_session_cookie(response, user.username, user.id, config.auth.secret_key)
    role = store.get_role(user.role_name)
    permissions = role.permissions if role else []
    return {"ok": True, "username": user.username, "role": user.role_name, "permissions": permissions}


@router.post("/auth/logout")
def logout(response: Response) -> Any:
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/session")
def session_status(request: Request) -> Any:
    config = load_config()
    store = ManifestStore()
    try:
        username = verify_session_cookie(request, config)
    except HTTPException:
        return {"authenticated": False}

    user = store.get_user_by_username(username)
    if user is None:
        return {"authenticated": False}

    role = store.get_role(user.role_name)
    permissions = role.permissions if role else []
    return {
        "authenticated": True,
        "username": user.username,
        "role": user.role_name,
        "permissions": permissions,
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
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    issue_session_cookie(response, username, user_id, config.auth.secret_key)
    role = store.get_role(role_name)
    permissions = role.permissions if role else []
    return {"ok": True, "username": username, "role": role_name, "permissions": permissions}
