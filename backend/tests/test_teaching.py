"""Gradebook, grading queue, student home, and the role permission matrix."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from tests.conftest import login


def _assignment(client, course, **overrides):
    payload = {"title": "A1", "max_points": 10, "is_published": True, **overrides}
    return client.post(f"/api/v1/courses/{course.id}/assignments", json=payload).json()


def _submit(student_client, assignment_id):
    notebook = student_client.post("/api/v1/notebooks", json={"title": "N"}).json()
    return student_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions", json={"notebook_id": notebook["id"]}
    ).json()


def _grade(client, assignment_id, submission_id, points, release):
    criterion = client.get(f"/api/v1/assignments/{assignment_id}/rubric").json()["criteria"][0]
    return client.post(
        f"/api/v1/submissions/{submission_id}/grade",
        json={"criteria": [{"criterion_id": criterion["id"], "points": points}], "release": release},
    )


def test_gradebook_states_and_weighted_total(instructor_client, student_client, course):
    past = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).isoformat()
    a1 = _assignment(instructor_client, course, title="A1", weight=1)
    a2 = _assignment(instructor_client, course, title="A2", weight=3, due_at=past)
    s1 = _submit(student_client, a1["id"])
    _grade(instructor_client, a1["id"], s1["id"], 8, release=True)

    book = instructor_client.get(f"/api/v1/courses/{course.id}/gradebook").json()
    assert [a["title"] for a in book["assignments"]] == ["A2", "A1"]  # due date first
    rows = {r["display_name"]: r for r in book["rows"]}
    one = {c["assignment_id"]: c for c in rows["Student One"]["cells"]}
    assert one[a1["id"]]["state"] == "returned" and one[a1["id"]]["score"] == 8
    assert one[a2["id"]]["state"] == "missing"
    # Weighted over returned work only: A1 alone -> 80 %.
    assert rows["Student One"]["weighted_percent"] == 80.0
    assert rows["Student Two"]["weighted_percent"] is None

    assert student_client.get(f"/api/v1/courses/{course.id}/gradebook").status_code == 403


def test_queue_lists_ungraded_and_drafts(instructor_client, ta_client, student_client, other_student_client, course):
    a1 = _assignment(instructor_client, course)
    s1 = _submit(student_client, a1["id"])
    _submit(other_student_client, a1["id"])
    _grade(instructor_client, a1["id"], s1["id"], 5, release=False)
    items = ta_client.get("/api/v1/teaching/queue").json()["items"]
    assert len(items) == 1
    assert (items[0]["ungraded"], items[0]["drafts"], items[0]["course_code"]) == (1, 1, "TEST-101")
    assert student_client.get("/api/v1/teaching/queue").json()["items"] == []


def test_student_home(instructor_client, student_client, course):
    soon = (dt.datetime.now(dt.UTC) + dt.timedelta(days=2)).isoformat()
    due = _assignment(instructor_client, course, title="Due soon", due_at=soon)
    done = _assignment(instructor_client, course, title="Done")
    s = _submit(student_client, done["id"])
    _grade(instructor_client, done["id"], s["id"], 9, release=True)
    instructor_client.post(f"/api/v1/courses/{course.id}/posts", json={"title": "Hello", "body": "Hi"})

    home = student_client.get("/api/v1/me/home").json()
    assert [d["title"] for d in home["due_soon"]] == ["Due soon"]
    assert home["posts"][0]["title"] == "Hello" and home["posts"][0]["is_read"] is False
    assert home["feedback"][0]["assignment_title"] == "Done" and home["feedback"][0]["final_score"] == 9
    assert due["id"] != done["id"]


# --------------------------------------------------------------------------
# Permission matrix (plan section 5). One row per endpoint; expected status for
# each actor. 404 for non-members, 403 for members without the role.
# --------------------------------------------------------------------------
@pytest.fixture()
def actors(client, users, db, course, instructor_client, ta_client, student_client):
    from app.core.security import hash_password
    from app.users.models import User

    db.add(User(email="outsider@test.local", display_name="Outsider", role="student",
                hub_username="outsider", password_hash=hash_password("pw-123456")))
    db.commit()
    return {
        "instructor": instructor_client,
        "ta": ta_client,
        "student": student_client,
        "outsider": login(TestClient(client.app), "outsider@test.local", "pw-123456"),
    }


MATRIX = [
    # (description, method, path template, body, {actor: expected})
    ("create assignment", "post", "/courses/{course}/assignments", {"title": "X"},
     {"instructor": 201, "ta": 403, "student": 403, "outsider": 404}),
    ("archive assignment", "post", "/assignments/{assignment}/archive", None,
     {"instructor": 200, "ta": 403, "student": 403, "outsider": 404}),
    ("list submissions", "get", "/assignments/{assignment}/submissions", None,
     {"instructor": 200, "ta": 200, "student": 403, "outsider": 404}),
    ("return all", "post", "/assignments/{assignment}/return", None,
     {"instructor": 200, "ta": 200, "student": 403, "outsider": 404}),
    ("gradebook", "get", "/courses/{course}/gradebook", None,
     {"instructor": 200, "ta": 200, "student": 403, "outsider": 404}),
    ("members", "get", "/courses/{course}/members", None,
     {"instructor": 200, "ta": 200, "student": 403, "outsider": 404}),
    ("add members", "post", "/courses/{course}/members", {"emails": ["nobody@test.local"]},
     {"instructor": 200, "ta": 403, "student": 403, "outsider": 404}),
    ("rotate join code", "post", "/courses/{course}/join-code", None,
     {"instructor": 200, "ta": 403, "student": 403, "outsider": 404}),
    ("edit course", "patch", "/courses/{course}", {"description": "d"},
     {"instructor": 200, "ta": 403, "student": 403, "outsider": 404}),
    ("post to stream", "post", "/courses/{course}/posts", {"body": "hi"},
     {"instructor": 201, "ta": 201, "student": 403, "outsider": 404}),
    ("read stream", "get", "/courses/{course}/posts", None,
     {"instructor": 200, "ta": 200, "student": 200, "outsider": 404}),
]


@pytest.mark.parametrize("actor", ["instructor", "ta", "student", "outsider"])
@pytest.mark.parametrize("row", MATRIX, ids=[r[0] for r in MATRIX])
def test_permission_matrix(actors, course, instructor_client, row, actor):
    _, method, template, body, expected = row
    assignment = instructor_client.post(
        f"/api/v1/courses/{course.id}/assignments", json={"title": "Matrix", "is_published": True}
    ).json()
    path = "/api/v1" + template.format(course=course.id, assignment=assignment["id"])
    client = actors[actor]
    response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
    assert response.status_code == expected[actor], (actor, path, response.text)
