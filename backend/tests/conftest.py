"""Shared pytest fixtures.

Tests run against an isolated SQLite database and the fake infrastructure
seam. Nothing here changes the production code path.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.datasets.models import Dataset, DatasetVersion
from app.db.base import Base, utcnow
from app.db.session import get_db
from app.integrations.grader import get_grader
from app.integrations.notebooks import get_notebook_backend
from app.learning.models import LearningPath, Lesson, Module
from app.main import app as fastapi_app
from app.practice.models import Exercise
from app.users.models import User
from tests.fakes import FakeGrader, FakeNotebookBackend

PASSWORD = "test-password"
_PASSWORD_HASH: str | None = None


def password_hash() -> str:
    """Hash once per test process; bcrypt is deliberately slow."""
    global _PASSWORD_HASH
    if _PASSWORD_HASH is None:
        _PASSWORD_HASH = hash_password(PASSWORD)
    return _PASSWORD_HASH


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.core.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@pytest.fixture()
def db(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def backend() -> FakeNotebookBackend:
    return FakeNotebookBackend()


@pytest.fixture()
def grader() -> FakeGrader:
    return FakeGrader(passed=True)


@pytest.fixture()
def client(session_factory, backend, grader) -> Iterator[TestClient]:
    from app.main import app

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_notebook_backend] = lambda: backend
    app.dependency_overrides[get_grader] = lambda: grader
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def users(db: Session) -> dict[str, User]:
    specs = [
        ("student1@test.local", "Student One", "student", "teststudent1"),
        ("student2@test.local", "Student Two", "student", "teststudent2"),
        ("instructor@test.local", "Instructor", "instructor", "testinstructor"),
    ]
    created = {}
    for email, name, role, hub in specs:
        user = User(
            email=email,
            display_name=name,
            role=role,
            hub_username=hub,
            password_hash=password_hash(),
        )
        db.add(user)
        created[email] = user
    db.commit()
    for user in created.values():
        db.refresh(user)
    return created


def login(client: TestClient, email: str, password: str = PASSWORD) -> TestClient:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture()
def student_client(client, users) -> TestClient:
    return login(client, "student1@test.local")


@pytest.fixture()
def other_student_client(client, users) -> TestClient:
    # A separate cookie jar for a second user.
    second = TestClient(client.app)
    return login(second, "student2@test.local")


@pytest.fixture()
def dataset(db: Session) -> Dataset:
    dataset = Dataset(
        slug="iris",
        title="Iris",
        summary="Flower measurements",
        description="Iris test dataset",
        category="Classic classification",
        teaching_tags=["EDA"],
        is_published=True,
        position=1,
    )
    db.add(dataset)
    db.flush()
    version = DatasetVersion(
        dataset_id=dataset.id,
        version=1,
        format="csv",
        object_key="iris/v1/iris.csv",
        relative_mount_path="iris/v1/iris.csv",
        size_bytes=4600,
        sha256="a" * 64,
        row_count=150,
        columns=[
            {"name": "sepal_length", "dtype": "float64"},
            {"name": "species", "dtype": "object"},
        ],
        preview=[{"sepal_length": 5.1, "species": "setosa"}],
        license="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        license_status="verified",
        source_url="https://archive.ics.uci.edu/dataset/53/iris",
        attribution="Fisher",
        is_current=True,
        published_at=utcnow(),
    )
    db.add(version)
    db.commit()
    db.refresh(dataset)
    return dataset


@pytest.fixture()
def lesson(db: Session) -> Lesson:
    path = LearningPath(
        slug="test-path", title="Test Path", description="test", is_published=True
    )
    db.add(path)
    db.flush()
    module = Module(
        learning_path_id=path.id,
        slug="test-module",
        title="Test Module",
        description="test",
        position=1,
        is_published=True,
    )
    db.add(module)
    db.flush()
    lesson = Lesson(
        module_id=module.id,
        slug="test-lesson",
        title="Test Lesson",
        objective="Learn a thing",
        summary="A test lesson",
        position=1,
        estimated_minutes=5,
        content={
            "stages": [
                {"key": "explore", "label": "Explore", "blocks": [{"type": "markdown", "text": "hi"}]},
                {"key": "understand", "label": "Understand", "blocks": []},
                {"key": "inspect", "label": "Inspect", "blocks": []},
                {"key": "execute", "label": "Execute", "blocks": []},
                {"key": "visualize", "label": "Visualize", "blocks": []},
                {"key": "debug", "label": "Debug", "blocks": []},
                {"key": "practice", "label": "Practice", "blocks": []},
            ],
            "takeaways": ["one"],
            "glossary": [],
        },
        dataset_slugs=["iris"],
        exercise_slugs=["test-exercise"],
        notebook_activity={
            "title": "Lesson notebook",
            "intro_markdown": "# Test lesson",
            "cells": ["import pandas as pd\ndf = pd.read_csv('/opt/opencs/datasets/iris/v1/iris.csv')\ndf.head()"],
        },
        is_published=True,
        version=1,
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)
    return lesson


@pytest.fixture()
def exercise(db: Session) -> Exercise:
    exercise = Exercise(
        slug="test-exercise",
        title="Test Exercise",
        topic="Pandas",
        difficulty="Easy",
        objective="Do a thing",
        instructions={"markdown": "Do the thing"},
        dataset_slugs=["iris"],
        starter_notebook={
            "intro_markdown": "# Exercise",
            "cells": ["import pandas as pd\n\ndf = pd.read_csv('/opt/opencs/datasets/iris/v1/iris.csv')"],
        },
        hints=["first hint", "second hint"],
        evaluation={
            "type": "python_assertions",
            "tests": [
                {"id": "loaded", "description": "df exists", "code": "assert 'df' in globals()"}
            ],
        },
        solution_code="secret solution that must never be serialised",
        estimated_minutes=10,
        position=1,
        is_published=True,
        version=1,
    )
    db.add(exercise)
    db.commit()
    db.refresh(exercise)
    return exercise
