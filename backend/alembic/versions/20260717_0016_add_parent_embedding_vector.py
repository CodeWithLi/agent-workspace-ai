"""add parent embedding vector

Revision ID: 20260717_0016
Revises: 20260717_0015
Create Date: 2026-07-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0016"
down_revision: Union[str, None] = "20260717_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("embeddings") as batch_op:
        batch_op.add_column(sa.Column("parent_vector_json", sa.Text(), server_default="[]", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("embeddings") as batch_op:
        batch_op.drop_column("parent_vector_json")
