"""End-to-end acceptance tests against the *real* curriculum and datasets.

These are the HLD's "definition of done" checks (HLD section 25):

    Login → Learn a concept → Open a lesson notebook → Browse datasets →
    Click dataset → Insert code cell → Run cell → Analyse/visualise data →
    Open Practice → Complete an exercise → Save notebook → Reopen previous
    notebook.

Notebook execution and grading are faked (the infrastructure seam); the
curriculum, dataset manifests, snippet composition, authorization and storage
metadata are the real thing, loaded from content/ and datasets/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.datasets.manifests import load_manifests
from app.learning.models import LearningPath, Lesson, Module
from app.practice.models import Exercise

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content"
MANIFESTS = REPO / "datasets" / "manifests"


def _load_yaml(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text())


@pytest.fixture()
def real_curriculum(db):
    """Load the actual authored content and dataset manifests into the DB."""
    from app.datasets.models import Dataset, DatasetVersion

    # --- datasets, from the real manifests ---------------------------------
    for manifest in load_manifests(MANIFESTS):
        dataset = Dataset(
            slug=manifest.slug,
            title=manifest.title,
            summary=manifest.summary,
            description=manifest.description,
            category=manifest.category,
            teaching_tags=manifest.teaching_tags,
            position=manifest.position,
            is_published=True,
        )
        db.add(dataset)
        db.flush()
        for version_doc in manifest.versions:
            db.add(
                DatasetVersion(
                    dataset_id=dataset.id,
                    version=version_doc.version,
                    format=version_doc.format,
                    object_key=version_doc.object_key,
                    relative_mount_path=version_doc.relative_mount_path,
                    size_bytes=version_doc.size_bytes,
                    sha256=version_doc.sha256,
                    row_count=version_doc.row_count,
                    columns=[column.model_dump() for column in version_doc.columns],
                    preview=version_doc.preview,
                    license=manifest.license,
                    license_url=manifest.license_url,
                    license_status=manifest.license_status,
                    source_url=manifest.source_url,
                    attribution=manifest.attribution,
                    is_current=True,
                )
            )

    # --- curriculum, from the real YAML ------------------------------------
    paths = json.loads((CONTENT / "paths.json").read_text())
    for path_spec in paths["paths"]:
        path = LearningPath(
            slug=path_spec["slug"],
            title=path_spec["title"],
            description=path_spec.get("description", ""),
            position=path_spec.get("position", 1),
            is_published=True,
            published_version=1,
        )
        db.add(path)
        db.flush()
        for module_position, module_slug in enumerate(path_spec["modules"], start=1):
            module_spec = _load_yaml(CONTENT / "lessons" / f"{module_slug}.yaml")
            module = Module(
                learning_path_id=path.id,
                slug=module_spec["slug"],
                title=module_spec["title"],
                description=module_spec.get("description", ""),
                position=module_position,
                is_published=True,
            )
            db.add(module)
            db.flush()
            for lesson_position, lesson_spec in enumerate(module_spec["lessons"], start=1):
                db.add(
                    Lesson(
                        module_id=module.id,
                        slug=lesson_spec["slug"],
                        title=lesson_spec["title"],
                        objective=lesson_spec.get("objective", ""),
                        summary=lesson_spec.get("summary", ""),
                        position=lesson_position,
                        estimated_minutes=lesson_spec.get("estimated_minutes", 12),
                        content=lesson_spec.get("content", {}),
                        dataset_slugs=lesson_spec.get("datasets", []),
                        exercise_slugs=lesson_spec.get("exercises", []),
                        notebook_activity=lesson_spec.get("notebook_activity"),
                        is_published=True,
                        version=1,
                    )
                )

    # --- exercises, from the real YAML -------------------------------------
    for position, exercise_file in enumerate(sorted((CONTENT / "exercises").glob("*.yaml"))):
        spec = _load_yaml(exercise_file)
        db.add(
            Exercise(
                slug=spec["slug"],
                title=spec["title"],
                topic=spec["topic"],
                difficulty=spec["difficulty"],
                objective=spec.get("objective", ""),
                instructions=spec.get("instructions", {}),
                dataset_slugs=spec.get("datasets", []),
                starter_notebook=spec.get("starter_notebook", {}),
                hints=spec.get("hints", []),
                evaluation=spec.get("evaluation", {}),
                solution_code=spec.get("solution_code"),
                estimated_minutes=spec.get("estimated_minutes", 20),
                position=spec.get("position", position),
                related_lesson_slug=spec.get("related_lesson"),
                is_published=True,
                version=1,
            )
        )

    db.commit()
    return db


def test_full_student_journey(student_client, real_curriculum):
    client = student_client

    # --- Learn a concept ---------------------------------------------------
    paths = client.get("/api/v1/learning/paths")
    assert paths.status_code == 200, paths.text
    catalogue = paths.json()
    assert catalogue["total_lessons"] == 21

    lesson_slug = "pandas-series-and-dataframes"
    lesson = client.get(f"/api/v1/learning/lessons/{lesson_slug}")
    assert lesson.status_code == 200
    body = lesson.json()
    stage_keys = [stage["key"] for stage in body["content"]["stages"]]
    assert stage_keys == [
        "explore",
        "understand",
        "inspect",
        "execute",
        "visualize",
        "debug",
        "practice",
    ]
    assert body["has_notebook_activity"] is True
    assert "iris" in [dataset["slug"] for dataset in body["datasets"]]

    # --- Open a lesson notebook -------------------------------------------
    launch = client.post(f"/api/v1/learning/lessons/{lesson_slug}/launch")
    assert launch.status_code == 200, launch.text
    lesson_notebook = launch.json()["notebook"]
    assert lesson_notebook["kind"] == "lesson"
    assert lesson_notebook["source_ref"] == lesson_slug

    # --- Browse datasets ---------------------------------------------------
    datasets = client.get("/api/v1/datasets")
    assert datasets.status_code == 200
    assert datasets.json()["total"] == 10

    detail = client.get("/api/v1/datasets/iris")
    assert detail.status_code == 200
    assert len(detail.json()["columns"]) == 5

    preview = client.get("/api/v1/datasets/iris/preview?limit=5")
    assert preview.status_code == 200
    assert len(preview.json()["rows"]) == 5

    # --- Click dataset -> insert code cell (never auto-executed) -----------
    snippet = client.get("/api/v1/datasets/iris/snippet")
    assert snippet.status_code == 200
    code = snippet.json()
    assert code["auto_execute"] is False
    assert code["cell_type"] == "code"
    assert "pd.read_csv" in code["code"]
    assert code["path"] == f"{settings.dataset_mount_path.rstrip('/')}/iris/v1/iris.csv"

    # The student creates a notebook where they will paste the cell.
    personal = client.post("/api/v1/notebooks", json={"title": "My iris analysis"})
    assert personal.status_code == 201
    personal_id = personal.json()["id"]

    # --- Open Practice -> complete an exercise -----------------------------
    exercises = client.get("/api/v1/practice/exercises")
    assert exercises.status_code == 200
    assert exercises.json()["total"] == 22

    attempt = client.post("/api/v1/practice/exercises/pandas-select-iris/attempts")
    assert attempt.status_code == 201, attempt.text
    attempt_body = attempt.json()
    assert attempt_body["notebook"]["kind"] == "practice"
    assert len(attempt_body["hints"]) == 3

    feedback = client.post(f"/api/v1/practice/attempts/{attempt_body['attempt']['id']}/evaluate")
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["passed"] is True
    assert feedback.json()["score"] == 1.0
    assert len(feedback.json()["tests"]) == 3

    progress = client.get("/api/v1/practice/progress")
    assert progress.json()["completed_exercises"] == 1

    # --- Save notebook -> reopen previous notebook -------------------------
    listed = client.get("/api/v1/notebooks")
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["notebooks"]}
    assert personal_id in ids
    assert lesson_notebook["id"] in ids

    reopened = client.get(f"/api/v1/notebooks/{personal_id}/open")
    assert reopened.status_code == 200
    assert reopened.json()["notebook"]["id"] == personal_id

    downloaded = client.get(f"/api/v1/notebooks/{personal_id}/download")
    assert downloaded.status_code == 200
    document = json.loads(downloaded.text)
    assert document["nbformat"] == 4


def test_lesson_progress_persists_and_is_sticky(student_client, real_curriculum):
    slug = "pandas-series-and-dataframes"
    client = student_client

    assert client.post(
        f"/api/v1/learning/lessons/{slug}/progress", json={"status": "in_progress"}
    ).json()["status"] == "in_progress"

    completed = client.post(
        f"/api/v1/learning/lessons/{slug}/progress",
        json={"status": "completed", "last_section": "practice"},
    ).json()
    assert completed["status"] == "completed"
    assert completed["completed_at"] is not None

    # Re-reading must not demote a completed lesson.
    again = client.post(
        f"/api/v1/learning/lessons/{slug}/progress", json={"status": "in_progress"}
    ).json()
    assert again["status"] == "completed"


def test_every_lesson_and_exercise_is_reachable(student_client, real_curriculum):
    client = student_client

    modules = client.get("/api/v1/learning/modules").json()["modules"]
    lesson_slugs = [lesson["slug"] for module in modules for lesson in module["lessons"]]
    assert len(lesson_slugs) == 21
    for slug in lesson_slugs:
        assert client.get(f"/api/v1/learning/lessons/{slug}").status_code == 200, slug

    exercises = client.get("/api/v1/practice/exercises?limit=100").json()["exercises"]
    assert len(exercises) == 22
    for exercise in exercises:
        assert client.get(f"/api/v1/practice/exercises/{exercise['slug']}").status_code == 200


def test_every_dataset_snippet_is_valid_and_non_executing(student_client, real_curriculum):
    client = student_client
    datasets = client.get("/api/v1/datasets?limit=100").json()["datasets"]
    assert len(datasets) == 10
    for dataset in datasets:
        response = client.get(f"/api/v1/datasets/{dataset['slug']}/snippet")
        assert response.status_code == 200, dataset["slug"]
        snippet = response.json()
        assert snippet["auto_execute"] is False
        assert snippet["read_only"] is True
        assert snippet["path"].startswith(f"{settings.dataset_mount_path.rstrip('/')}/")
        assert ".." not in snippet["path"]


def test_solution_code_is_never_serialised(student_client, real_curriculum):
    """A reference solution must stay server-side."""
    client = student_client
    exercises = client.get("/api/v1/practice/exercises?limit=100").json()["exercises"]
    for exercise in exercises:
        text = client.get(f"/api/v1/practice/exercises/{exercise['slug']}").text
        assert "solution_code" not in text, exercise["slug"]
        assert '"solution"' not in text, exercise["slug"]
