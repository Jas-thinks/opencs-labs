"""notebook (.ipynb) attachments on course posts

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-19 16:00:00.000000

Additive only (rolling-deploy safe).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("course_post_attachments", sa.Column("blob_sha256", sa.String(length=64), nullable=True))
    op.add_column("course_post_attachments", sa.Column("size_bytes", sa.Integer(), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_post_attachment_blob", "course_post_attachments", "notebook_blobs",
            ["blob_sha256"], ["sha256"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("fk_post_attachment_blob", "course_post_attachments", type_="foreignkey")
    op.drop_column("course_post_attachments", "size_bytes")
    op.drop_column("course_post_attachments", "blob_sha256")
