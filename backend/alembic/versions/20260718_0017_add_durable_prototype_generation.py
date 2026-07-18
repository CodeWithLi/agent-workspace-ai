"""add durable prototype generation jobs

Revision ID: 20260718_0017
Revises: 20260717_0016
Create Date: 2026-07-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0017"
down_revision: Union[str, None] = "20260717_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prototype_generation_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("request_payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "operation",
            sa.Enum(
                "CREATE",
                "REGENERATE",
                name="prototypegenerationoperation",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "CANCELLING",
                "CANCELLED",
                name="prototypegenerationstatus",
                native_enum=False,
            ),
            server_default="QUEUED",
            nullable=False,
        ),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("requirement_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("prototype_id", sa.Integer(), nullable=True),
        sa.Column("base_version", sa.Integer(), nullable=True),
        sa.Column("target_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_prompt", sa.Text(), nullable=False),
        sa.Column(
            "requirement_snapshot_json",
            sa.Text(),
            server_default="null",
            nullable=False,
        ),
        sa.Column(
            "agent_snapshot_json", sa.Text(), server_default="{}", nullable=False
        ),
        sa.Column("state_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column(
            "stage", sa.String(length=100), server_default="queued", nullable=False
        ),
        sa.Column("stage_history_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latest_event_id", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column(
            "error_code", sa.String(length=100), server_default="", nullable=False
        ),
        sa.Column("error_message", sa.Text(), server_default="", nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_prototype_id", sa.Integer(), nullable=True),
        sa.Column("result_version", sa.Integer(), nullable=True),
        sa.Column("result_version_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["prototype_id"], ["product_prototypes.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["requirements.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["result_prototype_id"], ["product_prototypes.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["result_version_id"],
            ["product_prototype_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_prototype_generation_progress_percent",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_prototype_generation_attempt_count"
        ),
        sa.CheckConstraint(
            "max_attempts > 0", name="ck_prototype_generation_max_attempts"
        ),
        sa.CheckConstraint(
            "target_version > 0", name="ck_prototype_generation_target_version"
        ),
    )
    indexed_columns = (
        "id",
        "request_id",
        "operation",
        "status",
        "project_id",
        "requirement_id",
        "user_id",
        "prototype_id",
        "next_attempt_at",
        "locked_at",
        "lease_token",
        "result_prototype_id",
        "result_version_id",
    )
    for column in indexed_columns:
        op.create_index(
            op.f(f"ix_prototype_generation_jobs_{column}"),
            "prototype_generation_jobs",
            [column],
            unique=column == "request_id",
        )
    op.create_index(
        "ix_prototype_generation_jobs_queue",
        "prototype_generation_jobs",
        ["status", "next_attempt_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_prototype_generation_active_target_version",
        "prototype_generation_jobs",
        ["prototype_id", "target_version"],
        unique=True,
        postgresql_where=sa.text(
            "prototype_id IS NOT NULL AND status IN ('QUEUED','RUNNING','CANCELLING')"
        ),
        sqlite_where=sa.text(
            "prototype_id IS NOT NULL AND status IN ('QUEUED','RUNNING','CANCELLING')"
        ),
    )

    op.create_table(
        "prototype_generation_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=100), server_default="", nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("message", sa.String(length=500), server_default="", nullable=False),
        sa.Column("payload_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["prototype_generation_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "job_id", "event_type", "created_at"):
        op.create_index(
            op.f(f"ix_prototype_generation_events_{column}"),
            "prototype_generation_events",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("created_at", "event_type", "job_id", "id"):
        op.drop_index(
            op.f(f"ix_prototype_generation_events_{column}"),
            table_name="prototype_generation_events",
        )
    op.drop_table("prototype_generation_events")

    op.drop_index(
        "uq_prototype_generation_active_target_version",
        table_name="prototype_generation_jobs",
    )
    op.drop_index(
        "ix_prototype_generation_jobs_queue", table_name="prototype_generation_jobs"
    )
    for column in (
        "result_version_id",
        "result_prototype_id",
        "lease_token",
        "locked_at",
        "next_attempt_at",
        "prototype_id",
        "user_id",
        "requirement_id",
        "project_id",
        "status",
        "operation",
        "request_id",
        "id",
    ):
        op.drop_index(
            op.f(f"ix_prototype_generation_jobs_{column}"),
            table_name="prototype_generation_jobs",
        )
    op.drop_table("prototype_generation_jobs")
