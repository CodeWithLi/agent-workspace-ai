"""add immutable workflow retry lineage

Revision ID: 20260718_0021
Revises: 20260718_0020
Create Date: 2026-07-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260718_0021"
down_revision: Union[str, None] = "20260718_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_workflow_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("retry_from_node", sa.String(length=100), server_default="", nullable=False)
        )
        batch_op.add_column(
            sa.Column("retry_sequence", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.create_foreign_key(
            "fk_workflow_runs_parent_workflow_id",
            "workflow_runs",
            ["parent_workflow_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_workflow_runs_retry_sequence",
            "retry_sequence >= 0",
        )
        batch_op.create_index(
            "ix_workflow_runs_parent_workflow_id",
            ["parent_workflow_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_workflow_runs_parent_workflow_id")
        batch_op.drop_constraint("ck_workflow_runs_retry_sequence", type_="check")
        batch_op.drop_constraint("fk_workflow_runs_parent_workflow_id", type_="foreignkey")
        batch_op.drop_column("retry_sequence")
        batch_op.drop_column("retry_from_node")
        batch_op.drop_column("parent_workflow_id")
