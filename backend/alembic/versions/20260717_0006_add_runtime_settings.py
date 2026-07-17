"""add runtime system setting overrides

Revision ID: 20260717_0006
Revises: 20260717_0005
Create Date: 2026-07-17 13:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0006"
down_revision: Union[str, None] = "20260717_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_setting_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("is_secret", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_system_setting_overrides_id"), "system_setting_overrides", ["id"], unique=False)
    op.create_index(op.f("ix_system_setting_overrides_key"), "system_setting_overrides", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_system_setting_overrides_key"), table_name="system_setting_overrides")
    op.drop_index(op.f("ix_system_setting_overrides_id"), table_name="system_setting_overrides")
    op.drop_table("system_setting_overrides")
