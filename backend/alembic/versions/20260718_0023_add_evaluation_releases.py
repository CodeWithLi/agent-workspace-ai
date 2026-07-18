"""add evaluation-driven Agent releases

Revision ID: 20260718_0023
Revises: 20260718_0022
Create Date: 2026-07-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260718_0023"
down_revision: Union[str, None] = "20260718_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("evaluation_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("candidate_agent_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("candidate_version_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("candidate_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("expected_current_version", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_evaluation_runs_candidate_agent_id",
            "agents",
            ["candidate_agent_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_evaluation_runs_candidate_version_id",
            "agent_prompt_versions",
            ["candidate_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        op.f("ix_evaluation_runs_candidate_agent_id"),
        "evaluation_runs",
        ["candidate_agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_evaluation_runs_candidate_version_id"),
        "evaluation_runs",
        ["candidate_version_id"],
        unique=False,
    )

    op.create_table(
        "agent_evaluation_releases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("evaluation_run_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("candidate_version_id", sa.Integer(), nullable=True),
        sa.Column("candidate_version", sa.Integer(), nullable=False),
        sa.Column("previous_version", sa.Integer(), nullable=False),
        sa.Column("expected_current_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="PUBLISHED", nullable=False),
        sa.Column("published_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("rollback_request_id", sa.String(length=64), nullable=True),
        sa.Column("rollback_created_version_id", sa.Integer(), nullable=True),
        sa.Column("rollback_version", sa.Integer(), nullable=True),
        sa.Column("rolled_back_by_user_id", sa.Integer(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PUBLISHED', 'ROLLED_BACK')",
            name="ck_agent_evaluation_release_status",
        ),
        sa.CheckConstraint(
            "candidate_version > 0",
            name="ck_agent_evaluation_release_candidate_version",
        ),
        sa.CheckConstraint(
            "previous_version > 0",
            name="ck_agent_evaluation_release_previous_version",
        ),
        sa.CheckConstraint(
            "expected_current_version > 0",
            name="ck_agent_evaluation_release_expected_current_version",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["candidate_version_id"],
            ["agent_prompt_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rollback_created_version_id"],
            ["agent_prompt_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rolled_back_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_evaluation_releases_id"),
        "agent_evaluation_releases",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_evaluation_releases_request_id"),
        "agent_evaluation_releases",
        ["request_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_agent_evaluation_releases_evaluation_run_id"),
        "agent_evaluation_releases",
        ["evaluation_run_id"],
        unique=True,
    )
    for column in ("agent_id", "candidate_version_id", "status"):
        op.create_index(
            op.f(f"ix_agent_evaluation_releases_{column}"),
            "agent_evaluation_releases",
            [column],
            unique=False,
        )
    op.create_index(
        op.f("ix_agent_evaluation_releases_rollback_request_id"),
        "agent_evaluation_releases",
        ["rollback_request_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("agent_evaluation_releases")
    op.drop_index(
        op.f("ix_evaluation_runs_candidate_version_id"),
        table_name="evaluation_runs",
    )
    op.drop_index(
        op.f("ix_evaluation_runs_candidate_agent_id"),
        table_name="evaluation_runs",
    )
    with op.batch_alter_table("evaluation_runs", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_evaluation_runs_candidate_version_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_evaluation_runs_candidate_agent_id",
            type_="foreignkey",
        )
        batch_op.drop_column("expected_current_version")
        batch_op.drop_column("candidate_version")
        batch_op.drop_column("candidate_version_id")
        batch_op.drop_column("candidate_agent_id")
