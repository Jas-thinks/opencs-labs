"""Assignment authoring: default rubric, scheduling, archive/delete, starter notebooks."""

from __future__ import annotations

import datetime as dt



def _create(client, course, **overrides):
    payload = {"title": "Explore iris", "max_points": 10, "is_published": True, **overrides}
    response = client.post(f"/api/v1/courses/{course.id}/assignments", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _submit(student_client, assignment_id, title="Work"):
    notebook = student_client.post("/api/v1/notebooks", json={"title": title}).json()
    response = student_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions", json={"notebook_id": notebook["id"]}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_new_assignment_has_default_rubric_and_is_gradeable(instructor_client, student_client, course):
    assignment = _create(instructor_client, course)
    rubric = instructor_client.get(f"/api/v1/assignments/{assignment['id']}/rubric").json()
    assert rubric["total_points"] == 10
    assert [c["key"] for c in rubric["criteria"]] == ["overall"]

    submission = _submit(student_client, assignment["id"])
    graded = instructor_client.post(
        f"/api/v1/submissions/{submission['id']}/grade",
        json={"criteria": [{"criterion_id": rubric["criteria"][0]["id"], "points": 8}]},
    )
    assert graded.status_code == 200, graded.text
    assert graded.json()["final_score"] == 8


def test_default_rubric_follows_max_points_until_used(instructor_client, course):
    assignment = _create(instructor_client, course)
    instructor_client.patch(f"/api/v1/assignments/{assignment['id']}", json={"max_points": 25})
    rubric = instructor_client.get(f"/api/v1/assignments/{assignment['id']}/rubric").json()
    assert rubric["total_points"] == 25
    assert rubric["criteria"][0]["max_points"] == 25


def test_scheduled_assignment_is_hidden_until_publish_time(instructor_client, student_client, course):
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(days=2)).isoformat()
    scheduled = _create(instructor_client, course, title="Later", publish_at=future)
    visible = _create(instructor_client, course, title="Now")

    titles = [a["title"] for a in student_client.get(f"/api/v1/courses/{course.id}/assignments").json()["assignments"]]
    assert titles == ["Now"]
    assert student_client.get(f"/api/v1/assignments/{scheduled['id']}").status_code == 404

    staff = instructor_client.get(f"/api/v1/courses/{course.id}/assignments").json()["assignments"]
    by_title = {a["title"]: a for a in staff}
    assert by_title["Later"]["is_visible"] is False
    assert by_title["Now"]["is_visible"] is True
    assert visible["submission_count"] == 0

    # A past publish_at (with an explicit offset) is visible: stored as UTC.
    past = (dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))) - dt.timedelta(minutes=5)).isoformat()
    instructor_client.patch(f"/api/v1/assignments/{scheduled['id']}", json={"publish_at": past})
    assert student_client.get(f"/api/v1/assignments/{scheduled['id']}").status_code == 200


def test_archive_hides_from_students_and_blocks_submissions(instructor_client, student_client, course):
    assignment = _create(instructor_client, course)
    notebook = student_client.post("/api/v1/notebooks", json={"title": "W"}).json()
    archived = instructor_client.post(f"/api/v1/assignments/{assignment['id']}/archive")
    assert archived.status_code == 200 and archived.json()["archived_at"]

    assert student_client.get(f"/api/v1/courses/{course.id}/assignments").json()["assignments"] == []
    blocked = student_client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions", json={"notebook_id": notebook["id"]}
    )
    assert blocked.status_code == 404
    # Hidden from the default staff list, available with include_archived.
    assert instructor_client.get(f"/api/v1/courses/{course.id}/assignments").json()["assignments"] == []
    listed = instructor_client.get(f"/api/v1/courses/{course.id}/assignments?include_archived=true").json()
    assert len(listed["assignments"]) == 1

    restored = instructor_client.post(f"/api/v1/assignments/{assignment['id']}/unarchive")
    assert restored.json()["archived_at"] is None


def test_delete_only_without_submissions_and_no_silent_unpublish(instructor_client, student_client, course):
    empty = _create(instructor_client, course, title="Empty")
    assert instructor_client.delete(f"/api/v1/assignments/{empty['id']}").status_code == 204
    assert instructor_client.get(f"/api/v1/assignments/{empty['id']}").status_code == 404

    used = _create(instructor_client, course, title="Used")
    _submit(student_client, used["id"])
    refused = instructor_client.delete(f"/api/v1/assignments/{used['id']}")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "HAS_SUBMISSIONS"
    unpublish = instructor_client.patch(f"/api/v1/assignments/{used['id']}", json={"is_published": False})
    assert unpublish.status_code == 409


def test_ta_and_student_cannot_manage_assignments(instructor_client, ta_client, student_client, course):
    assignment = _create(instructor_client, course)
    for client in (ta_client, student_client):
        assert client.post(f"/api/v1/courses/{course.id}/assignments", json={"title": "x"}).status_code == 403
        assert client.delete(f"/api/v1/assignments/{assignment['id']}").status_code == 403
        assert client.post(f"/api/v1/assignments/{assignment['id']}/archive").status_code == 403


def test_starter_notebook_is_copied_clean_and_start_is_idempotent(
    instructor_client, student_client, backend, users, course
):
    starter = instructor_client.post("/api/v1/notebooks", json={"title": "Starter"}).json()
    # Put a solved cell with output into the instructor's starter.
    files = backend.files[users["instructor@test.local"].hub_username]
    document = files[starter["file_name"]]
    document["cells"] = [
        {"cell_type": "markdown", "metadata": {}, "source": "# Task"},
        {"cell_type": "code", "metadata": {}, "execution_count": 3, "source": "df.head()",
         "outputs": [{"output_type": "stream", "name": "stdout", "text": "SOLUTION"}]},
    ]
    assignment = _create(instructor_client, course, starter_notebook_id=starter["id"])
    assert assignment["has_starter"] is True

    first = student_client.post(f"/api/v1/assignments/{assignment['id']}/start")
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True
    second = student_client.post(f"/api/v1/assignments/{assignment['id']}/start")
    assert second.json()["created"] is False
    assert second.json()["notebook_id"] == first.json()["notebook_id"]

    copy_doc = next(
        doc for name, doc in backend.files[users["student1@test.local"].hub_username].items()
    )
    code = [c for c in copy_doc["cells"] if c["cell_type"] == "code"][0]
    assert code["outputs"] == [] and code["execution_count"] is None
    assert copy_doc["metadata"]["opencs"]["notebook_id"] == first.json()["notebook_id"]

    # Staff do not start assignments.
    assert instructor_client.post(f"/api/v1/assignments/{assignment['id']}/start").status_code == 403


def test_student_list_includes_my_submission(instructor_client, student_client, course):
    assignment = _create(instructor_client, course)
    before = student_client.get(f"/api/v1/courses/{course.id}/assignments").json()["assignments"][0]
    assert before["my_submission"] is None and before["submission_count"] is None
    _submit(student_client, assignment["id"])
    after = student_client.get(f"/api/v1/courses/{course.id}/assignments").json()["assignments"][0]
    assert after["my_submission"]["status"] == "submitted"
    assert instructor_client.get(f"/api/v1/assignments/{assignment['id']}").json()["submission_count"] == 1
