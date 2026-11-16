"""Learning paths, lesson content, progress and notebook launch."""

from __future__ import annotations

from tests.conftest import login


def test_paths_tree(student_client, lesson):
    response = student_client.get("/api/v1/learning/paths")
    assert response.status_code == 200
    body = response.json()
    assert body["total_lessons"] == 1
    assert body["completed_lessons"] == 0
    path = body["paths"][0]
    assert path["slug"] == "test-path"
    assert path["modules"][0]["slug"] == "test-module"
    assert path["modules"][0]["lessons"][0]["status"] == "not_started"
    assert path["progress_percent"] == 0


def test_lesson_detail(student_client, lesson, dataset, exercise):
    response = student_client.get("/api/v1/learning/lessons/test-lesson")
    assert response.status_code == 200
    body = response.json()
    assert body["objective"] == "Learn a thing"
    assert [stage["key"] for stage in body["content"]["stages"]][:3] == [
        "explore",
        "understand",
        "inspect",
    ]
    assert body["datasets"][0]["slug"] == "iris"
    assert body["exercises"][0]["slug"] == "test-exercise"
    assert body["progress"]["status"] == "not_started"
    assert body["has_notebook_activity"] is True
    assert body["navigation"]["next"] is None


def test_unknown_lesson(student_client):
    assert student_client.get("/api/v1/learning/lessons/nope").status_code == 404


def test_progress_is_recorded_and_sticky(student_client, lesson):
    response = student_client.post(
        "/api/v1/learning/lessons/test-lesson/progress",
        json={"status": "in_progress", "last_section": "execute"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"

    response = student_client.post(
        "/api/v1/learning/lessons/test-lesson/progress",
        json={"status": "completed", "last_section": "practice"},
    )
    assert response.json()["status"] == "completed"
    assert response.json()["completed_at"]

    # Re-opening the lesson must not reset a completed lesson.
    response = student_client.post(
        "/api/v1/learning/lessons/test-lesson/progress", json={"status": "in_progress"}
    )
    assert response.json()["status"] == "completed"

    paths = student_client.get("/api/v1/learning/paths").json()
    assert paths["completed_lessons"] == 1
    assert paths["paths"][0]["progress_percent"] == 100


def test_invalid_progress_status(student_client, lesson):
    response = student_client.post(
        "/api/v1/learning/lessons/test-lesson/progress", json={"status": "finished"}
    )
    assert response.status_code == 422


def test_launch_lesson_creates_notebook(student_client, lesson, backend, users):
    response = student_client.post("/api/v1/learning/lessons/test-lesson/launch")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["notebook"]["kind"] == "lesson"
    assert body["notebook"]["source_ref"] == "test-lesson"
    assert "Lesson notebook" in body["notebook"]["title"]
    assert "/lab/tree/" in body["url"]

    document = backend.files["teststudent1"][body["notebook"]["file_name"]]
    sources = [cell.get("source", "") for cell in document["cells"]]
    assert any("import pandas" in source for source in sources)
    assert document["metadata"]["opencs"]["lesson"] == "test-lesson"

    # Launching marks the lesson as in progress.
    paths = student_client.get("/api/v1/learning/paths").json()
    assert paths["paths"][0]["modules"][0]["lessons"][0]["status"] == "in_progress"


def test_launch_requires_auth(client, lesson):
    assert client.post("/api/v1/learning/lessons/test-lesson/launch").status_code == 401


def test_progress_is_per_user(student_client, other_student_client, lesson):
    student_client.post(
        "/api/v1/learning/lessons/test-lesson/progress", json={"status": "completed"}
    )
    other = other_student_client.get("/api/v1/learning/paths").json()
    assert other["completed_lessons"] == 0
