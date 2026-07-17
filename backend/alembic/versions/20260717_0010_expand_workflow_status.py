"""expand durable workflow status values

Revision ID: 20260717_0010
Revises: 20260717_0009
Create Date: 2026-07-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0010"
down_revision: Union[str, None] = "20260717_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    status_type = sa.Enum(
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
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=9),
            type_=status_type,
            existing_nullable=False,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE workflow_runs SET status = CASE "
            "WHEN status IN ('QUEUED', 'CANCELLING') THEN 'RUNNING' "
            "WHEN status = 'CANCELLED' THEN 'FAILED' ELSE status END"
        )
    )
    old_status_type = sa.Enum(
        "RUNNING",
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
            type_=old_status_type,
            existing_nullable=False,
        )
