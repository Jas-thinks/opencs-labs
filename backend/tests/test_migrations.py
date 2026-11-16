"""Migration checks.

The development database is SQLite and production is PostgreSQL. A migration
that only works on one of them is a deployment failure waiting to happen, so
the schema is applied through Alembic (not just ``create_all``) on SQLite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

BACKEND = Path(__file__).resolve().parents[1]


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "OPENCE_DATABASE_URL": database_url,
            "PYTHONPATH": str(BACKEND),
        },
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("filename", ["migrate-up.db"])
def test_migration_applies_on_sqlite(tmp_path, filename):
    db_path = tmp_path / filename
    url = f"sqlite:///{db_path}"
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    for expected in {
        "users",
        "courses",
        "enrollments",
        "datasets",
        "dataset_versions",
        "learning_paths",
        "modules",
        "lessons",
        "lesson_progress",
        "exercises",
        "practice_attempts",
        "notebooks",
    }:
        assert expected in tables, f"missing table {expected}"


def test_migration_downgrades_cleanly(tmp_path):
    db_path = tmp_path / "migrate-down.db"
    url = f"sqlite:///{db_path}"
    assert _alembic(url, "upgrade", "head").returncode == 0
    result = _alembic(url, "downgrade", "base")
    assert result.returncode == 0, result.stderr

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert "users" not in tables
