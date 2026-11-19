"""Notification inbox and the fan-out used by the job worker."""

from __future__ import annotations

import uuid

from sqlalchemy import func, insert, literal, select, update
from sqlalchemy.orm import Session

from app.core.time import now_utc
from app.courses.models import Enrollment
from app.notifications.models import Notification
from app.users.models import User


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, user: User, *, unread_only: bool = False, cursor: str | None = None, limit: int = 20) -> dict:
        offset = max(0, int(cursor)) if cursor and cursor.isdigit() else 0
        stmt = select(Notification).where(Notification.user_id == user.id)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        rows = list(
            self.db.scalars(
                stmt.order_by(Notification.created_at.desc(), Notification.id)
                .limit(limit + 1)
                .offset(offset)
            )
        )
        has_more = len(rows) > limit
        return {
            "notifications": [self._out(n) for n in rows[:limit]],
            "next_cursor": str(offset + limit) if has_more else None,
        }

    def unread_count(self, user: User) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == user.id, Notification.read_at.is_(None))
            )
            or 0
        )

    def mark_read(self, user: User, ids: list[uuid.UUID] | None) -> int:
        stmt = update(Notification).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
        if ids:
            stmt = stmt.where(Notification.id.in_(ids))
        result = self.db.execute(stmt.values(read_at=now_utc()))
        self.db.commit()
        return int(result.rowcount or 0)

    @staticmethod
    def _out(n: Notification) -> dict:
        return {
            "id": n.id,
            "kind": n.kind,
            "course_id": n.course_id,
            "title": n.title,
            "link": n.link,
            "created_at": n.created_at,
            "read_at": n.read_at,
        }


def fan_out_to_students(
    db: Session,
    *,
    course_id: uuid.UUID,
    kind: str,
    ref_type: str,
    ref_id: uuid.UUID,
    title: str,
    link: str,
    exclude_user_id: uuid.UUID | None = None,
) -> int:
    """One INSERT ... SELECT for the whole class (no per-student round trips)."""
    students = select(
        func.gen_random_uuid() if db.bind.dialect.name == "postgresql" else Enrollment.id,
        Enrollment.user_id,
        literal(kind),
        literal(course_id),
        literal(ref_type),
        literal(ref_id),
        literal(title[:300]),
        literal(link[:300]),
        literal(now_utc()),
    ).where(Enrollment.course_id == course_id, Enrollment.role_in_course == "student")
    if exclude_user_id is not None:
        students = students.where(Enrollment.user_id != exclude_user_id)
    if db.bind.dialect.name != "postgresql":
        # SQLite (dev/tests): no server-side UUID function; insert row by row.
        rows = db.execute(students).all()
        for row in rows:
            db.add(
                Notification(
                    user_id=row[1], kind=kind, course_id=course_id, ref_type=ref_type,
                    ref_id=ref_id, title=title[:300], link=link[:300], created_at=now_utc(),
                )
            )
        return len(rows)
    result = db.execute(
        insert(Notification).from_select(
            [
                Notification.id, Notification.user_id, Notification.kind, Notification.course_id,
                Notification.ref_type, Notification.ref_id, Notification.title, Notification.link,
                Notification.created_at,
            ],
            students,
        )
    )
    return int(result.rowcount or 0)
