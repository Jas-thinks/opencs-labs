"""Authentication services and request dependencies."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import Forbidden, Unauthenticated
from app.core.security import create_session_token, decode_session_token, verify_password
from app.db.session import get_db
from app.users.models import User

SESSION_COOKIE = settings.session_cookie


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        domain=settings.cookie_domain,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        domain=settings.cookie_domain,
    )


def issue_session(user: User) -> str:
    return create_session_token(
        user_id=str(user.id),
        hub_username=user.hub_username,
        role=user.role,
        email=user.email,
        display_name=user.display_name,
    )


def authenticate_dev(db: Session, email: str, password: str) -> User | None:
    if settings.auth_mode != "dev":
        return None
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        # Perform a dummy hash comparison so unknown users take similar time.
        verify_password(password, "$2b$12$" + "x" * 53)
        return None
    if not user.is_active or not verify_password(password, user.password_hash):
        return None
    user.last_login_at = dt.datetime.now(dt.UTC)
    db.commit()
    return user


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip()
    return request.cookies.get(SESSION_COOKIE)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise Unauthenticated()
    try:
        payload = decode_session_token(token)
    except Exception as exc:  # noqa: BLE001 - normalise any JWT failure
        raise Unauthenticated("Session expired or invalid; sign in again") from exc

    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (ValueError, KeyError) as exc:
        raise Unauthenticated("Session expired or invalid; sign in again") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("Account is not active")
    if user.hub_username != payload.get("hub"):
        # The identity mapping must stay stable for the life of a session.
        raise Unauthenticated("Session identity mismatch; sign in again")
    request.state.user = user
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = _extract_token(request)
    if not token:
        return None
    try:
        payload = decode_session_token(token)
    except Exception:  # noqa: BLE001
        return None
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (ValueError, KeyError):
        return None
    user = db.get(User, user_id)
    if user and user.is_active and user.hub_username == payload.get("hub"):
        request.state.user = user
        return user
    return None


def require_roles(*roles: str):
    def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise Forbidden(f"This action requires one of: {', '.join(roles)}")
        return user

    return _dependency


require_admin = require_roles("admin")
require_staff = require_roles("admin", "instructor")


def assert_owner(resource_user_id, user: User) -> None:
    if str(resource_user_id) != str(user.id):
        raise Forbidden("You do not own this resource")
