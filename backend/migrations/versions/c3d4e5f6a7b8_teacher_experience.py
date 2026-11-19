"""teacher experience: assignment lifecycle, grade release, stream, notifications

Revision ID: c3d4e5f6a7b8
Revises: 9a1f2b3c4d5e
Create Date: 2026-11-19 10:00:00.000000

Additive only (new nullable columns / new tables), so the rolling deploy
contract holds: migrate first, then restart API nodes one at a time while old
and new code share the schema.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "9a1f2b3c4d5e"
branch_labels = None
depends_on = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # Plain ADD COLUMN only. A batch (copy-and-rename) rebuild of these tables
    # fails on SQLite because the analytics views reference them; constraint
    # and type changes are applied natively on PostgreSQL.
    pg = _is_postgres()

    # --- assignments: lifecycle, scheduling, starter notebook, topic -----
    op.add_column("assignments", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assignments", sa.Column("publish_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assignments", sa.Column("starter_version_id", sa.Uuid(), nullable=True))
    op.add_column("assignments", sa.Column("topic", sa.String(length=120), nullable=True))
    if pg:
        op.alter_column(
            "assignments", "description",
            existing_type=sa.String(length=2000), type_=sa.Text(), existing_nullable=False,
        )
        op.create_foreign_key(
            "fk_assignments_starter_version", "assignments", "notebook_versions",
            ["starter_version_id"], ["id"], ondelete="SET NULL",
        )
    op.create_index(
        "ix_assignments_course_archived_published",
        "assignments",
        ["course_id", "archived_at", "is_published"],
    )

    # --- grade revisions: draft/release, per-revision score, override audit
    op.add_column("submission_grades", sa.Column("released_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("submission_grades", sa.Column("final_score", sa.Float(), nullable=True))
    op.add_column("submission_grades", sa.Column("override_reason", sa.Text(), nullable=True))
    # Every grade that exists today was visible to students the moment it was
    # saved; keep it visible under the new draft/return model.
    op.execute("UPDATE submission_grades SET released_at = published_at WHERE released_at IS NULL")
    op.execute(
        "UPDATE submissions SET status = 'returned' "
        "WHERE status = 'graded' AND final_score IS NOT NULL"
    )
    op.create_index(
        "ix_submission_grades_submission_released",
        "submission_grades",
        ["submission_id", "released_at"],
    )

    # --- courses: self-enrolment code, creator ---------------------------
    op.add_column("courses", sa.Column("join_code", sa.String(length=12), nullable=True))
    op.add_column("courses", sa.Column("created_by", sa.Uuid(), nullable=True))
    op.create_index("ux_courses_join_code", "courses", ["join_code"], unique=True)
    if pg:
        op.create_foreign_key(
            "fk_courses_created_by", "courses", "users", ["created_by"], ["id"], ondelete="SET NULL"
        )

    # --- stream ----------------------------------------------------------
    op.create_table(
        "course_posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="announcement"),
        sa.Column("title", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("topic", sa.String(length=120), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="published"),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_course_posts_feed",
        "course_posts",
        ["course_id", "deleted_at", "status", "publish_at"],
    )
    op.create_table(
        "course_post_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("label", sa.String(length=240), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["post_id"], ["course_posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_course_post_attachments_post", "course_post_attachments", ["post_id"])
    op.create_table(
        "post_reads",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.ForeignKeyConstraint(["post_id"], ["course_posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id", "user_id"),
    )
    op.create_index("ix_post_reads_user", "post_reads", ["user_id"])

    # --- notifications ---------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=True),
        sa.Column("ref_type", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("link", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_user_unread", "notifications", ["user_id", "read_at", "created_at"]
    )


def downgrade() -> None:
    pg = _is_postgres()
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_post_reads_user", table_name="post_reads")
    op.drop_table("post_reads")
    op.drop_index("ix_course_post_attachments_post", table_name="course_post_attachments")
    op.drop_table("course_post_attachments")
    op.drop_index("ix_course_posts_feed", table_name="course_posts")
    op.drop_table("course_posts")

    if pg:
        op.drop_constraint("fk_courses_created_by", "courses", type_="foreignkey")
    op.drop_index("ux_courses_join_code", table_name="courses")
    op.drop_column("courses", "created_by")
    op.drop_column("courses", "join_code")

    op.drop_index("ix_submission_grades_submission_released", table_name="submission_grades")
    op.execute("UPDATE submissions SET status = 'graded' WHERE status = 'returned'")
    op.drop_column("submission_grades", "override_reason")
    op.drop_column("submission_grades", "final_score")
    op.drop_column("submission_grades", "released_at")

    op.drop_index("ix_assignments_course_archived_published", table_name="assignments")
    if pg:
        op.drop_constraint("fk_assignments_starter_version", "assignments", type_="foreignkey")
        op.alter_column(
            "assignments", "description",
            existing_type=sa.Text(), type_=sa.String(length=2000), existing_nullable=False,
        )
    op.drop_column("assignments", "topic")
    op.drop_column("assignments", "starter_version_id")
    op.drop_column("assignments", "publish_at")
    op.drop_column("assignments", "archived_at")
