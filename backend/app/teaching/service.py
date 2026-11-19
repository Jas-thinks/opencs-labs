"""Cross-cutting read models for the two personas.

* gradebook  - staff: students x assignments, released + draft state, weighted total
* queue      - staff: what needs grading/returning across all my classes
* home       - student: due soon, latest posts, recent feedback (one round trip)
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.time import ensure_utc, now_utc
from app.courses.models import Course, Enrollment
from app.courses.permissions import STAFF_ROLES, get_course, require_course_staff
from app.grading.models import Assignment, Submission, SubmissionGrade
from app.grading.service import is_visible_to_students
from app.stream.models import CoursePost, PostRead
from app.users.models import User


def _latest_by_pair(submissions) -> dict[tuple[uuid.UUID, uuid.UUID], Submission]:
    latest: dict[tuple[uuid.UUID, uuid.UUID], Submission] = {}
    for s in submissions:
        key = (s.assignment_id, s.user_id)
        current = latest.get(key)
        if current is None or s.attempt_number > current.attempt_number:
            latest[key] = s
    return latest


class TeachingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -- gradebook -------------------------------------------------------
    def gradebook(self, user: User, course_id: str) -> dict:
        course = get_course(self.db, course_id)
        require_course_staff(self.db, user, course.id)
        assignments = list(
            self.db.scalars(
                select(Assignment)
                .where(
                    Assignment.course_id == course.id,
                    Assignment.archived_at.is_(None),
                    Assignment.is_published.is_(True),
                )
                .order_by(Assignment.due_at.is_(None), Assignment.due_at, Assignment.created_at)
            )
        )
        students = list(
            self.db.scalars(
                select(User)
                .join(Enrollment, Enrollment.user_id == User.id)
                .where(Enrollment.course_id == course.id, Enrollment.role_in_course == "student")
                .order_by(User.display_name)
            )
        )
        ids = [a.id for a in assignments]
        latest = _latest_by_pair(
            self.db.scalars(select(Submission).where(Submission.assignment_id.in_(ids))) if ids else []
        )
        now = now_utc()
        rows = []
        for student in students:
            cells = []
            weighted, weight_total = 0.0, 0.0
            for a in assignments:
                s = latest.get((a.id, student.id))
                due = ensure_utc(a.due_at)
                if s is None:
                    state = "missing" if due is not None and due < now else "not_submitted"
                elif s.status == "graded":
                    state = "draft"
                elif s.final_score is not None:
                    state = "returned"
                else:
                    state = "submitted"
                if s is not None and s.final_score is not None and a.max_points:
                    weighted += a.weight * (float(s.final_score) / a.max_points)
                    weight_total += a.weight
                cells.append(
                    {
                        "assignment_id": a.id,
                        "submission_id": s.id if s else None,
                        "state": state,
                        "score": s.final_score if s else None,
                        "is_late": bool(s.is_late) if s else False,
                    }
                )
            rows.append(
                {
                    "user_id": student.id,
                    "display_name": student.display_name,
                    "email": student.email,
                    "cells": cells,
                    # Weighted average over returned work only, in percent.
                    "weighted_percent": round(100 * weighted / weight_total, 1) if weight_total else None,
                }
            )
        return {
            "course_id": course.id,
            "assignments": [
                {
                    "id": a.id,
                    "title": a.title,
                    "max_points": a.max_points,
                    "weight": a.weight,
                    "due_at": a.due_at,
                    "is_visible": is_visible_to_students(a, now),
                }
                for a in assignments
            ],
            "rows": rows,
        }

    # -- grading queue ---------------------------------------------------
    def queue(self, user: User) -> list[dict]:
        staff_courses = (
            list(self.db.scalars(select(Course.id)))
            if user.role == "admin"
            else list(
                self.db.scalars(
                    select(Enrollment.course_id).where(
                        Enrollment.user_id == user.id,
                        Enrollment.role_in_course.in_(STAFF_ROLES),
                    )
                )
            )
        )
        if not staff_courses:
            return []
        assignments = list(
            self.db.scalars(
                select(Assignment).where(
                    Assignment.course_id.in_(staff_courses), Assignment.archived_at.is_(None)
                )
            )
        )
        if not assignments:
            return []
        courses = {
            c.id: c for c in self.db.scalars(select(Course).where(Course.id.in_(staff_courses)))
        }
        latest = _latest_by_pair(
            self.db.scalars(
                select(Submission).where(Submission.assignment_id.in_([a.id for a in assignments]))
            )
        )
        counts: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: {"ungraded": 0, "drafts": 0, "late": 0})
        for (assignment_id, _), s in latest.items():
            if s.status == "submitted":
                counts[assignment_id]["ungraded"] += 1
                if s.is_late:
                    counts[assignment_id]["late"] += 1
            elif s.status == "graded":
                counts[assignment_id]["drafts"] += 1
        out = []
        for a in assignments:
            c = counts.get(a.id)
            if not c or (c["ungraded"] == 0 and c["drafts"] == 0):
                continue
            course = courses.get(a.course_id)
            out.append(
                {
                    "assignment_id": a.id,
                    "assignment_title": a.title,
                    "course_id": a.course_id,
                    "course_code": course.code if course else "",
                    "due_at": a.due_at,
                    **c,
                }
            )
        out.sort(key=lambda r: (-(r["ungraded"] + r["drafts"]), r["assignment_title"]))
        return out

    # -- student home ----------------------------------------------------
    def home(self, user: User) -> dict:
        course_rows = self.db.execute(
            select(Course)
            .join(Enrollment, Enrollment.course_id == Course.id)
            .where(Enrollment.user_id == user.id, Enrollment.role_in_course == "student")
            .order_by(Course.created_at)
        ).scalars().all()
        course_ids = [c.id for c in course_rows]
        courses = {c.id: c for c in course_rows}
        if not course_ids:
            return {"courses": [], "due_soon": [], "posts": [], "feedback": []}
        now = now_utc()
        assignments = [
            a
            for a in self.db.scalars(
                select(Assignment).where(
                    Assignment.course_id.in_(course_ids), Assignment.archived_at.is_(None)
                )
            )
            if is_visible_to_students(a, now)
        ]
        mine = _latest_by_pair(
            self.db.scalars(
                select(Submission).where(
                    Submission.user_id == user.id,
                    Submission.assignment_id.in_([a.id for a in assignments]),
                )
            )
            if assignments
            else []
        )
        due_soon = []
        for a in assignments:
            if (a.id, user.id) in mine:
                continue
            due = ensure_utc(a.due_at)
            if due is not None and due < now and not a.allow_late:
                continue
            due_soon.append(
                {
                    "assignment_id": a.id,
                    "title": a.title,
                    "course_id": a.course_id,
                    "course_code": courses[a.course_id].code,
                    "due_at": a.due_at,
                    "is_overdue": bool(due is not None and due < now),
                }
            )
        due_soon.sort(key=lambda r: (r["due_at"] is None, ensure_utc(r["due_at"]) or now))

        posts = list(
            self.db.scalars(
                select(CoursePost)
                .where(
                    CoursePost.course_id.in_(course_ids),
                    CoursePost.deleted_at.is_(None),
                    CoursePost.status == "published",
                    or_(CoursePost.publish_at.is_(None), CoursePost.publish_at <= now),
                )
                .order_by(func.coalesce(CoursePost.publish_at, CoursePost.created_at).desc())
                .limit(8)
            )
        )
        read = set(
            self.db.scalars(
                select(PostRead.post_id).where(
                    PostRead.user_id == user.id, PostRead.post_id.in_([p.id for p in posts])
                )
            )
        ) if posts else set()

        feedback_rows = self.db.execute(
            select(SubmissionGrade, Submission, Assignment)
            .join(Submission, Submission.id == SubmissionGrade.submission_id)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(Submission.user_id == user.id, SubmissionGrade.released_at.is_not(None))
            .order_by(SubmissionGrade.released_at.desc())
            .limit(5)
        ).all()
        return {
            "courses": [
                {"id": c.id, "code": c.code, "name": c.name, "status": c.status} for c in course_rows
            ],
            "due_soon": due_soon[:10],
            "posts": [
                {
                    "id": p.id,
                    "course_id": p.course_id,
                    "course_code": courses[p.course_id].code,
                    "kind": p.kind,
                    "title": p.title,
                    "excerpt": p.body[:240],
                    "is_read": p.id in read,
                    "published_at": p.publish_at or p.created_at,
                }
                for p in posts
            ],
            "feedback": [
                {
                    "submission_id": s.id,
                    "assignment_id": a.id,
                    "assignment_title": a.title,
                    "course_id": a.course_id,
                    "final_score": s.final_score,
                    "max_points": a.max_points,
                    "released_at": g.released_at,
                    "has_comments": bool(g.feedback.strip()),
                }
                for g, s, a in feedback_rows
            ],
        }
