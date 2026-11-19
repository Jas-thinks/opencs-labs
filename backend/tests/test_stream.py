"""Course stream: announcements/materials, scheduling, permissions, read receipts."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.core.jobs import JobWorker
from tests.conftest import login


def _post(client, course, **overrides):
    payload = {"kind": "announcement", "body": "Quiz on Friday", **overrides}
    return client.post(f"/api/v1/courses/{course.id}/posts", json=payload)


def _feed(client, course):
    response = client.get(f"/api/v1/courses/{course.id}/posts")
    assert response.status_code == 200, response.text
    return response.json()["posts"]


def test_instructor_and_ta_post_students_read(instructor_client, ta_client, student_client, course):
    created = _post(instructor_client, course, title="Welcome", is_pinned=True)
    assert created.status_code == 201, created.text
    # D1: TAs can post announcements.
    assert _post(ta_client, course, body="Office hours moved").status_code == 201
    # Students cannot.
    assert _post(student_client, course).status_code == 403

    feed = _feed(student_client, course)
    assert [p["title"] for p in feed][0] == "Welcome"  # pinned first
    assert feed[0]["can_edit"] is False and feed[0]["read_count"] is None
    staff_feed = _feed(instructor_client, course)
    assert staff_feed[0]["can_edit"] is True and staff_feed[0]["audience"] == 2


def test_non_member_cannot_see_stream(instructor_client, client, db, course):
    from app.core.security import hash_password
    from app.users.models import User

    db.add(User(email="outsider@test.local", display_name="Out", role="student",
                hub_username="outsider", password_hash=hash_password("pw-123456")))
    db.commit()
    created = _post(instructor_client, course).json()
    outsider = login(TestClient(client.app), "outsider@test.local", "pw-123456")
    assert outsider.get(f"/api/v1/courses/{course.id}/posts").status_code == 404
    assert outsider.get(f"/api/v1/posts/{created['id']}").status_code == 404


def test_scheduled_and_draft_posts_are_staff_only(instructor_client, student_client, course):
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=3)).isoformat()
    scheduled = _post(instructor_client, course, body="Later", publish_at=future).json()
    draft = _post(instructor_client, course, body="Draft", status="draft").json()
    assert scheduled["published_at"] is None
    assert [p["body"] for p in _feed(student_client, course)] == []
    assert {p["body"] for p in _feed(instructor_client, course)} == {"Later", "Draft"}
    assert student_client.get(f"/api/v1/posts/{draft['id']}").status_code == 404

    published = instructor_client.patch(f"/api/v1/posts/{draft['id']}", json={"status": "published"})
    assert published.json()["published_at"] is not None
    assert [p["body"] for p in _feed(student_client, course)] == ["Draft"]


def test_attachments_are_validated_and_resolved(instructor_client, course, dataset, lesson, exercise):
    ok = _post(
        instructor_client, course, kind="material", title="Week 1 resources", body="",
        attachments=[
            {"kind": "link", "target": "https://pandas.pydata.org/docs/"},
            {"kind": "dataset", "target": dataset.slug},
            {"kind": "lesson", "target": lesson.slug},
            {"kind": "exercise", "target": exercise.slug},
        ],
    )
    assert ok.status_code == 201, ok.text
    kinds = [(a["kind"], a["internal"], a["url"]) for a in ok.json()["attachments"]]
    assert kinds[0] == ("link", False, "https://pandas.pydata.org/docs/")
    assert kinds[1] == ("dataset", True, f"/datasets/{dataset.slug}")
    assert ok.json()["attachments"][0]["label"] == "pandas.pydata.org"

    for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://x.test/a", "//evil.test"):
        rejected = _post(instructor_client, course, attachments=[{"kind": "link", "target": bad}])
        assert rejected.status_code == 422, bad
    assert _post(instructor_client, course, attachments=[{"kind": "file", "target": "x.pdf"}]).status_code == 422
    assert _post(instructor_client, course, attachments=[{"kind": "dataset", "target": "nope"}]).status_code == 404
    # Materials need a title; posts need content.
    assert _post(instructor_client, course, kind="material", title="").status_code == 422
    assert _post(instructor_client, course, body="", title="").status_code == 422


def test_edit_and_delete_permissions(instructor_client, ta_client, course, client, users, db):
    from app.courses.models import Enrollment

    by_ta = _post(ta_client, course, body="TA note").json()
    by_instructor = _post(instructor_client, course, body="Instructor note").json()
    # Instructor moderates anything; a TA edits only their own.
    assert instructor_client.patch(f"/api/v1/posts/{by_ta['id']}", json={"body": "fixed"}).status_code == 200
    assert ta_client.patch(f"/api/v1/posts/{by_instructor['id']}", json={"body": "x"}).status_code == 403
    edited = ta_client.patch(f"/api/v1/posts/{by_ta['id']}", json={"body": "again"}).json()
    assert edited["edited_at"] is not None

    assert ta_client.delete(f"/api/v1/posts/{by_instructor['id']}").status_code == 403
    assert instructor_client.delete(f"/api/v1/posts/{by_ta['id']}").status_code == 204
    assert instructor_client.get(f"/api/v1/posts/{by_ta['id']}").status_code == 404


def test_read_receipts_and_notification_fan_out(
    instructor_client, student_client, other_student_client, course, session_factory
):
    post = _post(instructor_client, course, title="Exam room").json()
    JobWorker(session_factory).drain()
    # Both students notified; the author is not.
    assert student_client.get("/api/v1/me/notifications/count").json() == {"unread": 1}
    assert other_student_client.get("/api/v1/me/notifications/count").json() == {"unread": 1}
    assert instructor_client.get("/api/v1/me/notifications/count").json() == {"unread": 0}
    note = student_client.get("/api/v1/me/notifications").json()["notifications"][0]
    assert note["kind"] == "new_announcement" and note["link"].endswith(f"#post-{post['id']}")

    assert student_client.post(f"/api/v1/posts/{post['id']}/read").status_code == 204
    assert student_client.post(f"/api/v1/posts/{post['id']}/read").status_code == 204  # idempotent
    assert _feed(student_client, course)[0]["is_read"] is True
    staff_view = _feed(instructor_client, course)[0]
    assert (staff_view["read_count"], staff_view["audience"]) == (1, 2)
    readers = instructor_client.get(f"/api/v1/posts/{post['id']}/readers").json()
    assert [r["display_name"] for r in readers["read"]] == ["Student One"]
    assert [r["display_name"] for r in readers["unread"]] == ["Student Two"]
    assert student_client.get(f"/api/v1/posts/{post['id']}/readers").status_code == 403


def test_scheduled_post_notifies_once_due(instructor_client, student_client, course, session_factory, db):
    from app.core.jobs import enqueue
    from app.stream.models import CoursePost

    future = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat()
    post = _post(instructor_client, course, body="Scheduled", publish_at=future).json()
    session = session_factory()
    try:
        enqueue(session, "publish_due_posts", {})
        session.commit()
    finally:
        session.close()
    JobWorker(session_factory).drain()
    assert student_client.get("/api/v1/me/notifications/count").json() == {"unread": 0}

    # Time passes: move publish_at into the past and run the tick again.
    session = session_factory()
    try:
        row = session.get(CoursePost, __import__("uuid").UUID(post["id"]))
        row.publish_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
        enqueue(session, "publish_due_posts", {})
        session.commit()
    finally:
        session.close()
    JobWorker(session_factory).drain()
    assert student_client.get("/api/v1/me/notifications/count").json() == {"unread": 1}


def test_archived_course_is_read_only(instructor_client, course):
    instructor_client.patch(f"/api/v1/courses/{course.id}", json={"status": "archived"})
    refused = _post(instructor_client, course)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "COURSE_ARCHIVED"
