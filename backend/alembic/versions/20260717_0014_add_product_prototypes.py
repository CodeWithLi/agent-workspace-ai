"""add AI product prototypes and immutable versions

Revision ID: 20260717_0014
Revises: 20260717_0013
Create Date: 2026-07-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0014"
down_revision: Union[str, None] = "20260717_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_prototypes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("requirement_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=30), server_default="DRAFT", nullable=False),
        sa.Column("active_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "project_id", "requirement_id", "created_by_user_id", "status"):
        op.create_index(op.f(f"ix_product_prototypes_{column}"), "product_prototypes", [column], unique=False)

    op.create_table(
        "product_prototype_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prototype_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_prompt", sa.Text(), nullable=False),
        sa.Column("specification_json", sa.Text(), nullable=False),
        sa.Column("agent_trace_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("quality_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("generation_mode", sa.String(length=30), server_default="MULTI_AGENT", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prototype_id"], ["product_prototypes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prototype_id", "version", name="uq_product_prototype_version"),
    )
    for column in ("id", "prototype_id", "created_by_user_id"):
        op.create_index(
            op.f(f"ix_product_prototype_versions_{column}"),
            "product_prototype_versions",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("created_by_user_id", "prototype_id", "id"):
        op.drop_index(
            op.f(f"ix_product_prototype_versions_{column}"),
            table_name="product_prototype_versions",
        )
    op.drop_table("product_prototype_versions")
    for column in ("status", "created_by_user_id", "requirement_id", "project_id", "id"):
        op.drop_index(op.f(f"ix_product_prototypes_{column}"), table_name="product_prototypes")
    op.drop_table("product_prototypes")
