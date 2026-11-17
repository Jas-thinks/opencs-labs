"""Single import point for all ORM models (used by Alembic and tests)."""

from app.core.jobs import Job  # noqa: F401
from app.courses.models import Course, Enrollment  # noqa: F401
from app.datasets.models import Dataset, DatasetVersion  # noqa: F401
from app.grading.models import (  # noqa: F401
    Assignment,
    GradeCriterionScore,
    Rubric,
    RubricCriterion,
    Submission,
    SubmissionGrade,
)
from app.learning.models import LearningPath, Lesson, LessonProgress, Module  # noqa: F401
from app.notebooks.models import (  # noqa: F401
    Notebook,
    NotebookBlob,
    NotebookSession,
    NotebookVersion,
)
from app.practice.models import Exercise, PracticeAttempt  # noqa: F401
from app.users.models import User  # noqa: F401

__all__ = [
    "Assignment",
    "Course",
    "Dataset",
    "DatasetVersion",
    "Enrollment",
    "Exercise",
    "GradeCriterionScore",
    "Job",
    "LearningPath",
    "Lesson",
    "LessonProgress",
    "Module",
    "Notebook",
    "NotebookBlob",
    "NotebookSession",
    "NotebookVersion",
    "PracticeAttempt",
    "Rubric",
    "RubricCriterion",
    "Submission",
    "SubmissionGrade",
    "User",
]
