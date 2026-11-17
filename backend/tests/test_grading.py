"""Assignments, rubric grading, permissions and immutable snapshots."""

from __future__ import annotations

import copy

from tests.conftest import login

RUBRIC = {
    "title": "Iris rubric",
    "criteria": [
        {"key": "filter", "label": "Correct filter", "max_points": 40, "position": 1},
        {"key": "derive", "label": "Derived column", "max_points": 40, "position": 2},
        {"key": "style", "label": "Readable code", "max_points": 20, "position": 3},
    ],
}


def _assignment(client, course, **overrides):
    payload = {
        "title": "Iris selection",
        "kind": "practice",
        "description": "Select columns",
        "max_points": 100,
        "allow_late": True,
        "is_published": True,
        **overrides,
    }
    response = client.post(f"/api/v1/courses/{course.id}/assignments", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _rubric(client, assignment_id):
    response = client.put(f"/api/v1/assignments/{assignment_id}/rubric", json=RUBRIC)
    assert response.status_code == 200, response.text
    return response.json()


def _notebook(client, title="Submission notebook"):
    response = client.post("/api/v1/notebooks", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def test_instructor_creates_assignment_and_rubric(
    instructor_client, student_client, course
):
    assignment = _assignment(instructor_client, course)
    assert assignment["slug"] == "iris-selection"
    assert assignment["course_id"] == str(course.id)

    rubric = _rubric(instructor_client, assignment["id"])
    assert rubric["total_points"] == 100
    assert len(rubric["criteria"]) == 3

    student_view = student_client.get(
        f"/api/v1/assignments/{assignment['id']}/rubric"
    )
    assert student_view.status_code == 200
    assert all(criterion["description"] == "" for criterion in student_view.json()["criteria"])

    students = student_client.get(f"/api/v1/courses/{course.id}/assignments")
    assert students.status_code == 200
    assert len(students.json()["assignments"]) == 1

    forbidden = student_client.post(
        f"/api/v1/courses/{course.id}/assignments", json={"title": "Nope"}
    )
    assert forbidden.status_code == 403


def test_ta_cannot_create_assignment_but_can_grade(
    ta_client, instructor_client, student_client, course
):
    assignment = _assignment(instructor_client, course)
    _rubric(instructor_client, assignment["id"])

    assert (
        ta_client.post(
            f"/api/v1/courses/{course.id}/assignments", json={"title": "TA assignment"}
        ).status_code
        == 403
    )

    notebook = _notebook(student_client)
    submission = student_client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions",
        json={"notebook_id": notebook["id"]},
    ).json()

    queue = ta_client.get(f"/api/v1/assignments/{assignment['id']}/submissions")
    assert queue.status_code == 200, queue.text
    assert len(queue.json()["submissions"]) == 1

    rubric = ta_client.get(f"/api/v1/assignments/{assignment['id']}/rubric").json()
    grade = ta_client.post(
        f"/api/v1/submissions/{submission['id']}/grade",
        json={
            "criteria": [
                {"criterion_id": criterion["id"], "points": criterion["max_points"]}
                for criterion in rubric["criteria"]
            ],
            "feedback": "Great work",
        },
    )
    assert grade.status_code == 200, grade.text
    assert grade.json()["revision"] == 1
    assert grade.json()["final_score"] == 100


def test_submission_and_grading_flow(
    instructor_client, student_client, other_student_client, course
):
    assignment = _assignment(instructor_client, course)
    rubric = _rubric(instructor_client, assignment["id"])
    notebook = _notebook(student_client)

    submission = student_client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions",
        json={"notebook_id": notebook["id"]},
    )
    assert submission.status_code == 201, submission.text
    body = submission.json()
    assert body["attempt_number"] == 1
    assert body["status"] == "submitted"
    assert body["is_late"] is False
    assert body["notebook_version"]["version_number"] == 1

    # Only course staff may see the review queue.
    assert (
        student_client.get(
            f"/api/v1/assignments/{assignment['id']}/submissions"
        ).status_code
        == 403
    )

    # Another student must not learn that the submission exists.
    assert (
        other_student_client.get(f"/api/v1/submissions/{body['id']}").status_code
        == 404
    )

    criteria = rubric["criteria"]
    grade_payload = {
        "criteria": [
            {"criterion_id": criteria[0]["id"], "points": 38, "comment": "Missing copy"},
            {"criterion_id": criteria[1]["id"], "points": 40, "comment": ""},
            {"criterion_id": criteria[2]["id"], "points": 18, "comment": "Spacing"},
        ],
        "feedback": "Nice work overall",
    }
    graded = instructor_client.post(
        f"/api/v1/submissions/{body['id']}/grade", json=grade_payload
    )
    assert graded.status_code == 200, graded.text
    assert graded.json()["revision"] == 1
    assert graded.json()["total_points"] == 96
    assert graded.json()["final_score"] == 96

    # Regrading creates a new revision, never edits the first.
    regraded = instructor_client.post(
        f"/api/v1/submissions/{body['id']}/grade",
        json={**grade_payload, "final_score": 90},
    )
    assert regraded.status_code == 200
    assert regraded.json()["revision"] == 2
    assert regraded.json()["final_score"] == 90

    revisions = instructor_client.get(f"/api/v1/submissions/{body['id']}/grades")
    assert [item["revision"] for item in revisions.json()["grades"]] == [2, 1]

    # Students see their own published grade immediately.
    mine = student_client.get(f"/api/v1/me/grades?course_id={course.id}")
    assert mine.status_code == 200
    assert len(mine.json()["grades"]) == 1
    assert mine.json()["grades"][0]["final_score"] == 90

    own = student_client.get(f"/api/v1/submissions/{body['id']}")
    assert own.status_code == 200
    assert own.json()["final_score"] == 90
    assert own.json()["latest_grade"]["revision"] == 2
    assert len(own.json()["rubric"]["criteria"]) == 3

    # A student cannot grade.
    assert (
        student_client.post(
            f"/api/v1/submissions/{body['id']}/grade", json=grade_payload
        ).status_code
        == 403
    )


