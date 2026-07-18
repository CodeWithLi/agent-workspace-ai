"""add workflow operator interventions

Revision ID: 20260718_0022
Revises: 20260718_0021
Create Date: 2026-07-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260718_0022"
down_revision: Union[str, None] = "20260718_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pause_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("pause_requested_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pause_reason", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("pause_request_id", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("intervention_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.create_foreign_key(
            "fk_workflow_runs_pause_requested_by_user_id",
            "users",
            ["pause_requested_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "ck_workflow_runs_intervention_count",
            "intervention_count >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.drop_constraint("ck_workflow_runs_intervention_count", type_="check")
        batch_op.drop_constraint(
            "fk_workflow_runs_pause_requested_by_user_id",
            type_="foreignkey",
        )
        batch_op.drop_column("intervention_count")
        batch_op.drop_column("pause_request_id")
        batch_op.drop_column("pause_reason")
        batch_op.drop_column("pause_requested_by_user_id")
        batch_op.drop_column("pause_requested_at")
