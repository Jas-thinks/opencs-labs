"""Draft -> return grading (ADR-009 amendment): drafts are staff-only."""

from __future__ import annotations

from sqlalchemy import select

from app.core.jobs import JobWorker
from app.notifications.models import Notification


def _setup(instructor_client, student_client, course, max_points=10):
    assignment = instructor_client.post(
        f"/api/v1/courses/{course.id}/assignments",
        json={"title": "Release me", "max_points": max_points, "is_published": True},
    ).json()
    criterion = instructor_client.get(f"/api/v1/assignments/{assignment['id']}/rubric").json()["criteria"][0]
    notebook = student_client.post("/api/v1/notebooks", json={"title": "Mine"}).json()
    submission = student_client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions", json={"notebook_id": notebook["id"]}
    ).json()
    return assignment, criterion, submission


def _grade(client, submission_id, criterion, points, release, feedback="Nice work"):
    response = client.post(
        f"/api/v1/submissions/{submission_id}/grade",
        json={"criteria": [{"criterion_id": criterion["id"], "points": points}],
              "feedback": feedback, "release": release},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_draft_is_invisible_to_student_until_returned(instructor_client, student_client, course):
    assignment, criterion, submission = _setup(instructor_client, student_client, course)
    draft = _grade(instructor_client, submission["id"], criterion, 7, release=False)
    assert draft["state"] == "draft" and draft["released_at"] is None

    # Every student-facing surface still shows plain "submitted".
    assert student_client.get("/api/v1/me/grades").json()["grades"] == []
    own = student_client.get(f"/api/v1/submissions/{submission['id']}").json()
    assert own["status"] == "submitted" and own["final_score"] is None and own["latest_grade"] is None
    assert student_client.get(f"/api/v1/submissions/{submission['id']}/grades").json()["grades"] == []
    dash = student_client.get(f"/api/v1/analytics/me?course_id={course.id}").json()
    assert dash["assignments"][0]["status"] == "submitted"
    mine = student_client.get(f"/api/v1/courses/{course.id}/assignments").json()["assignments"][0]
    assert mine["my_submission"]["status"] == "submitted"

    # Staff see the draft.
    staff = instructor_client.get(f"/api/v1/submissions/{submission['id']}").json()
    assert staff["has_draft"] is True and staff["latest_grade"]["state"] == "draft"
    drafts = instructor_client.get(f"/api/v1/assignments/{assignment['id']}/submissions?status=draft").json()
    assert [s["id"] for s in drafts["submissions"]] == [submission["id"]]

    returned = instructor_client.post(f"/api/v1/submissions/{submission['id']}/return")
    assert returned.status_code == 200 and returned.json()["state"] == "released"
    grades = student_client.get("/api/v1/me/grades").json()["grades"]
    assert grades[0]["final_score"] == 7 and grades[0]["feedback"] == "Nice work"
    assert student_client.get(f"/api/v1/submissions/{submission['id']}").json()["status"] == "graded"

    again = instructor_client.post(f"/api/v1/submissions/{submission['id']}/return")
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_RETURNED"


def test_new_draft_after_return_keeps_old_grade_visible(instructor_client, student_client, course):
    _, criterion, submission = _setup(instructor_client, student_client, course)
    _grade(instructor_client, submission["id"], criterion, 6, release=True)
    _grade(instructor_client, submission["id"], criterion, 9, release=False, feedback="Revised")
    own = student_client.get(f"/api/v1/submissions/{submission['id']}").json()
    assert own["final_score"] == 6 and own["latest_grade"]["revision"] == 1
    staff_rev = instructor_client.get(f"/api/v1/submissions/{submission['id']}/grades").json()["grades"]
    assert [(g["revision"], g["state"]) for g in staff_rev] == [(2, "draft"), (1, "released")]


def test_return_all_releases_every_draft(instructor_client, student_client, other_student_client, course):
    assignment, criterion, first = _setup(instructor_client, student_client, course)
    notebook = other_student_client.post("/api/v1/notebooks", json={"title": "Theirs"}).json()
    second = other_student_client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions", json={"notebook_id": notebook["id"]}
    ).json()
    _grade(instructor_client, first["id"], criterion, 5, release=False)
    _grade(instructor_client, second["id"], criterion, 8, release=False)
    result = instructor_client.post(f"/api/v1/assignments/{assignment['id']}/return")
    assert result.json() == {"returned": 2}
    assert instructor_client.post(f"/api/v1/assignments/{assignment['id']}/return").json() == {"returned": 0}


def test_ta_can_save_drafts_and_return(ta_client, instructor_client, student_client, course):
    _, criterion, submission = _setup(instructor_client, student_client, course)
    _grade(ta_client, submission["id"], criterion, 4, release=False)
    assert ta_client.post(f"/api/v1/submissions/{submission['id']}/return").status_code == 200
    # A member without a staff role gets 403 (non-members get 404).
    assert student_client.post(f"/api/v1/submissions/{submission['id']}/return").status_code == 403


def test_return_creates_in_app_notification(instructor_client, student_client, course, session_factory, users):
    _, criterion, submission = _setup(instructor_client, student_client, course)
    _grade(instructor_client, submission["id"], criterion, 7, release=False)
    JobWorker(session_factory).drain()
    session = session_factory()
    try:
        assert session.scalars(select(Notification)).all() == []  # drafts never notify
    finally:
        session.close()

    instructor_client.post(f"/api/v1/submissions/{submission['id']}/return")
    JobWorker(session_factory).drain()
    inbox = student_client.get("/api/v1/me/notifications").json()["notifications"]
    assert len(inbox) == 1 and inbox[0]["kind"] == "grade_returned"
    assert student_client.get("/api/v1/me/notifications/count").json() == {"unread": 1}
    assert student_client.post("/api/v1/me/notifications/read", json={}).json() == {"unread": 0}


def test_submission_notebook_download_and_etag(instructor_client, student_client, course):
    _, _, submission = _setup(instructor_client, student_client, course)
    url = f"/api/v1/submissions/{submission['id']}/notebook"
    first = instructor_client.get(url)
    assert first.status_code == 200 and "cells" in first.json()
    etag = first.headers["etag"]
    assert "immutable" in first.headers["cache-control"]
    assert instructor_client.get(url, headers={"If-None-Match": etag}).status_code == 304
    download = instructor_client.get(url + "?download=1")
    assert download.headers["content-disposition"].startswith('attachment; filename="student-one-')
    assert download.headers["content-disposition"].endswith('-attempt1.ipynb"')
