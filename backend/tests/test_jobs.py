"""Job outbox worker, retry behavior and autosave retention."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.core.jobs import Job, JobWorker, enqueue, schedule_maintenance
from app.core.time import ensure_utc
from app.db.base import utcnow
from app.notebooks.ipynb import build_notebook
from app.notebooks.models import Notebook
from app.notebooks.versions import NotebookVersionService


def test_maintenance_jobs_are_scheduled_once(session_factory):
    assert schedule_maintenance(session_factory) == 3
    assert schedule_maintenance(session_factory) == 0

    session = session_factory()
    try:
        kinds = sorted(session.scalars(select(Job.kind)).all())
        assert kinds == ["close_idle_sessions", "prune_autosaves", "publish_due_posts"]
    finally:
        session.close()


def test_worker_processes_jobs(session_factory):
    session = session_factory()
    try:
        enqueue(session, "notify_grade", {"submission_id": "s", "user_id": "u"})
        session.commit()
    finally:
        session.close()

    worker = JobWorker(session_factory)
    assert worker.drain() == 1

    session = session_factory()
    try:
        job = session.scalar(select(Job))
        assert job.status == "done"
        assert job.attempts == 1
        assert job.last_error is None
    finally:
        session.close()


def test_failed_job_is_retried_with_backoff(session_factory):
    session = session_factory()
    try:
        job = enqueue(session, "explode", {})
        session.commit()
        job_id = job.id
    finally:
        session.close()

    worker = JobWorker(session_factory)

    def explode(db, payload):
        raise RuntimeError("boom")

    worker.handlers["explode"] = explode
    assert worker.run_once() is True

    session = session_factory()
    try:
        reloaded = session.get(Job, job_id)
        assert reloaded.status == "pending"
        assert reloaded.attempts == 1
        assert "boom" in reloaded.last_error
        assert ensure_utc(reloaded.run_at) > utcnow()
    finally:
        session.close()

    # Running the retry to the attempt cap marks the job failed.
    for _ in range(10):
        session = session_factory()
        try:
            row = session.get(Job, job_id)
            if row.status == "failed":
                break
            row.run_at = utcnow() - dt.timedelta(seconds=1)
            session.commit()
        finally:
            session.close()
        worker.run_once()

    session = session_factory()
    try:
        assert session.get(Job, job_id).status == "failed"
    finally:
        session.close()


def test_prune_autosaves_keeps_submissions(db, users):
    user = users["student1@test.local"]
    notebook = Notebook(
        user_id=user.id,
        title="Prune",
        file_name="Prune.ipynb",
        kind="personal",
        environment_image="",
    )
    db.add(notebook)
    db.commit()
    db.refresh(notebook)

    service = NotebookVersionService(db)
    for index in range(3):
        service.create_version(
            notebook, build_notebook(title=f"autosave {index}"), kind="autosave"
        )
    service.create_version(notebook, build_notebook(title="submitted"), kind="submission")

    assert service.prune_autosaves(notebook.id, keep=2) == 1
    versions = service.list_versions(notebook.id)
    kinds = [version["kind"] for version in versions]
    assert kinds.count("autosave") == 2
    assert kinds.count("submission") == 1
    assert versions[0]["kind"] == "submission"