def test_late_policy(instructor_client, student_client, course):
    closed = _assignment(
        instructor_client,
        course,
        title="Closed assignment",
        due_at="2020-01-01T00:00:00Z",
        allow_late=False,
        is_published=True,
    )
    notebook = _notebook(student_client, "Late notebook")
    rejected = student_client.post(
        f"/api/v1/assignments/{closed['id']}/submissions",
        json={"notebook_id": notebook["id"]},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "ASSIGNMENT_CLOSED"

    late_ok = _assignment(
        instructor_client,
        course,
        title="Late allowed",
        due_at="2020-01-01T00:00:00Z",
        allow_late=True,
        is_published=True,
    )
    accepted = student_client.post(
        f"/api/v1/assignments/{late_ok['id']}/submissions",
        json={"notebook_id": notebook["id"]},
    )
    assert accepted.status_code == 201
    assert accepted.json()["is_late"] is True


def test_submission_snapshot_is_immutable(
    instructor_client, student_client, backend, users, course
):
    assignment = _assignment(instructor_client, course)
    rubric = _rubric(instructor_client, assignment["id"])
    notebook = _notebook(student_client, "Immutable notebook")

    first = student_client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions",
        json={"notebook_id": notebook["id"]},
    ).json()
    original = student_client.get(
        f"/api/v1/submissions/{first['id']}/notebook"
    ).json()
    assert original["nbformat"] == 4

    # The student edits the working copy and resubmits.
    hub = users["student1@test.local"].hub_username
    working = copy.deepcopy(backend.files[hub][notebook["file_name"]])
    working["cells"].append(
        {"cell_type": "markdown", "metadata": {}, "source": "changed after submit"}
    )
    backend.files[hub][notebook["file_name"]] = working

    second = student_client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions",
        json={"notebook_id": notebook["id"]},
    ).json()
    assert second["attempt_number"] == 2

    # The first snapshot is byte-for-byte what was submitted.
    still = student_client.get(f"/api/v1/submissions/{first['id']}/notebook").json()
    assert still == original

    # Grading the first submission does not touch its snapshot either.
    criteria = rubric["criteria"]
    instructor_client.post(
        f"/api/v1/submissions/{first['id']}/grade",
        json={
            "criteria": [
                {"criterion_id": criterion["id"], "points": 0} for criterion in criteria
            ]
        },
    )
    assert student_client.get(f"/api/v1/submissions/{first['id']}/notebook").json() == original

    versions = student_client.get(
        f"/api/v1/notebooks/{notebook['id']}/versions?kind=submission"
    )
    assert versions.status_code == 200
    assert len(versions.json()["versions"]) == 2

    # Course staff can inspect the version history because the notebook was
    # submitted to their course.
    staff_versions = instructor_client.get(
        f"/api/v1/notebooks/{notebook['id']}/versions"
    )
    assert staff_versions.status_code == 200
    assert len(staff_versions.json()["versions"]) == 2


def test_grade_rejects_unknown_and_out_of_range_criteria(
    instructor_client, student_client, course
):
    assignment = _assignment(instructor_client, course)
    rubric = _rubric(instructor_client, assignment["id"])
    notebook = _notebook(student_client, "Range notebook")
    submission = student_client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions",
        json={"notebook_id": notebook["id"]},
    ).json()
    criteria = rubric["criteria"]

    too_many = instructor_client.post(
        f"/api/v1/submissions/{submission['id']}/grade",
        json={
            "criteria": [
                {"criterion_id": criteria[0]["id"], "points": 999},
                {"criterion_id": criteria[1]["id"], "points": 40},
                {"criterion_id": criteria[2]["id"], "points": 20},
            ]
        },
    )
    assert too_many.status_code == 409
    assert too_many.json()["error"]["code"] == "POINTS_OUT_OF_RANGE"

    incomplete = instructor_client.post(
        f"/api/v1/submissions/{submission['id']}/grade",
        json={"criteria": [{"criterion_id": criteria[0]["id"], "points": 10}]},
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "INCOMPLETE_GRADING"


def test_course_roster_permissions_and_roles(instructor_client, student_client, course):
    roster = instructor_client.get(f"/api/v1/courses/{course.id}/roster")
    assert roster.status_code == 200
    assert roster.json()["total"] == 2

    assert student_client.get(f"/api/v1/courses/{course.id}/roster").status_code == 403

    # An instructor can change a course role.
    target = [row for row in roster.json()["rows"] if row["email"] == "student2@test.local"][0]
    changed = instructor_client.patch(
        f"/api/v1/courses/{course.id}/enrollments/{target['user_id']}",
        json={"role_in_course": "ta"},
    )
    assert changed.status_code == 200
    assert changed.json()["role_in_course"] == "ta"
