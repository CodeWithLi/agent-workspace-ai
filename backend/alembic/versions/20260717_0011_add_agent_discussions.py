"""add multi-agent discussion metadata

Revision ID: 20260717_0011
Revises: 20260717_0010
Create Date: 2026-07-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0011"
down_revision: Union[str, None] = "20260717_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mode", sa.String(length=20), server_default="SINGLE", nullable=False))
        batch_op.create_index(batch_op.f("ix_conversations_mode"), ["mode"], unique=False)
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("agent_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("stage", sa.String(length=30), server_default="answer", nullable=False))
        batch_op.create_foreign_key("fk_messages_agent_id", "agents", ["agent_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index(batch_op.f("ix_messages_agent_id"), ["agent_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_messages_agent_id"))
        batch_op.drop_constraint("fk_messages_agent_id", type_="foreignkey")
        batch_op.drop_column("stage")
        batch_op.drop_column("agent_id")
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conversations_mode"))
        batch_op.drop_column("mode")
