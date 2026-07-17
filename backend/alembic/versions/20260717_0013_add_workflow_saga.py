"""add durable workflow saga execution log

Revision ID: 20260717_0013
Revises: 20260717_0012
Create Date: 2026-07-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0013"
down_revision: Union[str, None] = "20260717_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    workflow_status = sa.Enum(
        "QUEUED",
        "RUNNING",
        "CANCELLING",
        "COMPENSATING",
        "COMPENSATION_FAILED",
        "CANCELLED",
        "PAUSED",
        "COMPLETED",
        "FAILED",
        name="workflowstatus",
        native_enum=False,
    )
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=10),
            type_=workflow_status,
            existing_nullable=False,
        )
        batch_op.add_column(sa.Column("lease_token", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_workflow_runs_lease_token"), ["lease_token"], unique=False)

    saga_status = sa.Enum(
        "PENDING",
        "EXECUTING",
        "COMPLETED",
        "FAILED",
        "COMPENSATING",
        "COMPENSATED",
        "COMPENSATION_FAILED",
        name="sagastepstatus",
        native_enum=False,
    )
    op.create_table(
        "workflow_saga_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("compensation_action", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=150), nullable=False),
        sa.Column("status", saga_status, server_default="PENDING", nullable=False),
        sa.Column("input_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("output_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("transition_log_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("execute_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("compensation_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("compensated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "idempotency_key", name="uq_workflow_saga_step_key"),
    )
    for column in ("id", "workflow_id", "sequence", "node", "tool_name", "status"):
        op.create_index(op.f(f"ix_workflow_saga_steps_{column}"), "workflow_saga_steps", [column], unique=False)


def downgrade() -> None:
    for column in ("status", "tool_name", "node", "sequence", "workflow_id", "id"):
        op.drop_index(op.f(f"ix_workflow_saga_steps_{column}"), table_name="workflow_saga_steps")
    op.drop_table("workflow_saga_steps")

    op.execute(
        sa.text(
            "UPDATE workflow_runs SET status = 'FAILED' "
            "WHERE status IN ('COMPENSATING', 'COMPENSATION_FAILED')"
        )
    )

    old_status = sa.Enum(
        "QUEUED",
        "RUNNING",
        "CANCELLING",
        "CANCELLED",
        "PAUSED",
        "COMPLETED",
        "FAILED",
        name="workflowstatus",
        native_enum=False,
    )
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_runs_lease_token"))
        batch_op.drop_column("lease_token")
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=19),
            type_=old_status,
            existing_nullable=False,
        )
