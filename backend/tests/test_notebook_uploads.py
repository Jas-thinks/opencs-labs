""".ipynb uploads: teacher post attachments and student turn-in by upload."""

from __future__ import annotations

import copy

NOTEBOOK = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"},
                 "opencs": {"notebook_id": "someone-else"}},
    "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": "# Week 1 notes"},
        {"cell_type": "code", "metadata": {}, "execution_count": 1, "source": "1 + 1",
         "outputs": [{"output_type": "execute_result", "execution_count": 1, "metadata": {},
                      "data": {"text/plain": "2"}}]},
    ],
}


def _upload(client, course, **overrides):
    payload = {"file_name": "week1.ipynb", "notebook": NOTEBOOK, **overrides}
    return client.post(f"/api/v1/courses/{course.id}/notebook-uploads", json=payload)


def test_only_valid_ipynb_is_accepted(instructor_client, course):
    assert _upload(instructor_client, course, file_name="notes.pdf").json()["error"]["code"] == "NOT_A_NOTEBOOK"
    bad = _upload(instructor_client, course, notebook={"cells": "nope"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_NOTEBOOK"
    old = copy.deepcopy(NOTEBOOK); old["nbformat"] = 3
    assert _upload(instructor_client, course, notebook=old).status_code == 422
    ok = _upload(instructor_client, course, file_name="../../etc/Week 1!.IPYNB")
    assert ok.status_code == 201, ok.text
    assert ok.json()["file_name"] == "Week 1.ipynb" and ok.json()["cells"] == 2


def test_size_limit(instructor_client, course, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "notebook_upload_max_bytes", 200)
    big = _upload(instructor_client, course)
    assert big.status_code == 413 and big.json()["error"]["code"] == "NOTEBOOK_TOO_LARGE"


def test_students_and_tas(student_client, ta_client, course):
    assert _upload(student_client, course).status_code == 403
    assert _upload(ta_client, course).status_code == 201  # D1: TAs post too


def test_attach_download_and_copy(instructor_client, student_client, backend, users, course):
    up = _upload(instructor_client, course).json()
    post = instructor_client.post(
        f"/api/v1/courses/{course.id}/posts",
        json={"kind": "material", "title": "Week 1", "attachments": [
            {"kind": "notebook", "target": up["sha256"], "label": up["file_name"]}]},
    )
    assert post.status_code == 201, post.text
    att = post.json()["attachments"][0]
    assert att["kind"] == "notebook" and att["internal"] is False and att["size_bytes"] > 0
    assert instructor_client.post(
        f"/api/v1/courses/{course.id}/posts",
        json={"body": "x", "attachments": [{"kind": "notebook", "target": "f" * 64}]},
    ).status_code == 404

    base = f"/api/v1/posts/{post.json()['id']}/attachments/{att['id']}"
    download = student_client.get(f"{base}/notebook")
    assert download.status_code == 200
    assert download.headers["content-disposition"] == 'attachment; filename="week1.ipynb"'
    assert download.headers["content-type"].startswith("application/x-ipynb+json")
    assert download.json()["cells"][0]["source"] == "# Week 1 notes"

    first = student_client.post(f"{base}/copy")
    assert first.status_code == 200 and first.json()["created"] is True
    again = student_client.post(f"{base}/copy").json()
    assert again["created"] is False and again["notebook_id"] == first.json()["notebook_id"]
    files = backend.files[users["student1@test.local"].hub_username]
    copied = next(iter(files.values()))
    assert copied["metadata"]["opencs"]["notebook_id"] == first.json()["notebook_id"]
    assert copied["cells"][1]["outputs"]  # teacher notes keep their outputs


def test_student_turns_in_by_upload(instructor_client, student_client, course):
    assignment = instructor_client.post(
        f"/api/v1/courses/{course.id}/assignments",
        json={"title": "Upload me", "max_points": 10, "is_published": True},
    ).json()
    url = f"/api/v1/assignments/{assignment['id']}/submissions/upload"
    sub = student_client.post(url, json={"file_name": "my work.ipynb", "notebook": NOTEBOOK})
    assert sub.status_code == 201, sub.text
    assert sub.json()["attempt_number"] == 1 and sub.json()["status"] == "submitted"
    assert student_client.post(url, json={"file_name": "x.py", "notebook": NOTEBOOK}).status_code == 422
    assert instructor_client.post(url, json={"file_name": "a.ipynb", "notebook": NOTEBOOK}).status_code == 403

    # The teacher grades it like any other submission.
    listed = instructor_client.get(f"/api/v1/assignments/{assignment['id']}/submissions").json()
    assert [s["id"] for s in listed["submissions"]] == [sub.json()["id"]]
    doc = instructor_client.get(f"/api/v1/submissions/{sub.json()['id']}/notebook").json()
    assert doc["cells"][0]["source"] == "# Week 1 notes"

    # Storage-only: not in the workspace list, cannot be opened or re-submitted.
    notebooks = student_client.get("/api/v1/notebooks").json()["notebooks"]
    assert all(n["kind"] != "upload" for n in notebooks)
    resubmit = student_client.post(
        f"/api/v1/assignments/{assignment['id']}/submissions", json={"notebook_id": sub.json()["notebook_id"]}
    )
    assert resubmit.status_code == 404
    second = student_client.post(url, json={"file_name": "v2.ipynb", "notebook": NOTEBOOK})
    assert second.json()["attempt_number"] == 2


def test_upload_turn_in_respects_late_policy(instructor_client, student_client, course):
    import datetime as dt

    past = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()
    closed = instructor_client.post(
        f"/api/v1/courses/{course.id}/assignments",
        json={"title": "Closed", "is_published": True, "due_at": past, "allow_late": False},
    ).json()
    refused = student_client.post(
        f"/api/v1/assignments/{closed['id']}/submissions/upload",
        json={"file_name": "a.ipynb", "notebook": NOTEBOOK},
    )
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ASSIGNMENT_CLOSED"
