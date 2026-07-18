"""add durable trace alerts

Revision ID: 20260718_0020
Revises: 20260718_0019
Create Date: 2026-07-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260718_0020"
down_revision: Union[str, None] = "20260718_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trace_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.Enum("OPEN", "ACKNOWLEDGED", "RESOLVED", name="tracealertstatus", native_enum=False),
            nullable=False,
            server_default="OPEN",
        ),
        sa.Column("signals_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost_micros", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("acknowledged_by_user_id", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("severity IN ('WARNING','CRITICAL')", name="ck_trace_alert_severity"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["acknowledged_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("workflow_id", name="uq_trace_alert_workflow"),
    )
    op.create_index("ix_trace_alerts_id", "trace_alerts", ["id"])
    op.create_index("ix_trace_alerts_workflow_id", "trace_alerts", ["workflow_id"])
    op.create_index("ix_trace_alerts_project_id", "trace_alerts", ["project_id"])
    op.create_index("ix_trace_alerts_user_id", "trace_alerts", ["user_id"])
    op.create_index("ix_trace_alerts_severity", "trace_alerts", ["severity"])
    op.create_index("ix_trace_alerts_status", "trace_alerts", ["status"])
    op.create_index("ix_trace_alerts_detected_at", "trace_alerts", ["detected_at"])
    op.create_index("ix_trace_alert_scope", "trace_alerts", ["user_id", "status", "detected_at"])


def downgrade() -> None:
    op.drop_table("trace_alerts")
