"""Notebook workspace tests: creation, listing, ownership, rename, delete."""

from __future__ import annotations

from tests.conftest import login


def test_notebooks_require_auth(client):
    assert client.get("/api/v1/notebooks").status_code == 401
    assert client.post("/api/v1/notebooks", json={"title": "x"}).status_code == 401


def test_server_state(student_client):
    response = student_client.get("/api/v1/notebooks/server")
    assert response.status_code == 200
    assert response.json()["ready"] is True

    response = student_client.post("/api/v1/notebooks/server/start")
    assert response.status_code == 200
    assert response.json()["status"] == "running"

    response = student_client.post("/api/v1/notebooks/server/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"


def test_create_list_open(student_client, backend, users):
    response = student_client.post("/api/v1/notebooks", json={"title": "My Analysis"})
    assert response.status_code == 201, response.text
    notebook = response.json()
    assert notebook["title"] == "My Analysis"
    assert notebook["file_name"] == "My Analysis.ipynb"
    assert notebook["kind"] == "personal"
    assert notebook["environment_image"]

    listing = student_client.get("/api/v1/notebooks")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    opened = student_client.get(f"/api/v1/notebooks/{notebook['id']}/open")
    assert opened.status_code == 200
    assert opened.json()["url"].endswith("/lab/tree/My Analysis.ipynb")
    assert backend.file_count(users["student1@test.local"]) == 1


def test_created_notebook_is_a_valid_ipynb(student_client, backend, users):
    student_client.post("/api/v1/notebooks", json={"title": "Structure"})
    files = backend.files["teststudent1"]
    document = files["Structure.ipynb"]
    assert document["nbformat"] == 4
    assert document["cells"] == []
    assert document["metadata"]["kernelspec"]["name"] == "python3"
    assert document["metadata"]["opencs"]["title"] == "Structure"


def test_rename(student_client):
    created = student_client.post("/api/v1/notebooks", json={"title": "First"}).json()
    response = student_client.patch(
        f"/api/v1/notebooks/{created['id']}", json={"title": "Second Name"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Second Name"
    assert body["file_name"] == "Second Name.ipynb"


def test_duplicate_titles_get_unique_file_names(student_client):
    first = student_client.post("/api/v1/notebooks", json={"title": "Same"}).json()
    second = student_client.post("/api/v1/notebooks", json={"title": "Same"}).json()
    assert first["file_name"] == "Same.ipynb"
    assert second["file_name"] == "Same 2.ipynb"


def test_download(student_client):
    created = student_client.post("/api/v1/notebooks", json={"title": "Download me"}).json()
    response = student_client.get(f"/api/v1/notebooks/{created['id']}/download")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ipynb+json")
    assert "attachment" in response.headers["content-disposition"]
    assert '"nbformat": 4' in response.text


def test_delete(student_client, backend, users):
    created = student_client.post("/api/v1/notebooks", json={"title": "Delete me"}).json()
    response = student_client.delete(f"/api/v1/notebooks/{created['id']}")
    assert response.status_code == 204
    assert student_client.get("/api/v1/notebooks").json()["total"] == 0
    assert backend.file_count(users["student1@test.local"]) == 0


def test_cannot_access_another_users_notebook(
    student_client, other_student_client
):
    created = student_client.post("/api/v1/notebooks", json={"title": "Private"}).json()
    notebook_id = created["id"]

    assert other_student_client.get(f"/api/v1/notebooks/{notebook_id}/open").status_code == 404
    assert (
        other_student_client.patch(
            f"/api/v1/notebooks/{notebook_id}", json={"title": "stolen"}
        ).status_code
        == 404
    )
    assert other_student_client.delete(f"/api/v1/notebooks/{notebook_id}").status_code == 404
    assert other_student_client.get(f"/api/v1/notebooks/{notebook_id}/download").status_code == 404
    assert other_student_client.get("/api/v1/notebooks").json()["total"] == 0


def test_unknown_notebook(student_client):
    assert student_client.get("/api/v1/notebooks/00000000-0000-0000-0000-000000000000/open").status_code == 404
    assert student_client.get("/api/v1/notebooks/not-a-uuid/open").status_code == 404


def test_title_path_characters_are_sanitised(student_client):
    created = student_client.post(
        "/api/v1/notebooks", json={"title": "../../etc/passwd"}
    ).json()
    assert "/" not in created["file_name"] and ".." not in created["file_name"]
    assert created["file_name"].endswith(".ipynb")


def test_notebooks_are_listed_newest_first(student_client):
    student_client.post("/api/v1/notebooks", json={"title": "One"})
    student_client.post("/api/v1/notebooks", json={"title": "Two"})
    titles = [item["title"] for item in student_client.get("/api/v1/notebooks").json()["notebooks"]]
    assert titles[0] == "Two"


def test_auth_required_for_notebook_operations(client):
    assert client.get("/api/v1/notebooks/server").status_code == 401
    assert client.delete("/api/v1/notebooks/anything").status_code == 401
