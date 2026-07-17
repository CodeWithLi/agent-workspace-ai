"""add durable workflow queue and events

Revision ID: 20260717_0005
Revises: 20260717_0004
Create Date: 2026-07-17 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0005"
down_revision: Union[str, None] = "20260717_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("billing_transaction_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pause_before_report", sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.add_column(sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("max_attempts", sa.Integer(), server_default="2", nullable=False))
        batch_op.add_column(sa.Column("error", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_workflow_runs_billing_transaction_id",
            "token_transactions",
            ["billing_transaction_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(batch_op.f("ix_workflow_runs_locked_at"), ["locked_at"], unique=False)

    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "workflow_id", "event_type", "created_at"):
        op.create_index(op.f(f"ix_workflow_events_{column}"), "workflow_events", [column], unique=False)


def downgrade() -> None:
    for column in ("created_at", "event_type", "workflow_id", "id"):
        op.drop_index(op.f(f"ix_workflow_events_{column}"), table_name="workflow_events")
    op.drop_table("workflow_events")
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_runs_locked_at"))
        batch_op.drop_constraint("fk_workflow_runs_billing_transaction_id", type_="foreignkey")
        for column in (
            "finished_at",
            "started_at",
            "cancel_requested_at",
            "locked_at",
            "error",
            "max_attempts",
            "attempt_count",
            "pause_before_report",
            "billing_transaction_id",
        ):
            batch_op.drop_column(column)
