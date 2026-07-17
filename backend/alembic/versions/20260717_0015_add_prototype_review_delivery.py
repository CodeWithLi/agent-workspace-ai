"""add prototype review and delivery evidence

Revision ID: 20260717_0015
Revises: 20260717_0014
Create Date: 2026-07-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0015"
down_revision: Union[str, None] = "20260717_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prototype_review_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prototype_id", sa.Integer(), nullable=False),
        sa.Column("prototype_version", sa.Integer(), nullable=False),
        sa.Column("screen_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="OPEN", nullable=False),
        sa.Column("resolved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["prototype_id"], ["product_prototypes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "prototype_id", "prototype_version", "screen_id", "user_id", "status", "resolved_by_user_id"):
        op.create_index(op.f(f"ix_prototype_review_comments_{column}"), "prototype_review_comments", [column], unique=False)

    op.create_table(
        "prototype_test_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prototype_id", sa.Integer(), nullable=False),
        sa.Column("prototype_version", sa.Integer(), nullable=False),
        sa.Column("screen_id", sa.String(length=64), nullable=False),
        sa.Column("case_key", sa.String(length=150), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("preconditions", sa.Text(), server_default="", nullable=False),
        sa.Column("steps_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=30), server_default="MEDIUM", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prototype_id"], ["product_prototypes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prototype_id", "prototype_version", "case_key", name="uq_prototype_test_case_key"),
    )
    for column in ("id", "prototype_id", "prototype_version", "screen_id", "created_by_user_id"):
        op.create_index(op.f(f"ix_prototype_test_cases_{column}"), "prototype_test_cases", [column], unique=False)

    op.create_table(
        "product_prototype_materializations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prototype_id", sa.Integer(), nullable=False),
        sa.Column("prototype_version", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("task_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("test_case_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prototype_id"], ["product_prototypes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prototype_id", "prototype_version", name="uq_product_prototype_materialization_version"),
    )
    for column in ("id", "prototype_id", "request_id", "created_by_user_id"):
        op.create_index(
            op.f(f"ix_product_prototype_materializations_{column}"),
            "product_prototype_materializations",
            [column],
            unique=column == "request_id",
        )

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("source_prototype_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_prototype_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_screen_id", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            "fk_tasks_source_prototype_id_product_prototypes",
            "product_prototypes",
            ["source_prototype_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            "uq_task_prototype_screen",
            ["project_id", "source_prototype_id", "source_prototype_version", "source_screen_id"],
        )
        batch_op.create_index(op.f("ix_tasks_source_prototype_id"), ["source_prototype_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index(op.f("ix_tasks_source_prototype_id"))
        batch_op.drop_constraint("uq_task_prototype_screen", type_="unique")
        batch_op.drop_constraint("fk_tasks_source_prototype_id_product_prototypes", type_="foreignkey")
        batch_op.drop_column("source_screen_id")
        batch_op.drop_column("source_prototype_version")
        batch_op.drop_column("source_prototype_id")

    for column in ("created_by_user_id", "request_id", "prototype_id", "id"):
        op.drop_index(
            op.f(f"ix_product_prototype_materializations_{column}"),
            table_name="product_prototype_materializations",
        )
    op.drop_table("product_prototype_materializations")

    for column in ("created_by_user_id", "screen_id", "prototype_version", "prototype_id", "id"):
        op.drop_index(op.f(f"ix_prototype_test_cases_{column}"), table_name="prototype_test_cases")
    op.drop_table("prototype_test_cases")

    for column in ("resolved_by_user_id", "status", "user_id", "screen_id", "prototype_version", "prototype_id", "id"):
        op.drop_index(op.f(f"ix_prototype_review_comments_{column}"), table_name="prototype_review_comments")
    op.drop_table("prototype_review_comments")
