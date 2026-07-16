"""add agent approval controls

Revision ID: 20260716_0003
Revises: 20260716_0002
Create Date: 2026-07-16 23:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0003"
down_revision: Union[str, None] = "20260716_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("human_approval_required", sa.Boolean(), server_default=sa.false(), nullable=False))

    op.create_table(
        "agent_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "user_id", "project_id", "agent_id", "conversation_id", "status"):
        op.create_index(op.f(f"ix_agent_actions_{column}"), "agent_actions", [column], unique=False)

    approval_roles = "'product_manager','project_manager','architect','meeting_summarizer','notification_secretary'"
    op.execute(sa.text(f"UPDATE agents SET human_approval_required = true WHERE role IN ({approval_roles})"))


def downgrade() -> None:
    for column in ("status", "conversation_id", "agent_id", "project_id", "user_id", "id"):
        op.drop_index(op.f(f"ix_agent_actions_{column}"), table_name="agent_actions")
    op.drop_table("agent_actions")
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_column("human_approval_required")
