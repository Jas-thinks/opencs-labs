"""Cryptographic primitives: password hashing and session JWTs."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

PASSWORD_MAX_BYTES = 72


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")[:PASSWORD_MAX_BYTES]
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    encoded = password.encode("utf-8")[:PASSWORD_MAX_BYTES]
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("ascii"))
    except ValueError:
        return False


def create_session_token(
    *,
    user_id: str,
    hub_username: str,
    role: str,
    email: str,
    display_name: str,
    ttl_seconds: int | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    now = dt.datetime.now(dt.UTC)
    ttl = ttl_seconds or settings.session_ttl_seconds
    payload: dict[str, Any] = {
        "iss": settings.jwt_issuer,
        "sub": user_id,
        "hub": hub_username,
        "role": role,
        "email": email,
        "name": display_name,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + dt.timedelta(seconds=ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_session_token(token: str) -> dict[str, Any]:
    """Decode and validate a session token.

    Raises ``jwt.PyJWTError`` for invalid, expired or wrongly signed tokens.
    """
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        issuer=settings.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "hub", "iss"]},
    )
