"""User and role management endpoints (manage_users permission required)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ...config import hash_password
from ...db import ManifestStore, UserRecord, VALID_PERMISSIONS
from ..deps import get_store
from ..rate_limit import rate_limit
from ..security import AuthenticatedUser, require_auth, require_permission

router = APIRouter()


def _is_last_manage_users_holder(store: ManifestStore, user: UserRecord) -> bool:
    """True when this user holds manage_users and is the only one who does."""
    role = store.get_role(user.role_name)
    if role is None or "manage_users" not in role.permissions:
        return False
    return store.count_users_with_permission("manage_users") <= 1


@router.get("/users", dependencies=[Depends(require_permission("manage_users"))])
def list_users() -> Any:
    store = get_store()
    users = store.list_users()
    return [
        {
            "id": u.id,
            "username": u.username,
            "role_name": u.role_name,
            "created_at": u.created_at,
        }
        for u in users
    ]


@router.post("/users", dependencies=[Depends(require_permission("manage_users")), Depends(rate_limit(10, 60))])
def create_user(body: dict[str, str]) -> Any:
    store = get_store()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    role_name = body.get("role_name", "").strip()

    if not username or not password or not role_name:
        raise HTTPException(status_code=422, detail="username, password, and role_name are required.")
    if len(username) < 2:
        raise HTTPException(status_code=422, detail="Username must be at least 2 characters.")
    if len(password) < 4:
        raise HTTPException(status_code=422, detail="Password must be at least 4 characters.")

    role = store.get_role(role_name)
    if role is None:
        raise HTTPException(status_code=422, detail=f"Role '{role_name}' does not exist.")

    try:
        user_id = store.create_user(username, hash_password(password), role_name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "ok": True,
        "id": user_id,
        "username": username,
        "role_name": role_name,
    }


@router.post("/users/me/onboarding-complete")
def complete_onboarding(current_user: AuthenticatedUser = Depends(require_auth)) -> Any:
    store = get_store()
    store.mark_onboarding_seen(current_user.user_id)
    return {"ok": True}


@router.patch("/users/{user_id}")
def update_user_role(
    user_id: int,
    body: dict[str, str],
    current_user: AuthenticatedUser = Depends(require_permission("manage_users")),
) -> Any:
    store = get_store()
    role_name = body.get("role_name", "").strip()
    if not role_name:
        raise HTTPException(status_code=422, detail="role_name is required.")

    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    role = store.get_role(role_name)
    if role is None:
        raise HTTPException(status_code=422, detail=f"Role '{role_name}' does not exist.")

    if "manage_users" not in role.permissions and _is_last_manage_users_holder(store, user):
        raise HTTPException(
            status_code=409,
            detail="Cannot remove the last user with manage_users permission.",
        )

    store.update_user_role(user_id, role_name)
    return {"ok": True, "id": user_id, "role_name": role_name}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    current_user: AuthenticatedUser = Depends(require_permission("manage_users")),
) -> Any:
    store = get_store()
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if user.id == current_user.user_id:
        raise HTTPException(status_code=409, detail="Cannot delete your own account.")

    if _is_last_manage_users_holder(store, user):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the last user with manage_users permission.",
        )

    store.delete_user(user_id)
    return {"ok": True, "id": user_id}


@router.get("/roles", dependencies=[Depends(require_permission("manage_users"))])
def list_roles() -> Any:
    store = get_store()
    roles = store.list_roles()
    return [
        {
            "name": r.name,
            "permissions": r.permissions,
            "is_builtin": r.is_builtin,
        }
        for r in roles
    ]


@router.post("/roles", dependencies=[Depends(require_permission("manage_users"))])
def create_role(body: dict[str, Any]) -> Any:
    store = get_store()
    name = str(body.get("name", "")).strip()
    permissions: list[str] = [str(p) for p in body.get("permissions", [])]

    if not name:
        raise HTTPException(status_code=422, detail="name is required.")
    if not permissions:
        raise HTTPException(status_code=422, detail="permissions must be a non-empty list.")

    unknown = [p for p in permissions if p not in VALID_PERMISSIONS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown permissions: {', '.join(unknown)}.")

    existing = store.get_role(name)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Role '{name}' already exists.")

    try:
        store.create_role(name, permissions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    role = store.get_role(name)
    return {
        "ok": True,
        "name": role.name,
        "permissions": role.permissions,
        "is_builtin": role.is_builtin,
    }


@router.patch("/roles/{name}", dependencies=[Depends(require_permission("manage_users"))])
def update_role(name: str, body: dict[str, Any]) -> Any:
    store = get_store()
    role = store.get_role(name)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found.")
    if role.is_builtin:
        raise HTTPException(status_code=422, detail="Cannot modify built-in roles.")

    permissions: list[str] = [str(p) for p in body.get("permissions", [])]
    if not permissions:
        raise HTTPException(status_code=422, detail="permissions must be a non-empty list.")

    unknown = [p for p in permissions if p not in VALID_PERMISSIONS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown permissions: {', '.join(unknown)}.")

    try:
        store.update_role_permissions(name, permissions)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    updated = store.get_role(name)
    return {
        "ok": True,
        "name": updated.name,
        "permissions": updated.permissions,
        "is_builtin": updated.is_builtin,
    }


@router.delete("/roles/{name}", dependencies=[Depends(require_permission("manage_users"))])
def delete_role(name: str) -> Any:
    store = get_store()
    role = store.get_role(name)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found.")
    if role.is_builtin:
        raise HTTPException(status_code=422, detail="Cannot delete built-in roles.")

    users_with_role = store.get_users_by_role(name)
    if users_with_role:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete role '{name}': still assigned to {len(users_with_role)} user(s).",
        )

    store.delete_role(name)
    return {"ok": True, "name": name}
