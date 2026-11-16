"""Practice catalogue, attempts, evaluation and feedback."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.practice.models import Exercise
from tests.conftest import login


def test_list_and_filter(student_client, exercise):
    response = student_client.get("/api/v1/practice/exercises")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["exercises"][0]["slug"] == "test-exercise"
    assert body["exercises"][0]["has_automated_checks"] is True
    assert body["exercises"][0]["completed"] is False

    assert student_client.get("/api/v1/practice/exercises", params={"difficulty": "Easy"}).json()["total"] == 1
    assert student_client.get("/api/v1/practice/exercises", params={"difficulty": "Hard"}).json()["total"] == 0
    assert student_client.get("/api/v1/practice/exercises", params={"topic": "Pandas"}).json()["total"] == 1
    assert student_client.get("/api/v1/practice/exercises", params={"q": "thing"}).json()["total"] == 1


def test_invalid_difficulty_filter(student_client):
    assert student_client.get("/api/v1/practice/exercises", params={"difficulty": "Extreme"}).status_code == 422


def test_topics_and_progress(student_client, exercise):
    assert student_client.get("/api/v1/practice/topics").json() == [{"topic": "Pandas", "count": 1}]
    progress = student_client.get("/api/v1/practice/progress").json()
    assert progress["total_exercises"] == 1
    assert progress["completed_exercises"] == 0


def test_detail_never_exposes_hidden_material(student_client, exercise, dataset):
    response = student_client.get("/api/v1/practice/exercises/test-exercise")
    assert response.status_code == 200
    body = response.json()
    assert body["hints"][0]["text"] == "first hint"
    assert body["datasets"][0]["slug"] == "iris"
    assert "secret solution" not in response.text
    assert "assert 'df' in globals()" not in response.text
    assert "evaluation" not in body
    assert "solution_code" not in body


def test_create_attempt(student_client, exercise, backend, users):
    response = student_client.post("/api/v1/practice/exercises/test-exercise/attempts")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["attempt"]["attempt_number"] == 1
    assert body["attempt"]["status"] == "in_progress"
    assert body["notebook"]["kind"] == "practice"
    assert body["notebook"]["source_ref"] == "test-exercise"
    assert body["hints"][0]["text"] == "first hint"
    assert "/lab/tree/" in body["url"]

    document = backend.files["teststudent1"][body["notebook"]["file_name"]]
    assert document["metadata"]["opencs"]["exercise"] == "test-exercise"
    assert document["metadata"]["opencs"]["attempt_number"] == 1

    second = student_client.post("/api/v1/practice/exercises/test-exercise/attempts").json()
    assert second["attempt"]["attempt_number"] == 2
    assert second["notebook"]["id"] != body["notebook"]["id"]


def test_evaluate_pass(student_client, exercise, grader):
    created = student_client.post("/api/v1/practice/exercises/test-exercise/attempts").json()
    attempt_id = created["attempt"]["id"]

    response = student_client.post(f"/api/v1/practice/attempts/{attempt_id}/evaluate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is True
    assert body["status"] == "passed"
    assert body["score"] == 1.0
    assert body["tests"][0]["passed"] is True
    assert grader.calls == 1

    detail = student_client.get(f"/api/v1/practice/attempts/{attempt_id}").json()
    assert detail["status"] == "passed"
    assert detail["completed_at"]

    listing = student_client.get("/api/v1/practice/exercises").json()
    assert listing["exercises"][0]["completed"] is True
    progress = student_client.get("/api/v1/practice/progress").json()
    assert progress["completed_exercises"] == 1


def test_evaluate_fail(student_client, exercise, grader):
    grader.passed = False
    created = student_client.post("/api/v1/practice/exercises/test-exercise/attempts").json()
    attempt_id = created["attempt"]["id"]
    body = student_client.post(f"/api/v1/practice/attempts/{attempt_id}/evaluate").json()
    assert body["passed"] is False
    assert body["status"] == "failed"
    assert body["score"] == 0.0

    feedback = student_client.get(f"/api/v1/practice/attempts/{attempt_id}/feedback").json()
    assert feedback["passed"] is False
    assert feedback["tests"][0]["message"] == "assertion failed"


def test_attempt_isolation(student_client, other_student_client, exercise):
    created = student_client.post("/api/v1/practice/exercises/test-exercise/attempts").json()
    attempt_id = created["attempt"]["id"]

    assert other_student_client.get(f"/api/v1/practice/attempts/{attempt_id}").status_code == 404
    assert (
        other_student_client.post(f"/api/v1/practice/attempts/{attempt_id}/evaluate").status_code
        == 404
    )
    assert (
        other_student_client.get(f"/api/v1/practice/attempts/{attempt_id}/feedback").status_code
        == 404
    )


def test_unknown_attempt(student_client):
    assert student_client.get("/api/v1/practice/attempts/not-a-uuid").status_code == 404


def test_no_automated_checks_conflict(student_client, db: Session):
    exercise = Exercise(
        slug="manual-exercise",
        title="Manual Exercise",
        topic="Pandas",
        difficulty="Medium",
        objective="Manual",
        instructions={"markdown": "Do it"},
        starter_notebook={"cells": ["print('hi')"]},
        hints=[],
        evaluation={},
        is_published=True,
        position=2,
    )
    db.add(exercise)
    db.commit()

    created = student_client.post("/api/v1/practice/exercises/manual-exercise/attempts").json()
    response = student_client.post(
        f"/api/v1/practice/attempts/{created['attempt']['id']}/evaluate"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_AUTOMATED_CHECKS"


def test_practice_requires_auth(client):
    assert client.get("/api/v1/practice/exercises").status_code == 401
    assert client.post("/api/v1/practice/exercises/test-exercise/attempts").status_code == 401
