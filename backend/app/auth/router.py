"""Authentication endpoints.

The browser uses the HttpOnly session cookie. Programmatic clients (CLI,
load tests) may exchange credentials for a bearer token at ``/auth/token``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.schemas import LoginRequest, LoginResponse, TeachingSummary, TokenResponse, UserOut
from app.courses.permissions import teaching_summary
from app.auth.service import (
    authenticate_dev,
    clear_session_cookie,
    get_current_user,
    issue_session,
    set_session_cookie,
)
from app.core.config import settings
from app.core.errors import ApiError, Unauthenticated
from app.db.session import get_db
from app.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = authenticate_dev(db, payload.email, payload.password)
    if user is None:
        raise Unauthenticated("Incorrect email or password")
    token = issue_session(user)
    set_session_cookie(response, token)
    out = UserOut.model_validate(user)
    out.teaching = TeachingSummary(**teaching_summary(db, user))
    return LoginResponse(user=out, expires_in=settings.session_ttl_seconds)


@router.post("/token", response_model=TokenResponse)
def token(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_dev(db, payload.email, payload.password)
    if user is None:
        raise Unauthenticated("Incorrect email or password")
    return TokenResponse(access_token=issue_session(user), expires_in=settings.session_ttl_seconds)


@router.post("/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/mode")
def auth_mode():
    # Safe to expose: only the mode name, never provider configuration.
    return {"mode": settings.auth_mode}
