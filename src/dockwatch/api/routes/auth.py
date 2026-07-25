"""Login/logout/session-status endpoints."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from ...config import load_config, verify_password
from ..security import clear_session_cookie, issue_session_cookie, verify_session_cookie

router = APIRouter()

# Simple in-memory brute-force guard, keyed by client IP. Resets on process
# restart -- acceptable for a single-operator tool, no need for anything
# more elaborate than "keep it simple" per the design decision.
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
    if not config.auth.password_hash:
        raise HTTPException(status_code=503, detail="No credentials configured. See server logs.")

    key = _client_key(request)
    if _is_locked_out(key):
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")

    username = body.get("username", "")
    password = body.get("password", "")
    if username != config.auth.username or not verify_password(password, config.auth.password_hash):
        _record_failure(key)
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    issue_session_cookie(response, username, config.auth.secret_key)
    return {"ok": True, "username": username}


@router.post("/auth/logout")
def logout(response: Response) -> Any:
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/session")
def session_status(request: Request) -> Any:
    config = load_config()
    try:
        username = verify_session_cookie(request, config)
    except HTTPException:
        return {"authenticated": False}
    return {"authenticated": True, "username": username}
