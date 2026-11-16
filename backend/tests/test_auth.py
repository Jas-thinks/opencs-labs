"""Authentication and session tests."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security import create_session_token, decode_session_token
from app.users.models import User
from tests.conftest import PASSWORD, login


def test_login_success_sets_httponly_cookie(client, users):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "student1@test.local", "password": PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "student1@test.local"
    assert body["user"]["role"] == "student"
    cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie or "samesite=lax" in cookie.lower()
    assert "password" not in response.text
    assert "password_hash" not in response.text


def test_login_wrong_password(client, users):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "student1@test.local", "password": "nope"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_login_unknown_email_is_indistinguishable(client, users):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@test.local", "password": "whatever"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Incorrect email or password"


def test_me_requires_authentication(client):
    response = client.get("/api/v1/me")
    assert response.status_code == 401


def test_me_with_cookie(client, users):
    login(client, "student1@test.local")
    response = client.get("/api/v1/me")
    assert response.status_code == 200
    assert response.json()["hub_username"] == "teststudent1"


def test_logout_clears_session(client, users):
    login(client, "student1@test.local")
    assert client.get("/api/v1/me").status_code == 200
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/me").status_code == 401


def test_bearer_token_for_programmatic_clients(client, users):
    response = client.post(
        "/api/v1/auth/token",
        json={"email": "student1@test.local", "password": PASSWORD},
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "student1@test.local"


def test_tampered_token_rejected(client, users):
    token = create_session_token(
        user_id=str(users["student1@test.local"].id),
        hub_username="teststudent1",
        role="student",
        email="student1@test.local",
        display_name="Student One",
    )
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401


def test_hub_identity_mismatch_rejected(client, users, db: Session):
    token = create_session_token(
        user_id=str(users["student1@test.local"].id),
        hub_username="someone-else",
        role="student",
        email="student1@test.local",
        display_name="Student One",
    )
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_inactive_user_cannot_login(client, db: Session, users):
    user = db.query(User).filter_by(email="student1@test.local").one()
    user.is_active = False
    db.commit()
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "student1@test.local", "password": PASSWORD},
    )
    assert response.status_code == 401


def test_token_contains_hub_username(client, users):
    login(client, "student1@test.local")
    token = client.cookies.get("opencs_session")
    payload = decode_session_token(token)
    assert payload["hub"] == "teststudent1"
    assert payload["role"] == "student"


def test_preferences_update(client, users):
    login(client, "student1@test.local")
    response = client.patch(
        "/api/v1/me/preferences", json={"theme": "light", "editor_font_size": 14}
    )
    assert response.status_code == 200
    assert response.json()["preferences"]["theme"] == "light"
    assert client.get("/api/v1/me/preferences").json()["preferences"]["editor_font_size"] == 14
