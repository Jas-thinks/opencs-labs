"""Database-backed job outbox and in-process worker.

Jobs are inserted in the same transaction as the business change that needs
them, so a crash between "grade saved" and "notification sent" is recoverable.
There is no Redis or Celery: a single asyncio task polls the table.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
import uuid
from typing import Any, Callable

from sqlalchemy import DateTime, Integer, JSON, String, Text, Uuid, select, update
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from app.core.config import settings
from app.db.base import Base, utcnow
from app.db.session import SessionLocal

logger = logging.getLogger("opencs.jobs")

JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JOB_PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


def enqueue(
    db,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    run_at: dt.datetime | None = None,
) -> Job:
    """Add a job to the caller's transaction. The caller commits."""
    job = Job(kind=kind, payload=payload or {}, run_at=run_at or utcnow())
    db.add(job)
    return job


MAINTENANCE_KINDS = ("close_idle_sessions", "prune_autosaves", "publish_due_posts")


def schedule_maintenance(session_factory: sessionmaker = SessionLocal) -> int:
    """Ensure one pending maintenance job of each kind exists.

    The worker calls this on a slow cadence; the uniqueness check prevents
    duplicate maintenance work when a job is already queued or running.
    """
    scheduled = 0
    db = session_factory()
    try:
        for kind in MAINTENANCE_KINDS:
            exists = db.scalar(
                select(Job.id)
                .where(Job.kind == kind, Job.status.in_((JOB_PENDING, JOB_RUNNING)))
                .limit(1)
            )
            if exists is None:
                enqueue(db, kind, {})
                scheduled += 1
        if scheduled:
            db.commit()
    finally:
        db.close()
    return scheduled


class JobWorker:
    def __init__(self, session_factory: sessionmaker = SessionLocal) -> None:
        self.session_factory = session_factory
        self.handlers: dict[str, Callable[[Any, dict], None]] = {
            "prune_autosaves": _handle_prune_autosaves,
            "close_idle_sessions": _handle_close_idle_sessions,
            "notify_grade": _handle_notify_grade,
            "notify_post": _handle_notify_post,
            "publish_due_posts": _handle_publish_due_posts,
            "recompute_rollups": _handle_recompute_rollups,
        }

    # -- claiming --------------------------------------------------------
    def _reclaim_stuck(self, db) -> None:
        cutoff = utcnow() - dt.timedelta(seconds=settings.job_stuck_seconds)
        db.execute(
            update(Job)
            .where(Job.status == JOB_RUNNING, Job.locked_at < cutoff)
            .values(status=JOB_PENDING, locked_at=None)
        )

    def _claim(self, db) -> Job | None:
        self._reclaim_stuck(db)
        now = utcnow()
        stmt = (
            select(Job)
            .where(Job.status == JOB_PENDING, Job.run_at <= now)
            .order_by(Job.run_at)
            .limit(1)
        )
        try:
            stmt = stmt.with_for_update(skip_locked=True)
        except Exception:  # noqa: BLE001 - dialect without row locking
            pass
        job = db.scalar(stmt)
        if job is None:
            db.commit()
            return None
        claimed = db.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == JOB_PENDING)
            .values(status=JOB_RUNNING, locked_at=now, attempts=Job.attempts + 1)
        ).rowcount
        if not claimed:
            db.rollback()
            return None
        db.commit()
        db.refresh(job)
        return job

    # -- execution -------------------------------------------------------
    def _fail(self, db, job_id: uuid.UUID, error: Exception) -> None:
        db.rollback()
        job = db.get(Job, job_id)
        if job is None:
            return
        job.last_error = str(error)[:4000]
        if job.attempts >= settings.job_max_attempts:
            job.status = JOB_FAILED
        else:
            job.status = JOB_PENDING
            backoff = min(300, 2 ** max(job.attempts, 1))
            job.run_at = utcnow() + dt.timedelta(seconds=backoff)
        job.locked_at = None
        db.commit()
        logger.warning("job %s (%s) failed: %s", job.id, job.kind, error)

    def run_once(self) -> bool:
        db = self.session_factory()
        try:
            job = self._claim(db)
            if job is None:
                return False
            handler = self.handlers.get(job.kind)
            if handler is None:
                logger.warning("unknown job kind %s", job.kind)
                job.status = JOB_DONE
                job.locked_at = None
                db.commit()
                return True
            try:
                handler(db, job.payload or {})
                job = db.get(Job, job.id)
                if job is not None:
                    job.status = JOB_DONE
                    job.locked_at = None
                    job.last_error = None
                db.commit()
            except Exception as exc:  # noqa: BLE001 - one bad job must not stop the worker
                self._fail(db, job.id, exc)
            return True
        finally:
            db.close()

    def drain(self, limit: int = 10) -> int:
        processed = 0
        for _ in range(limit):
            if not self.run_once():
                break
            processed += 1
        return processed


