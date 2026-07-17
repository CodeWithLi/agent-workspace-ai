"""add asynchronous knowledge indexing fields

Revision ID: 20260717_0007
Revises: 20260717_0006
Create Date: 2026-07-17 14:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0007"
down_revision: Union[str, None] = "20260717_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("content_hash", sa.String(length=64), server_default="", nullable=False))
        batch_op.add_column(sa.Column("dedup_key", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("source_label", sa.String(length=100), server_default="upload", nullable=False))
        batch_op.add_column(sa.Column("metadata_json", sa.Text(), server_default="{}", nullable=False))
        batch_op.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False))
        batch_op.add_column(sa.Column("error", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))
        batch_op.create_index(batch_op.f("ix_documents_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_documents_content_hash"), ["content_hash"], unique=False)
        batch_op.create_index(batch_op.f("ix_documents_dedup_key"), ["dedup_key"], unique=True)
        batch_op.create_index(batch_op.f("ix_documents_locked_at"), ["locked_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        for index in ("locked_at", "dedup_key", "content_hash", "status"):
            batch_op.drop_index(batch_op.f(f"ix_documents_{index}"))
        for column in (
            "updated_at",
            "indexed_at",
            "locked_at",
            "error",
            "max_attempts",
            "attempts",
            "version",
            "metadata_json",
            "source_label",
            "dedup_key",
            "content_hash",
        ):
            batch_op.drop_column(column)
