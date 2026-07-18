"""add evaluation feedback reviews

Revision ID: 20260718_0024
Revises: 20260718_0023
Create Date: 2026-07-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260718_0024"
down_revision: Union[str, None] = "20260718_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_feedback_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("feedback_id", sa.Integer(), nullable=True),
        sa.Column("evaluation_case_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source_user_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("user_message_id", sa.Integer(), nullable=True),
        sa.Column("agent_role", sa.String(length=50), nullable=False),
        sa.Column("source_snapshot_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("resolution_note", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("reviewed_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('CONVERTED', 'DISMISSED')",
            name="ck_evaluation_feedback_review_status",
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["message_feedback.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_case_id"],
            ["evaluation_cases.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["user_message_id"],
            ["messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evaluation_feedback_reviews_id"),
        "evaluation_feedback_reviews",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_evaluation_feedback_reviews_request_id"),
        "evaluation_feedback_reviews",
        ["request_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_evaluation_feedback_reviews_feedback_id"),
        "evaluation_feedback_reviews",
        ["feedback_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_evaluation_feedback_reviews_evaluation_case_id"),
        "evaluation_feedback_reviews",
        ["evaluation_case_id"],
        unique=True,
    )
    for column in (
        "status",
        "source_user_id",
        "agent_id",
        "message_id",
        "agent_role",
    ):
        op.create_index(
            op.f(f"ix_evaluation_feedback_reviews_{column}"),
            "evaluation_feedback_reviews",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("evaluation_feedback_reviews")