# -- handlers -------------------------------------------------------------
def _uuid_or_none(value) -> uuid.UUID | None:
    """Notification jobs must not fail (and retry forever) on a stale reference."""
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _handle_prune_autosaves(db, payload: dict) -> None:
    from app.notebooks.versions import NotebookVersionService

    service = NotebookVersionService(db)
    notebook_id = payload.get("notebook_id")
    service.prune_autosaves(notebook_id, keep=settings.autosave_retention)


def _handle_close_idle_sessions(db, payload: dict) -> None:
    from app.notebooks.models import NotebookSession

    cutoff = utcnow() - dt.timedelta(seconds=settings.session_idle_seconds)
    rows = db.execute(
        update(NotebookSession)
        .where(NotebookSession.ended_at.is_(None), NotebookSession.last_seen_at < cutoff)
        .values(ended_at=utcnow())
    ).rowcount
    if rows:
        logger.info("closed %s idle notebook sessions", rows)


def _handle_notify_grade(db, payload: dict) -> None:
    """A grade was returned: tell the student (in-app; email can attach here)."""
    from app.grading.models import Assignment, Submission
    from app.notifications.models import Notification

    submission_id = _uuid_or_none(payload.get("submission_id"))
    submission = db.get(Submission, submission_id) if submission_id else None
    if submission is None:
        logger.info("grade notification skipped: unknown submission %s", payload.get("submission_id"))
        return
    assignment = db.get(Assignment, submission.assignment_id)
    if assignment is None:
        return
    db.add(
        Notification(
            user_id=submission.user_id,
            kind="grade_returned",
            course_id=assignment.course_id,
            ref_type="submission",
            ref_id=submission.id,
            title=f"Your work on “{assignment.title}” was returned",
            link=f"/classes/{assignment.course_id}/classwork/{assignment.id}",
        )
    )


def _handle_notify_post(db, payload: dict) -> None:
    """Fan a newly visible announcement/material out to the class."""
    from app.notifications.service import fan_out_to_students
    from app.stream.models import CoursePost

    post_id = _uuid_or_none(payload.get("post_id"))
    post = db.get(CoursePost, post_id) if post_id else None
    if post is None or post.deleted_at is not None or post.status != "published":
        return
    noun = "announcement" if post.kind == "announcement" else "material"
    headline = post.title or (post.body.strip().splitlines() or [""])[0]
    count = fan_out_to_students(
        db,
        course_id=post.course_id,
        kind=f"new_{noun}",
        ref_type="post",
        ref_id=post.id,
        title=f"New {noun}: {headline[:200]}",
        link=f"/classes/{post.course_id}/stream#post-{post.id}",
        exclude_user_id=post.author_id,
    )
    logger.info("post %s notified %s students", post.id, count)


def _handle_publish_due_posts(db, payload: dict) -> None:
    """Scheduled posts become visible at query time; this only fans out their
    notifications once publish_at has passed (cadence: maintenance tick)."""
    from app.stream.models import CoursePost

    now = utcnow()
    due = list(
        db.scalars(
            select(CoursePost).where(
                CoursePost.status == "published",
                CoursePost.deleted_at.is_(None),
                CoursePost.published_at.is_(None),
                CoursePost.publish_at.is_not(None),
                CoursePost.publish_at <= now,
            )
        )
    )
    for post in due:
        post.published_at = now
        enqueue(db, "notify_post", {"post_id": str(post.id)})


def _handle_recompute_rollups(db, payload: dict) -> None:
    logger.info("rollup recompute requested (no-op until a rollup table exists)")


async def job_worker_loop(interval_seconds: int | None = None) -> None:
    worker = JobWorker()
    interval = interval_seconds or settings.job_worker_interval_seconds
    last_maintenance = 0.0
    while True:
        try:
            now = time.monotonic()
            if now - last_maintenance >= 300:
                await asyncio.to_thread(schedule_maintenance)
                last_maintenance = now
            await asyncio.to_thread(worker.drain)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must survive a bad tick
            logger.exception("job worker tick failed")
        await asyncio.sleep(interval)
