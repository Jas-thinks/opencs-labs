"""Dataset catalogue, preview and snippet tests."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.datasets.manifests import safe_relative_path
from app.datasets.snippets import build_loading_snippet, dataset_absolute_path
from tests.conftest import login


def test_catalogue_requires_auth(client):
    assert client.get("/api/v1/datasets").status_code == 401
    assert client.get("/api/v1/datasets/iris/snippet").status_code == 401


def test_list_and_search(student_client, dataset):
    response = student_client.get("/api/v1/datasets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["datasets"][0]["slug"] == "iris"
    assert body["datasets"][0]["row_count"] == 150
    assert body["datasets"][0]["license_status"] == "verified"

    assert student_client.get("/api/v1/datasets", params={"q": "flower"}).json()["total"] == 1
    assert student_client.get("/api/v1/datasets", params={"q": "nothing"}).json()["total"] == 0
    assert (
        student_client.get("/api/v1/datasets", params={"category": "Classic classification"})
        .json()["total"]
        == 1
    )


def test_categories(student_client, dataset):
    response = student_client.get("/api/v1/datasets/categories")
    assert response.status_code == 200
    assert response.json() == [{"category": "Classic classification", "count": 1}]


def test_detail(student_client, dataset):
    response = student_client.get("/api/v1/datasets/iris")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Iris"
    assert body["read_only"] is True
    assert body["columns"][0]["name"] == "sepal_length"
    assert body["versions"][0]["version"] == 1
    assert body["license"] == "CC BY 4.0"


def test_preview(student_client, dataset):
    response = student_client.get("/api/v1/datasets/iris/preview", params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] == "iris"
    assert body["row_count"] == 150
    assert body["columns"]
    assert body["truncated"] is True


def test_preview_limit_validation(student_client, dataset):
    assert student_client.get("/api/v1/datasets/iris/preview", params={"limit": 0}).status_code == 422
    assert student_client.get("/api/v1/datasets/iris/preview", params={"limit": 500}).status_code == 422


def test_snippet(student_client, dataset):
    response = student_client.get("/api/v1/datasets/iris/snippet")
    assert response.status_code == 200
    body = response.json()
    assert body["auto_execute"] is False
    assert body["cell_type"] == "code"
    assert body["language"] == "python"
    assert f"{settings.dataset_mount_path.rstrip('/')}/iris/v1/iris.csv" in body["code"]
    assert "pd.read_csv" in body["code"]
    assert body["code"].strip().endswith("df.head()")


def test_unpublished_dataset_hidden(student_client, dataset, db):
    dataset.is_published = False
    db.add(dataset)
    db.commit()
    assert student_client.get("/api/v1/datasets/iris").status_code == 404
    assert student_client.get("/api/v1/datasets").json()["total"] == 0


def test_unknown_dataset(student_client):
    assert student_client.get("/api/v1/datasets/nope").status_code == 404


@pytest.mark.parametrize(
    "bad",
    [
        "../etc/passwd",
        "/etc/passwd",
        "iris/../../secret.csv",
        "iris\\v1\\iris.csv",
        "iris//v1/../x.csv",
        "",
    ],
)
def test_path_traversal_rejected(bad):
    with pytest.raises(ValueError):
        safe_relative_path(bad)


def test_absolute_path_built_from_trusted_metadata():
    path = dataset_absolute_path("iris/v1/iris.csv", "/opt/opencs/datasets")
    assert path == "/opt/opencs/datasets/iris/v1/iris.csv"


def test_snippet_rejects_bad_mount():
    with pytest.raises(ValueError):
        build_loading_snippet(
            dataset_id="iris",
            title="Iris",
            version=1,
            relative_path="iris/v1/iris.csv",
            fmt="csv",
            mount_path="/opt/../../etc",
        )


def test_snippet_supports_parquet():
    snippet = build_loading_snippet(
        dataset_id="nyc-taxi-sample",
        title="NYC Taxi",
        version=1,
        relative_path="nyc-taxi-sample/v1/trips.parquet",
        fmt="parquet",
    )
    assert "pd.read_parquet" in snippet["code"]
    assert snippet["auto_execute"] is False


def test_snippet_rejects_unsupported_format():
    with pytest.raises(ValueError):
        build_loading_snippet(
            dataset_id="x",
            title="X",
            version=1,
            relative_path="x/v1/x.bin",
            fmt="binary",
        )


def test_versions(student_client, dataset):
    response = student_client.get("/api/v1/datasets/iris/versions")
    assert response.status_code == 200
    assert response.json()[0]["is_current"] is True
