"""Practice catalogue, attempts and isolated evaluation."""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.errors import Conflict, NotFound
from app.datasets.models import Dataset
from app.integrations.grader import NotebookGrader, result_to_feedback
from app.notebooks.ipynb import cells_from_sources, markdown_cell
from app.notebooks.models import Notebook
from app.notebooks.service import NotebookService
from app.practice.models import Exercise, PracticeAttempt
from app.users.models import User

logger = logging.getLogger("opencs.practice")


class PracticeService:
    def __init__(
        self,
        db: Session,
        notebook_service: NotebookService | None = None,
        grader: NotebookGrader | None = None,
    ) -> None:
        self.db = db
        self.notebook_service = notebook_service or NotebookService(db)
        self.grader = grader or NotebookGrader()

    # -- catalogue -------------------------------------------------------
    def _attempt_stats(self, user: User) -> dict[str, dict]:
        rows = self.db.execute(
            select(
                PracticeAttempt.exercise_id,
                func.count(PracticeAttempt.id),
                func.max(PracticeAttempt.status),
            )
            .where(PracticeAttempt.user_id == user.id)
            .group_by(PracticeAttempt.exercise_id)
        ).all()
        passed_ids = set(
            self.db.scalars(
                select(PracticeAttempt.exercise_id).where(
                    PracticeAttempt.user_id == user.id,
                    PracticeAttempt.status == "passed",
                )
            )
        )
        return {
            str(exercise_id): {"attempts": count, "completed": exercise_id in passed_ids}
            for exercise_id, count, _ in rows
        }

    def list(
        self,
        user: User,
        *,
        topic: str | None = None,
        difficulty: str | None = None,
        q: str | None = None,
        limit: int = 24,
        offset: int = 0,
    ) -> tuple[list[Exercise], int]:
        stmt = select(Exercise).where(Exercise.is_published.is_(True))
        if topic:
            stmt = stmt.where(Exercise.topic == topic)
        if difficulty:
            stmt = stmt.where(Exercise.difficulty == difficulty)
        if q:
            needle = f"%{q.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Exercise.title).like(needle),
                    func.lower(Exercise.objective).like(needle),
                    func.lower(Exercise.topic).like(needle),
                )
            )
        rows = list(self.db.scalars(stmt.order_by(Exercise.position, Exercise.title)))
        return rows[offset : offset + limit], len(rows)

    def topics(self) -> list[dict]:
        rows = self.db.execute(
            select(Exercise.topic, func.count(Exercise.id))
            .where(Exercise.is_published.is_(True))
            .group_by(Exercise.topic)
            .order_by(Exercise.topic)
        ).all()
        return [{"topic": topic, "count": count} for topic, count in rows]

    def get_exercise(self, slug: str) -> Exercise:
        exercise = self.db.scalar(
            select(Exercise).where(Exercise.slug == slug, Exercise.is_published.is_(True))
        )
        if exercise is None:
            raise NotFound("exercise", slug)
        return exercise

    def _dataset_refs(self, slugs: list[str]) -> list[dict]:
        if not slugs:
            return []
        rows = self.db.scalars(
            select(Dataset)
            .where(Dataset.slug.in_(slugs), Dataset.is_published.is_(True))
            .options(selectinload(Dataset.versions))
        )
        by_slug = {row.slug: row for row in rows}
        refs = []
        for slug in slugs:
            dataset = by_slug.get(slug)
            if not dataset:
                continue
            version = dataset.current_version
            refs.append(
                {
                    "slug": dataset.slug,
                    "title": dataset.title,
                    "summary": dataset.summary,
                    "category": dataset.category,
                    "format": version.format if version else None,
                    "row_count": version.row_count if version else None,
                }
            )
        return refs

    def detail(self, user: User, slug: str) -> dict:
        exercise = self.get_exercise(slug)
        stats = self._attempt_stats(user).get(str(exercise.id), {"attempts": 0, "completed": False})
        return {
            "id": exercise.id,
            "slug": exercise.slug,
            "title": exercise.title,
            "topic": exercise.topic,
            "difficulty": exercise.difficulty,
            "objective": exercise.objective,
            "instructions": exercise.instructions,
            "hints": [
                {"index": index + 1, "text": text}
                for index, text in enumerate(exercise.hints or [])
            ],
            "dataset_slugs": exercise.dataset_slugs or [],
            "datasets": self._dataset_refs(exercise.dataset_slugs or []),
            "has_automated_checks": bool(exercise.evaluation and exercise.evaluation.get("tests")),
            "related_lesson_slug": exercise.related_lesson_slug,
            "estimated_minutes": exercise.estimated_minutes,
            "completed": stats["completed"],
            "attempts": stats["attempts"],
        }

    # -- attempts --------------------------------------------------------
    def _owned_attempt(self, user: User, attempt_id: str) -> PracticeAttempt:
        try:
            attempt_uuid = uuid.UUID(str(attempt_id))
        except ValueError as exc:
            raise NotFound("attempt", str(attempt_id)) from exc
        attempt = self.db.get(PracticeAttempt, attempt_uuid)
        if attempt is None or attempt.user_id != user.id:
            raise NotFound("attempt")
        return attempt

    def _attempt_out(self, attempt: PracticeAttempt) -> dict:
        notebook = self.db.get(Notebook, attempt.notebook_id) if attempt.notebook_id else None
        return {
            "id": attempt.id,
            "exercise_id": attempt.exercise_id,
            "exercise_slug": attempt.exercise.slug,
            "attempt_number": attempt.attempt_number,
            "status": attempt.status,
            "score": attempt.score,
            "started_at": attempt.started_at,
            "submitted_at": attempt.submitted_at,
            "completed_at": attempt.completed_at,
            "feedback": attempt.feedback or {},
            "notebook": notebook,
        }

    def get_attempt(self, user: User, attempt_id: str) -> dict:
        return self._attempt_out(self._owned_attempt(user, attempt_id))

    def create_attempt(self, user: User, slug: str) -> tuple[dict, Notebook, str, list[dict]]:
        exercise = self.get_exercise(slug)
        previous = self.db.scalar(
            select(func.max(PracticeAttempt.attempt_number)).where(
                PracticeAttempt.user_id == user.id,
                PracticeAttempt.exercise_id == exercise.id,
            )
        )
        attempt_number = int(previous or 0) + 1

        template = exercise.starter_notebook or {}
        cells = []
        intro = template.get("intro_markdown") or (
            f"# {exercise.title}\n\n**Objective:** {exercise.objective}\n\n"
            f"Difficulty: {exercise.difficulty} · Topic: {exercise.topic}"
        )
        cells.append(markdown_cell(intro))
        for item in template.get("cells", []):
            if isinstance(item, str):
                cells.extend(
                    cells_from_sources([item], metadata={"opencs_exercise": exercise.slug})
                )
            elif isinstance(item, dict) and item.get("cell_type") == "markdown":
                cells.append(markdown_cell(item.get("source", "")))
            elif isinstance(item, dict) and item.get("source"):
                from app.notebooks.ipynb import code_cell

                cells.append(
                    code_cell(item["source"], metadata={"opencs_exercise": exercise.slug})
                )
        if template.get("outro_markdown"):
            cells.append(markdown_cell(template["outro_markdown"]))

        dataset_versions = {}
        if exercise.dataset_slugs:
            rows = self.db.scalars(
                select(Dataset)
                .where(Dataset.slug.in_(exercise.dataset_slugs), Dataset.is_published.is_(True))
                .options(selectinload(Dataset.versions))
            )
            for dataset in rows:
                current = dataset.current_version
                if current:
                    dataset_versions[dataset.slug] = current.version

        notebook_row = self.notebook_service.create(
            user,
            title=f"{exercise.title} — Practice {attempt_number}",
            kind="practice",
            source_ref=exercise.slug,
            cells=cells,
            metadata={
                "exercise": exercise.slug,
                "exercise_version": exercise.version,
                "attempt_number": attempt_number,
                "datasets": dataset_versions,
                "environment_image": settings.environment_image,
            },
        )
        url = self.notebook_service.backend.open_url(user, notebook_row.file_name)

        attempt = PracticeAttempt(
            user_id=user.id,
            exercise_id=exercise.id,
            notebook_id=notebook_row.id,
            attempt_number=attempt_number,
            status="in_progress",
            started_at=dt.datetime.now(dt.UTC),
        )
        self.db.add(attempt)
        self.db.commit()
        self.db.refresh(attempt)

        hints = [
            {"index": index + 1, "text": text}
            for index, text in enumerate(exercise.hints or [])
        ]
        return self._attempt_out(attempt), notebook_row, url, hints

    def evaluate(self, user: User, attempt_id: str) -> dict:
        attempt = self._owned_attempt(user, attempt_id)
        exercise = attempt.exercise
        evaluation = exercise.evaluation or {}
        if not evaluation.get("tests"):
            raise Conflict(
                "NO_AUTOMATED_CHECKS",
                "This exercise is assessed by your instructor; there are no automated checks.",
            )
        if not attempt.notebook_id:
            raise Conflict("NO_NOTEBOOK", "This attempt has no associated notebook")
        notebook_row = self.db.get(Notebook, attempt.notebook_id)
        if notebook_row is None or notebook_row.user_id != user.id:
            raise Conflict("NO_NOTEBOOK", "This attempt has no associated notebook")

        self.notebook_service.ensure_server_ready(user)
        notebook = self.notebook_service.read_for_grading(user, notebook_row)
        result = self.grader.evaluate(notebook, evaluation)

        now = dt.datetime.now(dt.UTC)
        attempt.status = "passed" if result.passed else "failed"
        attempt.score = round(result.score, 3)
        attempt.feedback = result_to_feedback(result, attempt.attempt_number)
        attempt.submitted_at = now
        if result.passed:
            attempt.completed_at = now
        self.db.commit()
        self.db.refresh(attempt)
        return self._attempt_out(attempt)

    def feedback(self, user: User, attempt_id: str) -> dict:
        attempt = self._owned_attempt(user, attempt_id)
        feedback = attempt.feedback or {}
        return {
            "attempt_id": attempt.id,
            "status": attempt.status,
            "passed": attempt.status == "passed",
            "score": attempt.score,
            "tests": feedback.get("tests", []),
            "message": feedback.get("error"),
            "evaluated_at": feedback.get("evaluated_at"),
        }

    def progress(self, user: User) -> dict:
        exercises = self.db.execute(
            select(Exercise.id, Exercise.topic).where(Exercise.is_published.is_(True))
        ).all()
        attempt_counts = dict(
            self.db.execute(
                select(PracticeAttempt.exercise_id, func.count(PracticeAttempt.id))
                .where(PracticeAttempt.user_id == user.id)
                .group_by(PracticeAttempt.exercise_id)
            ).all()
        )
        passed = set(
            self.db.scalars(
                select(PracticeAttempt.exercise_id).where(
                    PracticeAttempt.user_id == user.id, PracticeAttempt.status == "passed"
                )
            )
        )
        by_topic: dict[str, dict[str, int]] = {}
        for exercise_id, topic in exercises:
            entry = by_topic.setdefault(topic, {"attempts": 0, "completed": 0, "exercises": 0})
            entry["exercises"] += 1
            entry["attempts"] += int(attempt_counts.get(exercise_id, 0))
            if exercise_id in passed:
                entry["completed"] += 1
        return {
            "topics": [
                {"topic": topic, **values} for topic, values in sorted(by_topic.items())
            ],
            "total_exercises": len(exercises),
            "completed_exercises": len(passed),
        }
