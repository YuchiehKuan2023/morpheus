"""
Authentication routes for the DFP platform.

Endpoints:
  POST /login   — authenticate analyst, return JWT in httpOnly cookie
  GET  /me      — return current analyst profile from JWT
  POST /logout  — clear the auth cookie

No registration endpoint — analyst accounts are admin-managed in the DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg2.extras
from auth_utils import (
    JWT_EXPIRE_MINUTES,
    LOCKOUT_MINUTES,
    MAX_FAILED_ATTEMPTS,
    create_access_token,
    get_current_user,
    verify_password,
)
from db import get_db
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class UserProfile(BaseModel):
    id: int
    username: str
    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    analyst_role: str
    level: int
    avatar_color: str | None = None
    avatar_initials: str | None = None
    avatar_url: str | None = None
    is_active: bool = True


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------


@router.post("/login")
def login(body: LoginRequest, response: Response):
    """Authenticate an analyst and return a JWT in an httpOnly cookie."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, username, display_name, first_name, last_name, email,
                       analyst_role, level, avatar_color, avatar_initials, avatar_url,
                       is_active, password_hash, failed_login_count, locked_until
                FROM analyst_users
                WHERE username = %s
                """,
                (body.username,),
            )
            user = cur.fetchone()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")

    # Check lockout
    now = datetime.now(timezone.utc)
    if user["locked_until"] and user["locked_until"] > now:
        remaining = int((user["locked_until"] - now).total_seconds() / 60) + 1
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account locked due to too many failed attempts. Try again in {remaining} minute(s).",
        )

    if not user["password_hash"] or not verify_password(body.password, user["password_hash"]):
        # Increment failed count, possibly lock
        with get_db() as conn:
            with conn.cursor() as cur:
                new_count = (user["failed_login_count"] or 0) + 1
                locked_until = None
                if new_count >= MAX_FAILED_ATTEMPTS:
                    locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
                cur.execute(
                    """
                    UPDATE analyst_users
                    SET failed_login_count = %s, locked_until = %s
                    WHERE id = %s
                    """,
                    (new_count, locked_until, user["id"]),
                )
                conn.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Successful login — reset failed count, record login time
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE analyst_users
                SET failed_login_count = 0, locked_until = NULL, last_login_at = %s
                WHERE id = %s
                """,
                (now, user["id"]),
            )
            conn.commit()

    token = create_access_token({"sub": str(user["id"]), "username": user["username"]})

    response.set_cookie(
        key="dfp_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # PoC runs on localhost — set True in production
        max_age=JWT_EXPIRE_MINUTES * 60,
        path="/",
    )

    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "first_name": user["first_name"],
            "last_name": user["last_name"],
            "email": user["email"],
            "analyst_role": user["analyst_role"],
            "level": user["level"],
            "avatar_color": user["avatar_color"],
            "avatar_initials": user["avatar_initials"],
            "avatar_url": user.get("avatar_url"),
        },
        "token": token,
    }


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------


@router.get("/me")
def me(request: Request):
    """Return the current analyst profile from the JWT."""
    user = get_current_user(request)
    return {"user": user}


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------


@router.post("/logout")
def logout(request: Request, response: Response):
    """Clear the auth cookie and record logout time."""
    # Try to record logout time if the user has a valid token
    try:
        user = get_current_user(request)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE analyst_users SET last_logout_at = NOW() WHERE id = %s",
                    (user["id"],),
                )
                conn.commit()
    except HTTPException:
        pass  # Token already expired or invalid — just clear the cookie

    response.delete_cookie(key="dfp_token", path="/")
    return {"message": "Logged out"}
