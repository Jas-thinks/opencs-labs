"""Authoritative autosave watcher.

Every active notebook session is polled on an interval. If the working copy on
disk (or in JupyterHub contents) differs from the last snapshot hash, an
``autosave`` version is written. This makes autosave work even when the
JupyterLab tab never calls the API.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy import select

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.notebooks.models import Notebook, NotebookSession
from app.notebooks.service import NotebookService
from app.users.models import User

logger = logging.getLogger("opencs.notebooks.watcher")


def run_once(session_factory=None, service_factory=NotebookService) -> int:
    """Snapshot changed working copies for active sessions.

    ``session_factory`` and ``service_factory`` are injectable so the watcher
    can be exercised against an isolated database and fake notebook backend.
    """
    cutoff = utcnow() - dt.timedelta(seconds=settings.watcher_active_window_seconds)
    snapshotted = 0
    db = (session_factory or SessionLocal)()
    try:
        pairs = db.execute(
            select(NotebookSession.notebook_id, NotebookSession.user_id)
            .where(
                NotebookSession.ended_at.is_(None),
                NotebookSession.last_seen_at >= cutoff,
            )
            .distinct()
        ).all()
        service = service_factory(db)
        for notebook_id, user_id in pairs:
            notebook = db.get(Notebook, notebook_id)
            user = db.get(User, user_id)
            if notebook is None or user is None:
                continue
            try:
                if service.watch_snapshot(user, notebook):
                    snapshotted += 1
            except Exception:  # noqa: BLE001 - one notebook must not stop the tick
                db.rollback()
                logger.exception("autosave watcher failed for notebook %s", notebook_id)
    finally:
        db.close()
    return snapshotted


async def watcher_loop(interval_seconds: int | None = None) -> None:
    interval = interval_seconds or settings.watcher_interval_seconds
    while True:
        try:
            changed = await asyncio.to_thread(run_once)
            if changed:
                logger.info("watcher snapshotted %s changed notebooks", changed)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the loop must survive a bad tick
            logger.exception("autosave watcher tick failed")
        await asyncio.sleep(interval)
