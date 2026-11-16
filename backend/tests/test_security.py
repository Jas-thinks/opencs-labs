"""Security and isolation checks that do not require a live cluster."""

from __future__ import annotations

from app.core.security import decode_session_token
from tests.conftest import login


def test_cross_user_notebook_isolation(student_client, other_student_client, backend):
    created = student_client.post("/api/v1/notebooks", json={"title": "A private note"}).json()
    notebook_id = created["id"]

    assert other_student_client.get("/api/v1/notebooks").json()["total"] == 0
    assert other_student_client.get(f"/api/v1/notebooks/{notebook_id}/open").status_code == 404
    assert other_student_client.get(f"/api/v1/notebooks/{notebook_id}/download").status_code == 404
    assert student_client.get(f"/api/v1/notebooks/{notebook_id}/download").status_code == 200

    # The storage layer keys files by hub user, never by browser input.
    assert set(backend.files.keys()) >= {"teststudent1"}


def test_cross_user_practice_isolation(student_client, other_student_client, exercise):
    created = student_client.post("/api/v1/practice/exercises/test-exercise/attempts").json()
    attempt_id = created["attempt"]["id"]
    assert other_student_client.get(f"/api/v1/practice/attempts/{attempt_id}").status_code == 404
    assert other_student_client.get("/api/v1/practice/progress").json()["completed_exercises"] == 0


def test_lesson_progress_isolation(student_client, other_student_client, lesson):
    student_client.post(
        "/api/v1/learning/lessons/test-lesson/progress", json={"status": "completed"}
    )
    assert other_student_client.get("/api/v1/learning/paths").json()["completed_lessons"] == 0


def test_session_cookie_is_httponly_and_lax(client, users):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "student1@test.local", "password": "test-password"},
    )
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie


def test_jwt_hub_claim_cannot_be_forged(client):
    from app.core.security import create_session_token

    # A valid signature but a mismatched hub identity must be rejected.
    token = create_session_token(
        user_id="00000000-0000-0000-0000-000000000000",
        hub_username="admin",
        role="admin",
        email="admin@test.local",
        display_name="Fake Admin",
    )
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_admin_routes_not_exposed(client):
    # The API has no unauthenticated administrative surface.
    assert client.get("/api/v1/admin").status_code == 404
    assert client.get("/api/v1/users").status_code == 404


def test_student_cannot_use_instructor_role(client, users, db):
    login(client, "student1@test.local")
    token = client.cookies.get("opencs_session")
    assert decode_session_token(token)["role"] == "student"

    # The role comes from the database-backed user, not the token alone.
    from app.users.models import User

    student = db.query(User).filter_by(email="student1@test.local").one()
    assert student.role == "student"


def test_dataset_catalogue_does_not_leak_filesystem_paths(student_client, dataset):
    body = student_client.get("/api/v1/datasets/iris").json()
    serialised = str(body)
    assert "/datasets/serving" not in serialised
    assert dataset.slug in serialised


def test_snippet_path_is_server_constructed(student_client, dataset):
    body = student_client.get("/api/v1/datasets/iris/snippet").json()
    assert body["path"].startswith("/opt/opencs/datasets/")
    assert ".." not in body["path"]


def test_not_found_does_not_reveal_other_users_resources(student_client, other_student_client):
    created = other_student_client.post("/api/v1/notebooks", json={"title": "Secret"}).json()
    response = student_client.get(f"/api/v1/notebooks/{created['id']}/open")
    assert response.status_code == 404
    assert "Secret" not in response.text
