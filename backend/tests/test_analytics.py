"""Analytics dashboards: aggregates, permissions and export."""

from __future__ import annotations

import datetime as dt
import uuid

from app.db.base import utcnow

RUBRIC = {
    "title": "Analytics rubric",
    "criteria": [
        {"key": "filter", "label": "Correct filter", "max_points": 40, "position": 1},
        {"key": "derive", "label": "Derived column", "max_points": 40, "position": 2},
        {"key": "style", "label": "Readable code", "max_points": 20, "position": 3},
    ],
}


def _graded_submission(instructor_client, student_client, course):
    assignment = instructor_client.post(
        f"/api/v1/courses/{course.id}/assignments",
        json={"title": "Analytics assignment", "max_points": 100, "is_published": True},
    ).json()
    rubric = instructor_client.put(
        f"/api/v1/assignments/{assignment['id']}/rubric", json=RUBRIC
    ).json()
    notebook = student_client.post(
        "/api/v1/notebooks", json={"title": "Analytics notebook"}
    ).json()
    submission = student_client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions",
        json={"notebook_id": notebook["id"]},
    ).json()
    criteria = rubric["criteria"]
    grade = instructor_client.post(
        f"/api/v1/submissions/{submission['id']}/grade",
        json={
            "criteria": [
                {"criterion_id": criteria[0]["id"], "points": 38},
                {"criterion_id": criteria[1]["id"], "points": 40},
                {"criterion_id": criteria[2]["id"], "points": 18},
            ],
            "feedback": "Good",
        },
    )
    assert grade.status_code == 200, grade.text
    return assignment, notebook, submission


def test_student_dashboard_aggregates(
    db, users, instructor_client, student_client, course
):
    _, notebook, _ = _graded_submission(instructor_client, student_client, course)

    now = utcnow()
    from app.notebooks.models import NotebookSession

    db.add(
        NotebookSession(
            notebook_id=uuid.UUID(notebook["id"]),
            user_id=users["student1@test.local"].id,
            client="jupyterlab",
            started_at=now - dt.timedelta(seconds=600),
            last_seen_at=now - dt.timedelta(seconds=60),
        )
    )
    db.commit()

    response = student_client.get(f"/api/v1/analytics/me?course_id={course.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["completion"] == {"assigned": 1, "submitted": 1, "graded": 1}
    assert body["scores"]["average"] == 96
    assert body["scores"]["best"] == 96
    assert len(body["scores"]["trend"]) == 1
    assert body["time_on_task_seconds"] == 540
    assert body["late_count"] == 0
    assert body["ungraded_count"] == 0
    assert body["assignments"][0]["status"] == "graded"
    mastery = {item["key"]: item for item in body["criteria"]}
    assert mastery["filter"]["earned"] == 38
    assert mastery["filter"]["max"] == 40
    assert mastery["filter"]["percent"] == 95.0
    assert mastery["style"]["percent"] == 90.0


def test_teacher_dashboard_and_roster(instructor_client, student_client, course):
    assignment, _, _ = _graded_submission(instructor_client, student_client, course)

    response = instructor_client.get(f"/api/v1/analytics/courses/{course.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["students"] == 2
    assert body["summary"]["average_score"] == 96
    assert body["summary"]["ungraded"] == 0
    assert body["summary"]["completion_rate"] == 0.5

    row = body["assignments"][0]
    assert row["id"] == assignment["id"]
    assert row["submitted"] == 1
    assert row["graded"] == 1
    assert row["average_score"] == 96
    assert row["distribution"]["90-100"] == 1

    criteria = {item["key"]: item for item in body["criteria"]}
    assert criteria["filter"]["average_percent"] == 95.0
    assert criteria["derive"]["average_percent"] == 100.0

    assert body["roster_total"] == 2
    assert len(body["roster"]) == 2
    one = [r for r in body["roster"] if r["email"] == "student1@test.local"][0]
    assert one["completed"] == 1
    assert one["average_score"] == 96


def test_dashboard_permissions(instructor_client, student_client, other_student_client, course):
    _graded_submission(instructor_client, student_client, course)

    assert student_client.get(f"/api/v1/analytics/courses/{course.id}").status_code == 403
    assert student_client.get(f"/api/v1/analytics/courses/{course.id}/export.csv").status_code == 403

    roster = instructor_client.get(f"/api/v1/courses/{course.id}/roster").json()
    student_row = [r for r in roster["rows"] if r["email"] == "student1@test.local"][0]

    # Self drill-down works; another student is forbidden.
    self_view = student_client.get(
        f"/api/v1/analytics/courses/{course.id}/students/{student_row['user_id']}"
    )
    assert self_view.status_code == 200
    assert self_view.json()["student"]["email"] == "student1@test.local"

    assert (
        other_student_client.get(
            f"/api/v1/analytics/courses/{course.id}/students/{student_row['user_id']}"
        ).status_code
        == 403
    )


def test_csv_export(instructor_client, student_client, course):
    _graded_submission(instructor_client, student_client, course)
    response = instructor_client.get(f"/api/v1/analytics/courses/{course.id}/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert "student1@test.local" in response.text
    assert response.text.splitlines()[0].startswith("user_id,")
