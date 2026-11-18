#!/usr/bin/env python3
"""Seed the OpenCS database: users, course, datasets, curriculum, exercises.

Idempotent: running it again updates content in place by slug and keeps
student progress, notebooks and attempts intact.

Requires a migrated database (``alembic upgrade head``).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.courses.models import Course, Enrollment  # noqa: E402
from app.datasets.manifests import load_manifests, verify_file  # noqa: E402
from app.datasets.models import Dataset, DatasetVersion  # noqa: E402
from app.db.base import utcnow  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.learning.models import LearningPath, Lesson, Module  # noqa: E402
from app.grading.models import Assignment, Rubric, RubricCriterion  # noqa: E402
from app.practice.models import Exercise  # noqa: E402
from app.users.models import User  # noqa: E402

CONTENT = REPO / "content"
DEFAULT_PASSWORD = os.environ.get("OPENCE_SEED_PASSWORD", "opencs-demo")

SEED_USERS = [
    {
        "email": "admin@opencs.local",
        "display_name": "Platform Admin",
        "role": "admin",
        "hub_username": "admin",
    },
    {
        "email": "instructor@opencs.local",
        "display_name": "Dr. Ada Instructor",
        "role": "instructor",
        "hub_username": "instructor",
    },
    {
        "email": "ta@opencs.local",
        "display_name": "Tariq Teaching Assistant",
        "role": "student",
        "hub_username": "ta1",
    },
    {
        "email": "student@opencs.local",
        "display_name": "Maya Student",
        "role": "student",
        "hub_username": "student1",
    },
    {
        "email": "student2@opencs.local",
        "display_name": "Leo Student",
        "role": "student",
        "hub_username": "student2",
    },
]


def log(message: str) -> None:
    print(message)


def upsert_users(db: Session) -> dict[str, User]:
    if settings.is_production:
        raise SystemExit("refusing to seed development accounts in production")
    users: dict[str, User] = {}
    for spec in SEED_USERS:
        user = db.scalar(select(User).where(User.email == spec["email"]))
        if user is None:
            user = User(
                email=spec["email"],
                display_name=spec["display_name"],
                role=spec["role"],
                hub_username=spec["hub_username"],
                password_hash=hash_password(DEFAULT_PASSWORD),
                preferences={"theme": "dark"},
            )
            db.add(user)
            db.flush()
            log(f"  + user {spec['email']} ({spec['role']}, hub={spec['hub_username']})")
        else:
            user.display_name = spec["display_name"]
            user.role = spec["role"]
            user.hub_username = spec["hub_username"]
            if not user.password_hash:
                user.password_hash = hash_password(DEFAULT_PASSWORD)
        users[spec["email"]] = user
    db.flush()
    return users


def upsert_course(db: Session, users: dict[str, User]) -> Course:
    course = db.scalar(select(Course).where(Course.code == "CS-2410"))
    if course is None:
        course = Course(
            name="CS-2410 Data Analysis with Python",
            code="CS-2410",
            term="2026-S2",
            status="active",
            description="Undergraduate data analysis and introductory data science.",
        )
        db.add(course)
        db.flush()
        log("  + course CS-2410")
    for email, role in [
        ("admin@opencs.local", "instructor"),
        ("instructor@opencs.local", "instructor"),
        ("ta@opencs.local", "ta"),
        ("student@opencs.local", "student"),
        ("student2@opencs.local", "student"),
    ]:
        user = users[email]
        enrollment = db.scalar(
            select(Enrollment).where(
                Enrollment.course_id == course.id, Enrollment.user_id == user.id
            )
        )
        if enrollment is None:
            db.add(Enrollment(course_id=course.id, user_id=user.id, role_in_course=role))
        else:
            enrollment.role_in_course = role
    db.flush()
    return course


def upsert_datasets(db: Session) -> int:
    manifests = load_manifests(REPO / "datasets" / "manifests")
    count = 0
    for manifest in manifests:
        # Honour OPENCE_DATASET_SERVING_DIR: deployments keep the tree outside
        # the code checkout (one copy shared by every release).
        problems = verify_file(manifest, settings.serving_dir)
        if problems and all("missing file" in p for p in problems):
            # Not built on this deployment (e.g. its source is unreachable from
            # the network). Leave it out of the catalogue rather than list a
            # dataset whose loading cell would fail; integrity failures below
            # (size/checksum) still abort.
            log(f"  - dataset {manifest.slug} skipped: {'; '.join(problems)}")
            continue
        if problems:
            raise SystemExit(
                f"dataset {manifest.slug} failed verification: {'; '.join(problems)}"
            )
        dataset = db.scalar(select(Dataset).where(Dataset.slug == manifest.slug))
        if dataset is None:
            dataset = Dataset(slug=manifest.slug, title=manifest.title, category=manifest.category)
            db.add(dataset)
            db.flush()
        dataset.title = manifest.title
        dataset.summary = manifest.summary
        dataset.description = manifest.description
        dataset.category = manifest.category
        dataset.teaching_tags = manifest.teaching_tags
        dataset.position = manifest.position
        dataset.is_published = True

        for version_doc in manifest.versions:
            version = db.scalar(
                select(DatasetVersion).where(
                    DatasetVersion.dataset_id == dataset.id,
                    DatasetVersion.version == version_doc.version,
                )
            )
            if version is None:
                version = DatasetVersion(
                    dataset_id=dataset.id, version=version_doc.version, format=version_doc.format
                )
                db.add(version)
            version.format = version_doc.format
            version.object_key = version_doc.object_key
            version.relative_mount_path = version_doc.relative_mount_path
            version.size_bytes = version_doc.size_bytes
            version.sha256 = version_doc.sha256
            version.row_count = version_doc.row_count
            version.columns = [column.model_dump() for column in version_doc.columns]
            version.preview = version_doc.preview
            version.license = manifest.license
            version.license_url = manifest.license_url
            version.license_status = manifest.license_status
            version.source_url = manifest.source_url
            version.attribution = manifest.attribution
            version.is_current = True
            version.published_at = utcnow()
        count += 1
    db.flush()
    log(f"  + {count} datasets")
    return count


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def load_doc(path: Path) -> dict:
    """Load a YAML or JSON content document."""
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        import yaml

        doc = yaml.safe_load(text)
    else:
        doc = json.loads(text)
    if not isinstance(doc, dict):
        raise SystemExit(f"{path}: content document must be a mapping")
    return doc


def upsert_curriculum(db: Session) -> int:
    index = load_json(CONTENT / "paths.json")
    lessons_total = 0
    for path_position, path_spec in enumerate(index["paths"], start=1):
        path = db.scalar(select(LearningPath).where(LearningPath.slug == path_spec["slug"]))
        if path is None:
            path = LearningPath(slug=path_spec["slug"], title=path_spec["title"])
            db.add(path)
            db.flush()
        path.title = path_spec["title"]
        path.description = path_spec.get("description", "")
        path.position = path_spec.get("position", path_position)
        path.is_published = True
        path.published_version = 1

        for module_position, module_slug in enumerate(path_spec["modules"], start=1):
            module_path = CONTENT / "lessons" / f"{module_slug}.yaml"
            if not module_path.is_file():
                module_path = CONTENT / "lessons" / f"{module_slug}.json"
            if not module_path.is_file():
                raise SystemExit(f"missing module content for '{module_slug}'")
            module_spec = load_doc(module_path)
            module = db.scalar(
                select(Module).where(
                    Module.learning_path_id == path.id, Module.slug == module_spec["slug"]
                )
            )
            if module is None:
                module = Module(learning_path_id=path.id, slug=module_spec["slug"], title=module_spec["title"])
                db.add(module)
                db.flush()
            module.title = module_spec["title"]
            module.description = module_spec.get("description", "")
            module.position = module_position
            module.is_published = True

            for lesson_position, lesson_spec in enumerate(module_spec["lessons"], start=1):
                lesson = db.scalar(
                    select(Lesson).where(
                        Lesson.module_id == module.id, Lesson.slug == lesson_spec["slug"]
                    )
                )
                if lesson is None:
                    lesson = Lesson(module_id=module.id, slug=lesson_spec["slug"], title=lesson_spec["title"])
                    db.add(lesson)
                    db.flush()
                lesson.title = lesson_spec["title"]
                lesson.objective = lesson_spec.get("objective", "")
                lesson.summary = lesson_spec.get("summary", "")
                lesson.position = lesson_position
                lesson.estimated_minutes = lesson_spec.get("estimated_minutes", 12)
                lesson.content = lesson_spec.get("content", {})
                lesson.dataset_slugs = lesson_spec.get("datasets", [])
                lesson.exercise_slugs = lesson_spec.get("exercises", [])
                lesson.notebook_activity = lesson_spec.get("notebook_activity")
                lesson.is_published = True
                lesson.version = 1
                lessons_total += 1
            log(f"  + module {module.slug} ({len(module_spec['lessons'])} lessons)")
    db.flush()
    log(f"  + {lessons_total} lessons")
    return lessons_total


def upsert_exercises(db: Session) -> int:
    directory = CONTENT / "exercises"
    count = 0
    paths = sorted(list(directory.glob("*.yaml")) + list(directory.glob("*.yml")) + list(directory.glob("*.json")))
    for path in paths:
        spec = load_doc(path)
        exercise = db.scalar(select(Exercise).where(Exercise.slug == spec["slug"]))
        if exercise is None:
            exercise = Exercise(slug=spec["slug"], title=spec["title"])
            db.add(exercise)
        exercise.title = spec["title"]
        exercise.topic = spec["topic"]
        exercise.difficulty = spec["difficulty"]
        exercise.objective = spec.get("objective", "")
        exercise.instructions = spec.get("instructions", {})
        exercise.dataset_slugs = spec.get("datasets", [])
        exercise.starter_notebook = spec.get("starter_notebook", {})
        exercise.hints = spec.get("hints", [])
        exercise.evaluation = spec.get("evaluation", {})
        exercise.solution_code = spec.get("solution_code")
        exercise.estimated_minutes = spec.get("estimated_minutes", 20)
        exercise.position = spec.get("position", count)
        exercise.related_lesson_slug = spec.get("related_lesson")
        exercise.is_published = True
        exercise.version = 1
        count += 1
    db.flush()
    log(f"  + {count} exercises")
    return count


def upsert_course_work(db: Session, users: dict[str, User], course: Course) -> Assignment:
    """Seed one published assignment and its rubric."""
    instructor = users["instructor@opencs.local"]
    assignment = db.scalar(
        select(Assignment).where(
            Assignment.course_id == course.id, Assignment.slug == "iris-selection"
        )
    )
    if assignment is None:
        assignment = Assignment(
            course_id=course.id,
            slug="iris-selection",
            title="Iris selection",
            created_by=instructor.id,
        )
        db.add(assignment)
        db.flush()
        log("  + assignment iris-selection")
    exercise = db.scalar(select(Exercise).where(Exercise.slug == "pandas-select-iris"))
    assignment.exercise_id = exercise.id if exercise else None
    assignment.kind = "practice"
    assignment.title = "Iris selection"
    assignment.description = "Select and derive columns from the Iris dataset."
    assignment.due_at = dt.datetime(2026, 12, 1, 23, 59, tzinfo=dt.UTC)
    assignment.max_points = 100
    assignment.weight = 1
    assignment.allow_late = True
    assignment.late_penalty_pct = 10
    assignment.is_published = True

    rubric = db.scalar(select(Rubric).where(Rubric.assignment_id == assignment.id))
    if rubric is None:
        rubric = Rubric(
            assignment_id=assignment.id,
            title="Iris rubric",
            created_by=instructor.id,
        )
        db.add(rubric)
        db.flush()
        log("  + rubric for iris-selection")
    rubric.title = "Iris rubric"
    specs = [
        ("filter", "Correct filter", 40, 1),
        ("derive", "Derived column", 40, 2),
        ("style", "Readable code", 20, 3),
    ]
    for key, label, max_points, position in specs:
        criterion = db.scalar(
            select(RubricCriterion).where(
                RubricCriterion.rubric_id == rubric.id, RubricCriterion.key == key
            )
        )
        if criterion is None:
            criterion = RubricCriterion(rubric_id=rubric.id, key=key, label=label)
            db.add(criterion)
        criterion.label = label
        criterion.max_points = max_points
        criterion.position = position
    db.flush()
    rubric.total_points = sum(spec[2] for spec in specs)
    db.flush()
    return assignment


def main() -> int:
    log("Seeding OpenCS Labs")
    log(f"  database: {settings.database_url.rsplit('@', 1)[-1]}")
    with SessionLocal() as db:
        users = upsert_users(db)
        course = upsert_course(db, users)
        upsert_datasets(db)
        upsert_curriculum(db)
        upsert_exercises(db)
        upsert_course_work(db, users, course)
        db.commit()

        log("\nDemo accounts (development only):")
        for spec in SEED_USERS:
            log(f"  {spec['email']:<26} password: {DEFAULT_PASSWORD}   role: {spec['role']}")
        log("\nSeed complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
