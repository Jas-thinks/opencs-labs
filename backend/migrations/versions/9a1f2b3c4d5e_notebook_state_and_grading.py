"""notebook snapshots, manual grading and analytics

Revision ID: 9a1f2b3c4d5e
Revises: f443308c6e53
Create Date: 2026-11-17 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "9a1f2b3c4d5e"
down_revision = "f443308c6e53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- notebook snapshot storage --------------------------------------
    op.create_table(
        "notebook_blobs",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("encoding", sa.String(length=16), nullable=False, server_default="gzip+json"),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.Column("storage_kind", sa.String(length=16), nullable=False, server_default="db"),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("sha256"),
    )

    op.add_column("notebooks", sa.Column("edit_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("notebooks", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    op.add_column("notebooks", sa.Column("current_version_id", sa.Uuid(), nullable=True))
    op.add_column("notebooks", sa.Column("last_saved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notebooks", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_notebooks_current_version_id", "notebooks", ["current_version_id"])

    op.create_table(
        "notebook_versions",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("blob_sha256", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["blob_sha256"], ["notebook_blobs.sha256"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notebook_id", "version_number", name="uq_notebook_version_number"),
    )
    op.create_index("ix_notebook_versions_notebook_id", "notebook_versions", ["notebook_id"])
    op.create_index("ix_notebook_versions_notebook_version", "notebook_versions", ["notebook_id", "version_number"])
    op.create_index("ix_notebook_versions_kind", "notebook_versions", ["kind"])

    op.create_table(
        "notebook_sessions",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client", sa.String(length=20), nullable=False, server_default="jupyterlab"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notebook_sessions_notebook_id", "notebook_sessions", ["notebook_id"])
    op.create_index("ix_notebook_sessions_user_id", "notebook_sessions", ["user_id"])
    op.create_index("ix_notebook_sessions_user_started", "notebook_sessions", ["user_id", "started_at"])
    op.create_index("ix_notebook_sessions_notebook_seen", "notebook_sessions", ["notebook_id", "last_seen_at"])

    # --- course work ------------------------------------------------------
    op.create_table(
        "assignments",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("exercise_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="practice"),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_points", sa.Float(), nullable=False, server_default="100"),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("allow_late", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("late_penalty_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["exercises.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "slug", name="uq_assignment_course_slug"),
    )
    op.create_index("ix_assignments_course_id", "assignments", ["course_id"])
    op.create_index("ix_assignments_exercise_id", "assignments", ["exercise_id"])
    op.create_index("ix_assignments_course_published", "assignments", ["course_id", "is_published"])

    op.create_table(
        "rubrics",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("total_points", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id"),
    )

    op.create_table(
        "rubric_criteria",
        sa.Column("rubric_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False, server_default=""),
        sa.Column("max_points", sa.Float(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["rubric_id"], ["rubrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rubric_id", "key", name="uq_rubric_criterion_key"),
    )
    op.create_index("ix_rubric_criteria_rubric_id", "rubric_criteria", ["rubric_id"])

    op.create_table(
        "submissions",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("notebook_version_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="submitted"),
        sa.Column("is_late", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_score", sa.Float(), nullable=True),
        sa.Column("final_score", sa.Float(), nullable=True),
        sa.Column("score_source", sa.String(length=16), nullable=False, server_default="none"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"]),
        sa.ForeignKeyConstraint(["notebook_version_id"], ["notebook_versions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "user_id", "attempt_number", name="uq_submission_attempt"),
    )
    op.create_index("ix_submissions_assignment_id", "submissions", ["assignment_id"])
    op.create_index("ix_submissions_user_id", "submissions", ["user_id"])
    op.create_index("ix_submissions_notebook_id", "submissions", ["notebook_id"])
    op.create_index("ix_submissions_assignment_user", "submissions", ["assignment_id", "user_id"])
    op.create_index("ix_submissions_assignment_status", "submissions", ["assignment_id", "status"])
    op.create_index("ix_submissions_user_submitted", "submissions", ["user_id", "submitted_at"])

    op.create_table(
        "submission_grades",
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rubric_id", sa.Uuid(), nullable=False),
        sa.Column("total_points", sa.Float(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("graded_by", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["graded_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["rubric_id"], ["rubrics.id"]),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", "revision", name="uq_submission_grade_revision"),
    )
    op.create_index("ix_submission_grades_submission_id", "submission_grades", ["submission_id"])
    op.create_index("ix_submission_grades_submission_revision", "submission_grades", ["submission_id", "revision"])

    op.create_table(
        "grade_criterion_scores",
        sa.Column("submission_grade_id", sa.Uuid(), nullable=False),
        sa.Column("criterion_id", sa.Uuid(), nullable=False),
        sa.Column("points", sa.Float(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["criterion_id"], ["rubric_criteria.id"]),
        sa.ForeignKeyConstraint(["submission_grade_id"], ["submission_grades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_grade_id", "criterion_id", name="uq_grade_criterion"),
    )
    op.create_index("ix_grade_criterion_scores_submission_grade_id", "grade_criterion_scores", ["submission_grade_id"])
    op.create_index("ix_grade_criterion_scores_criterion", "grade_criterion_scores", ["criterion_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_run_at", "jobs", ["run_at"])

    # --- attach automated attempts to course work -----------------------
    op.add_column("practice_attempts", sa.Column("assignment_id", sa.Uuid(), nullable=True))
    op.create_index("ix_practice_attempts_assignment_id", "practice_attempts", ["assignment_id"])
    with op.batch_alter_table("practice_attempts") as batch:
        batch.create_foreign_key(
            "fk_practice_attempts_assignment",
            "assignments",
            ["assignment_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # --- reporting views -------------------------------------------------
    op.execute(
        """
        CREATE VIEW v_latest_submission AS
        SELECT s.id, s.assignment_id, s.user_id, s.notebook_id,
               s.notebook_version_id, s.attempt_number, s.status, s.is_late,
               s.auto_score, s.final_score, s.score_source,
               s.submitted_at, s.graded_at
        FROM submissions s
        JOIN (
            SELECT assignment_id, user_id, MAX(attempt_number) AS max_attempt
            FROM submissions
            GROUP BY assignment_id, user_id
        ) m
          ON m.assignment_id = s.assignment_id
         AND m.user_id = s.user_id
         AND m.max_attempt = s.attempt_number
        """
    )
    op.execute(
        """
        CREATE VIEW v_latest_grade AS
        SELECT g.id, g.submission_id, g.revision, g.rubric_id,
               g.total_points, g.feedback, g.graded_by, g.published_at
        FROM submission_grades g
        JOIN (
            SELECT submission_id, MAX(revision) AS max_revision
            FROM submission_grades
            GROUP BY submission_id
        ) m
          ON m.submission_id = g.submission_id
         AND m.max_revision = g.revision
        """
    )
    op.execute(
        """
        CREATE VIEW v_student_assignment AS
        SELECT a.id AS assignment_id, a.course_id, e.user_id,
               ls.id AS submission_id, ls.attempt_number, ls.status,
               ls.is_late, ls.final_score, ls.submitted_at, ls.graded_at,
               lg.published_at
        FROM assignments a
        JOIN enrollments e
          ON e.course_id = a.course_id
         AND e.role_in_course = 'student'
        LEFT JOIN v_latest_submission ls
          ON ls.assignment_id = a.id
         AND ls.user_id = e.user_id
        LEFT JOIN v_latest_grade lg
          ON lg.submission_id = ls.id
        """
    )
    op.execute(
        """
        CREATE VIEW v_criterion_mastery AS
        SELECT s.user_id, sg.rubric_id, rc.id AS criterion_id,
               rc.key, rc.label, rc.max_points,
               gcs.points, gcs.submission_grade_id, sg.submission_id
        FROM grade_criterion_scores gcs
        JOIN submission_grades sg
          ON sg.id = gcs.submission_grade_id
        JOIN submissions s
          ON s.id = sg.submission_id
        JOIN v_latest_grade lg
          ON lg.submission_id = sg.submission_id
         AND lg.revision = sg.revision
        JOIN rubric_criteria rc
          ON rc.id = gcs.criterion_id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_criterion_mastery")
    op.execute("DROP VIEW IF EXISTS v_student_assignment")
    op.execute("DROP VIEW IF EXISTS v_latest_grade")
    op.execute("DROP VIEW IF EXISTS v_latest_submission")

    with op.batch_alter_table("practice_attempts") as batch:
        batch.drop_constraint("fk_practice_attempts_assignment", type_="foreignkey")
    op.drop_index("ix_practice_attempts_assignment_id", table_name="practice_attempts")
    op.drop_column("practice_attempts", "assignment_id")

    op.drop_index("ix_jobs_run_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_kind", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_grade_criterion_scores_criterion", table_name="grade_criterion_scores")
    op.drop_index("ix_grade_criterion_scores_submission_grade_id", table_name="grade_criterion_scores")
    op.drop_table("grade_criterion_scores")

    op.drop_index("ix_submission_grades_submission_revision", table_name="submission_grades")
    op.drop_index("ix_submission_grades_submission_id", table_name="submission_grades")
    op.drop_table("submission_grades")

    op.drop_index("ix_submissions_user_submitted", table_name="submissions")
    op.drop_index("ix_submissions_assignment_status", table_name="submissions")
    op.drop_index("ix_submissions_assignment_user", table_name="submissions")
    op.drop_index("ix_submissions_notebook_id", table_name="submissions")
    op.drop_index("ix_submissions_user_id", table_name="submissions")
    op.drop_index("ix_submissions_assignment_id", table_name="submissions")
    op.drop_table("submissions")

    op.drop_index("ix_rubric_criteria_rubric_id", table_name="rubric_criteria")
    op.drop_table("rubric_criteria")
    op.drop_table("rubrics")

    op.drop_index("ix_assignments_course_published", table_name="assignments")
    op.drop_index("ix_assignments_exercise_id", table_name="assignments")
    op.drop_index("ix_assignments_course_id", table_name="assignments")
    op.drop_table("assignments")

    op.drop_index("ix_notebook_sessions_notebook_seen", table_name="notebook_sessions")
    op.drop_index("ix_notebook_sessions_user_started", table_name="notebook_sessions")
    op.drop_index("ix_notebook_sessions_user_id", table_name="notebook_sessions")
    op.drop_index("ix_notebook_sessions_notebook_id", table_name="notebook_sessions")
    op.drop_table("notebook_sessions")

    op.drop_index("ix_notebook_versions_kind", table_name="notebook_versions")
    op.drop_index("ix_notebook_versions_notebook_version", table_name="notebook_versions")
    op.drop_index("ix_notebook_versions_notebook_id", table_name="notebook_versions")
    op.drop_table("notebook_versions")

    op.drop_index("ix_notebooks_current_version_id", table_name="notebooks")
    op.drop_column("notebooks", "last_activity_at")
    op.drop_column("notebooks", "last_saved_at")
    op.drop_column("notebooks", "current_version_id")
    op.drop_column("notebooks", "content_sha256")
    op.drop_column("notebooks", "edit_version")

    op.drop_table("notebook_blobs")
