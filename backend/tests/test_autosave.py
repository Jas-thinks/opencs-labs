"""Autosave, optimistic concurrency, heartbeat and version history."""

from __future__ import annotations

import json


def _create_notebook(client, title="Autosave notebook"):
    response = client.post("/api/v1/notebooks", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def _document(client, notebook_id):
    response = client.get(f"/api/v1/notebooks/{notebook_id}/download")
    assert response.status_code == 200
    return json.loads(response.text)


def _edited(document):
    changed = json.loads(json.dumps(document))
    changed["cells"].append(
        {"cell_type": "markdown", "metadata": {}, "source": f"edit {len(changed['cells'])}"}
    )
    return changed


def test_autosave_is_idempotent_and_versioned(student_client):
    notebook = _create_notebook(student_client)
    document = _document(student_client, notebook["id"])

    first = student_client.put(
        f"/api/v1/notebooks/{notebook['id']}/autosave",
        json={"base_version": 0, "document": _edited(document)},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["saved"] is True
    assert body["version"] == 1
    assert body["version_number"] == 1
    assert len(body["sha256"]) == 64

    same = student_client.put(
        f"/api/v1/notebooks/{notebook['id']}/autosave",
        json={"base_version": 0, "document": _edited(document)},
    )
    assert same.status_code == 200
    assert same.json()["saved"] is False
    assert same.json()["version"] == 1
    assert same.json()["sha256"] == body["sha256"]

    versions = student_client.get(
        f"/api/v1/notebooks/{notebook['id']}/versions?kind=autosave"
    )
    assert versions.status_code == 200
    assert len(versions.json()["versions"]) == 1

    downloaded = student_client.get(
        f"/api/v1/notebooks/{notebook['id']}/versions/1/download"
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/x-ipynb+json")
    assert json.loads(downloaded.text) == _edited(document)


def test_stale_base_version_conflicts(student_client):
    notebook = _create_notebook(student_client, "Conflict notebook")
    document = _document(student_client, notebook["id"])

    assert (
        student_client.put(
            f"/api/v1/notebooks/{notebook['id']}/autosave",
            json={"base_version": 0, "document": _edited(document)},
        ).status_code
        == 200
    )

    conflict = student_client.put(
        f"/api/v1/notebooks/{notebook['id']}/autosave",
        json={"base_version": 0, "document": _edited(_edited(document))},
    )
    assert conflict.status_code == 409
    error = conflict.json()["error"]
    assert error["code"] == "VERSION_CONFLICT"
    assert error["details"]["current_version"] == 1

    retried = student_client.put(
        f"/api/v1/notebooks/{notebook['id']}/autosave",
        json={"base_version": 1, "document": _edited(_edited(document))},
    )
    assert retried.status_code == 200
    assert retried.json()["version"] == 2


def test_invalid_document_is_rejected(student_client):
    notebook = _create_notebook(student_client, "Invalid notebook")
    response = student_client.put(
        f"/api/v1/notebooks/{notebook['id']}/autosave",
        json={"base_version": 0, "document": {"not": "a notebook"}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_NOTEBOOK"


def test_heartbeat_reuses_the_open_session(student_client):
    notebook = _create_notebook(student_client, "Heartbeat notebook")
    first = student_client.post(
        f"/api/v1/notebooks/{notebook['id']}/heartbeat", json={"client": "jupyterlab"}
    )
    assert first.status_code == 200, first.text
    session_id = first.json()["session_id"]
    assert first.json()["version"] == 0

    second = student_client.post(
        f"/api/v1/notebooks/{notebook['id']}/heartbeat", json={"client": "jupyterlab"}
    )
    assert second.status_code == 200
    assert second.json()["session_id"] == session_id


def test_autosave_and_versions_are_owner_only(student_client, other_student_client):
    notebook = _create_notebook(student_client, "Private autosave")
    document = _document(student_client, notebook["id"])

    assert (
        other_student_client.put(
            f"/api/v1/notebooks/{notebook['id']}/autosave",
            json={"base_version": 0, "document": _edited(document)},
        ).status_code
        == 404
    )
    assert (
        other_student_client.get(
            f"/api/v1/notebooks/{notebook['id']}/versions"
        ).status_code
        == 404
    )


def test_watcher_snapshots_out_of_band_changes(session_factory, backend, users, db):
    from app.db.base import utcnow
    from app.notebooks.ipynb import build_notebook
    from app.notebooks.models import Notebook, NotebookSession
    from app.notebooks.service import NotebookService
    from app.notebooks.versions import NotebookVersionService
    from app.notebooks.watcher import run_once

    user = users["student1@test.local"]
    notebook = Notebook(
        user_id=user.id,
        title="Watched",
        file_name="Watched.ipynb",
        kind="personal",
        environment_image="",
    )
    db.add(notebook)
    db.commit()
    db.refresh(notebook)

    backend.files[user.hub_username]["Watched.ipynb"] = build_notebook(title="Watcher")
    now = utcnow()
    db.add(
        NotebookSession(
            notebook_id=notebook.id,
            user_id=user.id,
            client="jupyterlab",
            started_at=now,
            last_seen_at=now,
        )
    )
    db.commit()

    factory = lambda session: NotebookService(session, backend)  # noqa: E731
    assert run_once(session_factory, factory) == 1

    with session_factory() as session:
        versions = NotebookVersionService(session).list_versions(notebook.id)
        assert len(versions) == 1
        assert versions[0]["kind"] == "autosave"

    # The same file produces no duplicate version.
    assert run_once(session_factory, factory) == 0
    with session_factory() as session:
        assert len(NotebookVersionService(session).list_versions(notebook.id)) == 1
