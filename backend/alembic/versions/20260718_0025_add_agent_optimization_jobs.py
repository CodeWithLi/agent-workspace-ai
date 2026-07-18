"""add durable Agent optimization jobs

Revision ID: 20260718_0025
Revises: 20260718_0024
Create Date: 2026-07-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260718_0025"
down_revision: Union[str, None] = "20260718_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_optimization_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("request_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluation_run_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("source_version_id", sa.Integer(), nullable=True),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("result_ids_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("evidence_snapshot_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="QUEUED", nullable=False),
        sa.Column("stage", sa.String(length=30), server_default="queued", nullable=False),
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("optimizer_model", sa.String(length=100), server_default="", nullable=False),
        sa.Column("reviewer_model", sa.String(length=100), server_default="", nullable=False),
        sa.Column("optimizer_output_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("reviewer_output_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("safety_checks_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("draft_version_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), server_default="", nullable=False),
        sa.Column("error_message", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'CANCELLING', 'CANCELLED', 'COMPLETED', 'REJECTED', 'FAILED')",
            name="ck_agent_optimization_job_status",
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_agent_optimization_job_progress",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_agent_optimization_job_attempt_count",
        ),
        sa.CheckConstraint(
            "max_attempts > 0",
            name="ck_agent_optimization_job_max_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["agent_prompt_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["draft_version_id"],
            ["agent_prompt_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_optimization_jobs_id"),
        "agent_optimization_jobs",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_optimization_jobs_request_id"),
        "agent_optimization_jobs",
        ["request_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_agent_optimization_jobs_draft_version_id"),
        "agent_optimization_jobs",
        ["draft_version_id"],
        unique=True,
    )
    for column in (
        "evaluation_run_id",
        "agent_id",
        "source_version_id",
        "evidence_fingerprint",
        "status",
        "next_attempt_at",
        "locked_at",
        "lease_token",
        "created_by_user_id",
    ):
        op.create_index(
            op.f(f"ix_agent_optimization_jobs_{column}"),
            "agent_optimization_jobs",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_agent_optimization_jobs_queue",
        "agent_optimization_jobs",
        ["status", "next_attempt_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("agent_optimization_jobs")
