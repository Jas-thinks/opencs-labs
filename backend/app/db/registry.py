"""Single import point for all ORM models (used by Alembic)."""

from app.courses.models import Course, Enrollment  # noqa: F401
from app.datasets.models import Dataset, DatasetVersion  # noqa: F401
from app.learning.models import LearningPath, Lesson, LessonProgress, Module  # noqa: F401
from app.notebooks.models import Notebook  # noqa: F401
from app.practice.models import Exercise, PracticeAttempt  # noqa: F401
from app.users.models import User  # noqa: F401

__all__ = [
    "Course",
    "Dataset",
    "DatasetVersion",
    "Enrollment",
    "Exercise",
    "LearningPath",
    "Lesson",
    "LessonProgress",
    "Module",
    "Notebook",
    "PracticeAttempt",
    "User",
]
