"""Learning content queries and progress tracking."""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.errors import Conflict, NotFound
from app.datasets.models import Dataset
from app.learning.models import LearningPath, Lesson, LessonProgress, Module
from app.notebooks.ipynb import cells_from_sources, markdown_cell
from app.notebooks.service import NotebookService
from app.practice.models import Exercise
from app.users.models import User

logger = logging.getLogger("opencs.learning")


class LearningService:
    def __init__(self, db: Session, notebook_service: NotebookService | None = None) -> None:
        self.db = db
        self.notebook_service = notebook_service or NotebookService(db)

    # -- read ------------------------------------------------------------
    def _progress_map(self, user: User) -> dict[str, LessonProgress]:
        rows = self.db.scalars(
            select(LessonProgress).where(LessonProgress.user_id == user.id)
        )
        return {str(row.lesson_id): row for row in rows}

    def paths(self, user: User) -> dict:
        paths = list(
            self.db.scalars(
                select(LearningPath)
                .where(LearningPath.is_published.is_(True))
                .options(selectinload(LearningPath.modules).selectinload(Module.lessons))
                .order_by(LearningPath.position)
            )
        )
        progress = self._progress_map(user)
        output = []
        total_lessons = 0
        total_completed = 0
        for path in paths:
            modules_out = []
            for module in sorted(path.modules, key=lambda m: m.position):
                if not module.is_published:
                    continue
                lessons = [lesson for lesson in sorted(module.lessons, key=lambda l: l.position) if lesson.is_published]
                completed = sum(
                    1
                    for lesson in lessons
                    if progress.get(str(lesson.id))
                    and progress[str(lesson.id)].status == "completed"
                )
                modules_out.append(
                    {
                        "slug": module.slug,
                        "title": module.title,
                        "description": module.description,
                        "position": module.position,
                        "lessons": [
                            {
                                "slug": lesson.slug,
                                "title": lesson.title,
                                "summary": lesson.summary,
                                "objective": lesson.objective,
                                "estimated_minutes": lesson.estimated_minutes,
                                "position": lesson.position,
                                "status": (
                                    progress[str(lesson.id)].status
                                    if progress.get(str(lesson.id))
                                    else "not_started"
                                ),
                                "dataset_slugs": lesson.dataset_slugs or [],
                                "exercise_slugs": lesson.exercise_slugs or [],
                                "has_notebook_activity": bool(lesson.notebook_activity),
                            }
                            for lesson in lessons
                        ],
                        "total_lessons": len(lessons),
                        "completed_lessons": completed,
                    }
                )
                total_lessons += len(lessons)
                total_completed += completed
            output.append(
                {
                    "slug": path.slug,
                    "title": path.title,
                    "description": path.description,
                    "modules": modules_out,
                    "total_lessons": sum(m["total_lessons"] for m in modules_out),
                    "completed_lessons": sum(m["completed_lessons"] for m in modules_out),
                    "progress_percent": _percent(
                        sum(m["completed_lessons"] for m in modules_out),
                        sum(m["total_lessons"] for m in modules_out),
                    ),
                }
            )
        return {
            "paths": output,
            "total_lessons": total_lessons,
            "completed_lessons": total_completed,
        }

    def _lesson_query(self):
        return (
            select(Lesson)
            .options(
                joinedload(Lesson.module).joinedload(Module.path),
            )
        )

    def get_lesson(self, slug: str, *, require_published: bool = True) -> Lesson:
        stmt = self._lesson_query().where(Lesson.slug == slug)
        if require_published:
            stmt = stmt.where(Lesson.is_published.is_(True))
        lesson = self.db.scalar(stmt)
        if lesson is None:
            raise NotFound("lesson", slug)
        return lesson

    def lesson_detail(self, user: User, slug: str) -> dict:
        lesson = self.get_lesson(slug)
        progress = self.db.scalar(
            select(LessonProgress).where(
                LessonProgress.user_id == user.id, LessonProgress.lesson_id == lesson.id
            )
        )

        datasets = []
        if lesson.dataset_slugs:
            rows = self.db.scalars(
                select(Dataset)
                .where(Dataset.slug.in_(lesson.dataset_slugs), Dataset.is_published.is_(True))
                .options(selectinload(Dataset.versions))
            )
            by_slug = {row.slug: row for row in rows}
            for dataset_slug in lesson.dataset_slugs:
                row = by_slug.get(dataset_slug)
                if not row:
                    continue
                version = row.current_version
                datasets.append(
                    {
                        "slug": row.slug,
                        "title": row.title,
                        "summary": row.summary,
                        "category": row.category,
                        "format": version.format if version else None,
                        "row_count": version.row_count if version else None,
                    }
                )

        exercises = []
        if lesson.exercise_slugs:
            rows = self.db.scalars(
                select(Exercise).where(
                    Exercise.slug.in_(lesson.exercise_slugs), Exercise.is_published.is_(True)
                )
            )
            by_slug = {row.slug: row for row in rows}
            for exercise_slug in lesson.exercise_slugs:
                row = by_slug.get(exercise_slug)
                if row:
                    exercises.append(
                        {
                            "slug": row.slug,
                            "title": row.title,
                            "topic": row.topic,
                            "difficulty": row.difficulty,
                        }
                    )

        previous_lesson, next_lesson = self._neighbours(lesson)
        return {
            "slug": lesson.slug,
            "title": lesson.title,
            "objective": lesson.objective,
            "summary": lesson.summary,
            "estimated_minutes": lesson.estimated_minutes,
            "content": lesson.content or {},
            "progress": {
                "status": progress.status if progress else "not_started",
                "last_section": progress.last_section if progress else None,
                "completed_at": progress.completed_at if progress else None,
            },
            "datasets": datasets,
            "exercises": exercises,
            "module": {"slug": lesson.module.slug, "title": lesson.module.title},
            "path": {"slug": lesson.module.path.slug, "title": lesson.module.path.title},
            "navigation": {
                "previous": previous_lesson.slug if previous_lesson else None,
                "next": next_lesson.slug if next_lesson else None,
            },
            "has_notebook_activity": bool(lesson.notebook_activity),
            "version": lesson.version,
        }

    def _neighbours(self, lesson: Lesson) -> tuple[Lesson | None, Lesson | None]:
        siblings = [
            item
            for item in sorted(lesson.module.lessons, key=lambda l: l.position)
            if item.is_published
        ]
        try:
            index = siblings.index(lesson)
        except ValueError:
            return None, None
        previous_lesson = siblings[index - 1] if index > 0 else None
        next_lesson = siblings[index + 1] if index + 1 < len(siblings) else None
        return previous_lesson, next_lesson

    # -- progress --------------------------------------------------------
    def update_progress(
        self, user: User, slug: str, status: str, last_section: str | None = None
    ) -> LessonProgress:
        lesson = self.get_lesson(slug)
        progress = self.db.scalar(
            select(LessonProgress).where(
                LessonProgress.user_id == user.id, LessonProgress.lesson_id == lesson.id
            )
        )
        now = dt.datetime.now(dt.UTC)
        if progress is None:
            progress = LessonProgress(
                user_id=user.id,
                lesson_id=lesson.id,
                status=status,
                last_section=last_section,
            )
            self.db.add(progress)
        else:
            # Completed is sticky: re-reading a lesson must not reset progress.
            if progress.status != "completed":
                progress.status = status
            if last_section:
                progress.last_section = last_section
        if status == "completed" and progress.completed_at is None:
            progress.completed_at = now
        self.db.commit()
        self.db.refresh(progress)
        return progress

    # -- notebook activity ------------------------------------------------
    def launch_activity(self, user: User, slug: str) -> tuple:
        lesson = self.get_lesson(slug)
        activity = lesson.notebook_activity
        if not activity:
            raise Conflict(
                "LESSON_HAS_NO_ACTIVITY",
                "This lesson does not have a notebook activity",
            )

        dataset_versions: dict[str, int] = {}
        if lesson.dataset_slugs:
            rows = self.db.scalars(
                select(Dataset)
                .where(Dataset.slug.in_(lesson.dataset_slugs), Dataset.is_published.is_(True))
                .options(selectinload(Dataset.versions))
            )
            for dataset in rows:
                current = dataset.current_version
                if current:
                    dataset_versions[dataset.slug] = current.version

        cells: list[dict] = []
        intro = activity.get("intro_markdown") or f"# {lesson.title}\n\n{lesson.objective}"
        cells.append(markdown_cell(intro))
        for item in activity.get("cells", []):
            if isinstance(item, str):
                cells.extend(cells_from_sources([item], metadata={"opencs_lesson": lesson.slug}))
            elif isinstance(item, dict) and item.get("cell_type") == "markdown":
                cells.append(markdown_cell(item.get("source", "")))
            elif isinstance(item, dict) and item.get("source"):
                from app.notebooks.ipynb import code_cell

                cells.append(
                    code_cell(item["source"], metadata={"opencs_lesson": lesson.slug})
                )
        if activity.get("outro_markdown"):
            cells.append(markdown_cell(activity["outro_markdown"]))

        notebook_row = self.notebook_service.create(
            user,
            title=activity.get("title") or f"{lesson.title} — Lesson Notebook",
            kind="lesson",
            source_ref=lesson.slug,
            cells=cells,
            metadata={
                "lesson": lesson.slug,
                "lesson_version": lesson.version,
                "datasets": dataset_versions,
                "environment_image": self._environment_image(),
            },
        )
        url = self.notebook_service.backend.open_url(user, notebook_row.file_name)
        self.update_progress(user, slug, "in_progress")
        return notebook_row, url

    @staticmethod
    def _environment_image() -> str:
        from app.core.config import settings

        return settings.environment_image


def _percent(completed: int, total: int) -> int:
    if total <= 0:
        return 0
    return round(completed / total * 100)
