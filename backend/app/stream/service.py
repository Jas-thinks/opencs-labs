"""Course stream: announcements and materials (one-way; ADR-010).

Staff (instructors and TAs, D1) post; the author or an instructor edits and
deletes; enrolled members read. Visibility of scheduled posts is evaluated at
query time; notification fan-out runs in the job worker, never in the request.
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError, Conflict, Forbidden, NotFound
from app.core.jobs import enqueue
from app.core.time import ensure_utc, now_utc
from app.courses.models import Enrollment
from app.courses.permissions import (
    STAFF_ROLES,
    course_role,
    get_course,
    require_course_member,
    require_course_staff,
)
from app.stream.models import CoursePost, CoursePostAttachment, PostRead
from app.users.models import User

STAFF = ("admin", *STAFF_ROLES)
MODERATORS = ("admin", "instructor", "staff")


def _uuid(value: str, resource: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise NotFound(resource, str(value)) from exc


def is_visible(post: CoursePost, now=None) -> bool:
    if post.deleted_at is not None or post.status != "published":
        return False
    publish_at = ensure_utc(post.publish_at)
    return publish_at is None or publish_at <= (now or now_utc())


class StreamService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- attachments -----------------------------------------------------
    def _resolve_attachment(self, course_id: uuid.UUID, item, position: int) -> CoursePostAttachment:
        from app.datasets.models import Dataset
        from app.grading.models import Assignment
        from app.learning.models import Lesson
        from app.practice.models import Exercise

        target = item.target.strip()
        if item.kind == "file":
            raise ApiError(
                "ATTACHMENT_UNSUPPORTED",
                "File uploads are not available yet; attach a link instead.",
                status_code=422,
            )
        if item.kind == "link":
            parts = urlsplit(target)
            # Only real web links: never javascript:, data:, file: and friends.
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ApiError(
                    "INVALID_LINK", "Links must start with http:// or https://", status_code=422
                )
            return CoursePostAttachment(
                kind="link", url=target, label=(item.label or parts.netloc)[:240], position=position
            )
        if item.kind == "dataset":
            row = self.db.scalar(select(Dataset).where(Dataset.slug == target, Dataset.is_published.is_(True)))
            path = f"/datasets/{target}"
        elif item.kind == "lesson":
            row = self.db.scalar(
                select(Lesson).where(Lesson.slug == target, Lesson.is_published.is_(True)).limit(1)
            )
            path = f"/learn/{target}"
        elif item.kind == "exercise":
            row = self.db.scalar(select(Exercise).where(Exercise.slug == target, Exercise.is_published.is_(True)))
            path = f"/practice/{target}"
        else:  # assignment in this course
            row = self.db.get(Assignment, _uuid(target, "assignment"))
            if row is not None and row.course_id != course_id:
                row = None
            path = f"/classes/{course_id}/classwork/{target}"
        if row is None:
            raise NotFound(item.kind, target)
        return CoursePostAttachment(
            kind=item.kind,
            ref_id=row.id,
            url=path,
            label=(item.label or row.title)[:240],
            position=position,
        )

    # -- serialisation ---------------------------------------------------
    def _post_out(
        self,
        post: CoursePost,
        *,
        user: User,
        role: str,
        authors: dict[uuid.UUID, User],
        read_ids: set[uuid.UUID],
        read_counts: dict[uuid.UUID, int] | None,
        audience: int | None,
    ) -> dict[str, Any]:
        author = authors.get(post.author_id) if post.author_id else None
        staff = role in STAFF
        return {
            "id": post.id,
            "course_id": post.course_id,
            "kind": post.kind,
            "title": post.title,
            "body": post.body,
            "topic": post.topic,
            "is_pinned": post.is_pinned,
            "status": post.status,
            "publish_at": post.publish_at,
            "published_at": post.published_at,
            "edited_at": post.edited_at,
            "created_at": post.created_at,
            "author": {"id": author.id, "display_name": author.display_name} if author else None,
            "attachments": [
                {
                    "id": a.id,
                    "kind": a.kind,
                    "label": a.label,
                    "url": a.url,
                    "internal": a.kind != "link",
                }
                for a in post.attachments
            ],
            "is_read": post.id in read_ids,
            "can_edit": staff and (post.author_id == user.id or role in MODERATORS),
            "read_count": (read_counts or {}).get(post.id, 0) if staff else None,
            "audience": audience if staff else None,
        }

    def _context(self, posts: list[CoursePost], user: User, role: str, course_id: uuid.UUID):
        ids = [p.id for p in posts]
        author_ids = {p.author_id for p in posts if p.author_id}
        authors = (
            {u.id: u for u in self.db.scalars(select(User).where(User.id.in_(author_ids)))}
            if author_ids
            else {}
        )
        read_ids = set(
            self.db.scalars(
                select(PostRead.post_id).where(PostRead.user_id == user.id, PostRead.post_id.in_(ids))
            )
        ) if ids else set()
        read_counts = None
        audience = None
        if role in STAFF and ids:
            students = select(Enrollment.user_id).where(
                Enrollment.course_id == course_id, Enrollment.role_in_course == "student"
            )
            read_counts = {
                post_id: int(count)
                for post_id, count in self.db.execute(
                    select(PostRead.post_id, func.count())
                    .where(PostRead.post_id.in_(ids), PostRead.user_id.in_(students))
                    .group_by(PostRead.post_id)
                ).all()
            }
            audience = int(
                self.db.scalar(select(func.count()).select_from(students.subquery())) or 0
            )
        return authors, read_ids, read_counts, audience

    # -- queries ---------------------------------------------------------
    def list_posts(
        self,
        user: User,
        course_id: str,
        *,
        kind: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict:
        course = get_course(self.db, course_id)
        role = require_course_member(self.db, user, course.id)
        offset = 0
        if cursor:
            try:
                offset = max(0, int(cursor))
            except ValueError as exc:
                raise Conflict("INVALID_CURSOR", "The pagination cursor is invalid") from exc
        stmt = select(CoursePost).where(
            CoursePost.course_id == course.id, CoursePost.deleted_at.is_(None)
        )
        if kind:
            stmt = stmt.where(CoursePost.kind == kind)
        if role not in STAFF:
            # Timestamps are stored in UTC (normalised on write), so this
            # comparison is correct on both SQLite and PostgreSQL.
            stmt = stmt.where(
                CoursePost.status == "published",
                or_(CoursePost.publish_at.is_(None), CoursePost.publish_at <= now_utc()),
            )
        stmt = stmt.order_by(
            CoursePost.is_pinned.desc(),
            func.coalesce(CoursePost.publish_at, CoursePost.created_at).desc(),
            CoursePost.id,
        )
        posts = list(self.db.scalars(stmt.limit(limit + 1).offset(offset)))
        has_more = len(posts) > limit
        posts = posts[:limit]
        authors, read_ids, read_counts, audience = self._context(posts, user, role, course.id)
        return {
            "posts": [
                self._post_out(
                    p, user=user, role=role, authors=authors, read_ids=read_ids,
                    read_counts=read_counts, audience=audience,
                )
                for p in posts
            ],
            "next_cursor": str(offset + limit) if has_more else None,
        }

    def _load(self, user: User, post_id: str) -> tuple[CoursePost, str]:
        post = self.db.get(CoursePost, _uuid(post_id, "post"))
        if post is None or post.deleted_at is not None:
            raise NotFound("post")
        role = course_role(self.db, user, post.course_id)
        if role is None:
            raise NotFound("post")
        if role not in STAFF and not is_visible(post):
            raise NotFound("post")
        return post, role

    def get_post(self, user: User, post_id: str) -> dict:
        post, role = self._load(user, post_id)
        return self._one(post, user, role)

    def _one(self, post: CoursePost, user: User, role: str) -> dict:
        authors, read_ids, read_counts, audience = self._context([post], user, role, post.course_id)
        return self._post_out(
            post, user=user, role=role, authors=authors, read_ids=read_ids,
            read_counts=read_counts, audience=audience,
        )

    # -- writes ----------------------------------------------------------
    def _validate_content(self, kind: str, title: str, body: str) -> None:
        if kind == "material" and not title.strip():
            raise ApiError("TITLE_REQUIRED", "Materials need a title", status_code=422)
        if not title.strip() and not body.strip():
            raise ApiError("EMPTY_POST", "Write something before posting", status_code=422)

    def _maybe_publish(self, post: CoursePost) -> None:
        """Fan out notifications the first time a post becomes visible."""
        if post.published_at is None and is_visible(post):
            post.published_at = now_utc()
            enqueue(self.db, "notify_post", {"post_id": str(post.id)})

    def create_post(self, user: User, course_id: str, payload) -> dict:
        course = get_course(self.db, course_id)
        role = require_course_staff(self.db, user, course.id)
        if course.status == "archived":
            raise Conflict("COURSE_ARCHIVED", "This class is archived and read-only")
        self._validate_content(payload.kind, payload.title, payload.body)
        post = CoursePost(
            course_id=course.id,
            author_id=user.id,
            kind=payload.kind,
            title=payload.title.strip(),
            body=payload.body,
            topic=(payload.topic or "").strip() or None,
            is_pinned=payload.is_pinned,
            status=payload.status,
            publish_at=ensure_utc(payload.publish_at),
        )
        post.attachments = [
            self._resolve_attachment(course.id, item, index)
            for index, item in enumerate(payload.attachments)
        ]
        self.db.add(post)
        self.db.flush()
        self._maybe_publish(post)
        self.db.commit()
        self.db.refresh(post)
        return self._one(post, user, role)

    def update_post(self, user: User, post_id: str, payload) -> dict:
        post, role = self._load(user, post_id)
        self._require_editor(user, post, role)
        data = payload.model_dump(exclude_unset=True)
        attachments = data.pop("attachments", None)
        if "publish_at" in data:
            data["publish_at"] = ensure_utc(data["publish_at"])
        if "topic" in data:
            data["topic"] = (data["topic"] or "").strip() or None
        for field, value in data.items():
            setattr(post, field, value)
        if attachments is not None:
            post.attachments = [
                self._resolve_attachment(post.course_id, item, index)
                for index, item in enumerate(payload.attachments or [])
            ]
        self._validate_content(post.kind, post.title, post.body)
        if post.published_at is not None:
            post.edited_at = now_utc()
        self._maybe_publish(post)
        self.db.commit()
        self.db.refresh(post)
        return self._one(post, user, role)

    def delete_post(self, user: User, post_id: str) -> None:
        post, role = self._load(user, post_id)
        self._require_editor(user, post, role)
        post.deleted_at = now_utc()  # soft delete: keeps an audit trail
        self.db.commit()

    @staticmethod
    def _require_editor(user: User, post: CoursePost, role: str) -> None:
        if role not in STAFF:
            raise Forbidden("Only course staff can change posts")
        if post.author_id != user.id and role not in MODERATORS:
            raise Forbidden("Only the author or an instructor can change this post")

    # -- read receipts ---------------------------------------------------
    def mark_read(self, user: User, post_id: str) -> None:
        post, _ = self._load(user, post_id)
        exists = self.db.get(PostRead, (post.id, user.id))
        if exists is None:
            self.db.add(PostRead(post_id=post.id, user_id=user.id, read_at=now_utc()))
            self.db.commit()

    def readers(self, user: User, post_id: str) -> dict:
        post, role = self._load(user, post_id)
        if role not in STAFF:
            raise Forbidden("Only course staff can see read receipts")
        rows = self.db.execute(
            select(User, PostRead.read_at)
            .join(Enrollment, Enrollment.user_id == User.id)
            .outerjoin(PostRead, (PostRead.user_id == User.id) & (PostRead.post_id == post.id))
            .where(Enrollment.course_id == post.course_id, Enrollment.role_in_course == "student")
            .order_by(User.display_name)
        ).all()
        read = [
            {"user_id": u.id, "display_name": u.display_name, "read_at": at}
            for u, at in rows
            if at is not None
        ]
        unread = [
            {"user_id": u.id, "display_name": u.display_name, "read_at": None}
            for u, at in rows
            if at is None
        ]
        return {"read": read, "unread": unread}
