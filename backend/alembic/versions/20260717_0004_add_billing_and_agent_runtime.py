"""add billing and agent runtime controls

Revision ID: 20260717_0004
Revises: 20260716_0003
Create Date: 2026-07-17 00:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0004"
down_revision: Union[str, None] = "20260716_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ai_token_balance", sa.Integer(), server_default="1000", nullable=False))
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("concurrency_limit", sa.Integer(), server_default="4", nullable=False))
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("request_id", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_workflow_runs_request_id"), ["request_id"], unique=True)

    op.create_table(
        "token_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("transaction_type", sa.String(length=30), nullable=False),
        sa.Column("reference_type", sa.String(length=50), nullable=False),
        sa.Column("reference_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=150), nullable=True),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("operator_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["operator_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column, unique in (("id", False), ("user_id", False), ("transaction_type", False), ("idempotency_key", True), ("created_at", False)):
        op.create_index(op.f(f"ix_token_transactions_{column}"), "token_transactions", [column], unique=unique)

    op.create_table(
        "recharge_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_no", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("token_amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column, unique in (("id", False), ("order_no", True), ("user_id", False), ("status", False)):
        op.create_index(op.f(f"ix_recharge_orders_{column}"), "recharge_orders", [column], unique=unique)

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("billing_transaction_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["billing_transaction_id"], ["token_transactions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column, unique in (
        ("id", False),
        ("request_id", True),
        ("user_id", False),
        ("project_id", False),
        ("agent_id", False),
        ("conversation_id", False),
        ("status", False),
    ):
        op.create_index(op.f(f"ix_agent_runs_{column}"), "agent_runs", [column], unique=unique)

    op.execute(
        sa.text(
            "INSERT INTO token_transactions "
            "(user_id, amount, balance_after, transaction_type, reference_type, reference_id, idempotency_key, description) "
            "SELECT id, 1000, 1000, 'WELCOME', '', '', 'welcome:' || CAST(id AS VARCHAR), "
            "'Existing user welcome grant' FROM users"
        )
    )


def downgrade() -> None:
    for column in ("status", "conversation_id", "agent_id", "project_id", "user_id", "request_id", "id"):
        op.drop_index(op.f(f"ix_agent_runs_{column}"), table_name="agent_runs")
    op.drop_table("agent_runs")
    for column in ("status", "user_id", "order_no", "id"):
        op.drop_index(op.f(f"ix_recharge_orders_{column}"), table_name="recharge_orders")
    op.drop_table("recharge_orders")
    for column in ("created_at", "idempotency_key", "transaction_type", "user_id", "id"):
        op.drop_index(op.f(f"ix_token_transactions_{column}"), table_name="token_transactions")
    op.drop_table("token_transactions")
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_runs_request_id"))
        batch_op.drop_column("request_id")
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_column("concurrency_limit")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("ai_token_balance")
