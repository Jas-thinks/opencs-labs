"""Cross-cutting integration tests.

These exercise the whole HTTP surface through the real application with only
the infrastructure seam faked. Marked ``integration`` so they can be selected
with ``pytest -m integration``.
"""

from __future__ import annotations

import pytest

from app.core.config import settings

pytestmark = pytest.mark.integration


def test_student_journey_learn_practice_notebook(student_client, lesson, exercise, dataset):
    client = student_client

    paths = client.get("/api/v1/learning/paths")
    assert paths.status_code == 200
    assert paths.json()["total_lessons"] >= 1

    detail = client.get(f"/api/v1/learning/lessons/{lesson.slug}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["slug"] == lesson.slug
    assert [dataset["slug"] for dataset in body["datasets"]] == ["iris"]

    progress = client.post(
        f"/api/v1/learning/lessons/{lesson.slug}/progress",
        json={"status": "completed", "last_section": "practice"},
    )
    assert progress.status_code == 200
    assert progress.json()["status"] == "completed"

    launch = client.post(f"/api/v1/learning/lessons/{lesson.slug}/launch")
    assert launch.status_code == 200
    assert launch.json()["notebook"]["kind"] == "lesson"

    attempt = client.post(f"/api/v1/practice/exercises/{exercise.slug}/attempts")
    assert attempt.status_code == 201
    attempt_body = attempt.json()
    assert attempt_body["notebook"]["kind"] == "practice"
    assert len(attempt_body["hints"]) == 2

    feedback = client.post(f"/api/v1/practice/attempts/{attempt_body['attempt']['id']}/evaluate")
    assert feedback.status_code == 200
    assert feedback.json()["passed"] is True


def test_dataset_snippet_never_auto_executes(student_client, dataset):
    response = student_client.get("/api/v1/datasets/iris/snippet")
    assert response.status_code == 200
    body = response.json()
    assert body["auto_execute"] is False
    assert body["cell_type"] == "code"
    assert "read_csv" in body["code"]
    assert body["read_only"] is True
    assert body["path"].startswith(f"{settings.dataset_mount_path.rstrip('/')}/")


def test_notebook_crud_round_trip(student_client):
    client = student_client

    created = client.post("/api/v1/notebooks", json={"title": "Integration Notebook"})
    assert created.status_code == 201
    notebook = created.json()
    notebook_id = notebook["id"]

    listed = client.get("/api/v1/notebooks")
    assert listed.status_code == 200
    assert any(item["id"] == notebook_id for item in listed.json()["notebooks"])

    renamed = client.patch(f"/api/v1/notebooks/{notebook_id}", json={"title": "Renamed Notebook"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Renamed Notebook"

    opened = client.get(f"/api/v1/notebooks/{notebook_id}/open")
    assert opened.status_code == 200
    assert notebook_id == opened.json()["notebook"]["id"]

    downloaded = client.get(f"/api/v1/notebooks/{notebook_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/x-ipynb+json")

    deleted = client.delete(f"/api/v1/notebooks/{notebook_id}")
    assert deleted.status_code == 204


def test_second_student_isolation(student_client, other_student_client):
    created = student_client.post("/api/v1/notebooks", json={"title": "Private Notebook"})
    assert created.status_code == 201
    notebook_id = created.json()["id"]

    # The other student must not see or open it.
    listed = other_student_client.get("/api/v1/notebooks")
    assert all(item["id"] != notebook_id for item in listed.json()["notebooks"])

    blocked = other_student_client.get(f"/api/v1/notebooks/{notebook_id}/open")
    assert blocked.status_code == 404
    assert blocked.json()["error"]["code"] == "NOT_FOUND"


def test_unauthenticated_requests_are_rejected(client, lesson):
    assert client.get("/api/v1/learning/paths").status_code == 401
    assert client.get("/api/v1/datasets").status_code == 401
    assert client.get("/api/v1/notebooks").status_code == 401


def test_health_and_readiness(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["database"] == "ok"
