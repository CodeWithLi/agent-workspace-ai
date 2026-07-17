"""add project collaboration lifecycle

Revision ID: 20260717_0009
Revises: 20260717_0008
Create Date: 2026-07-17 16:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0009"
down_revision: Union[str, None] = "20260717_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=30), server_default="ACTIVE", nullable=False))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))
        batch_op.create_index(batch_op.f("ix_projects_status"), ["status"], unique=False)
    for table in ("requirements", "meetings", "reports"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False))
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("assignee_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key("fk_tasks_assignee_user_id", "users", ["assignee_user_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index(batch_op.f("ix_tasks_assignee_user_id"), ["assignee_user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_tasks_due_at"), ["due_at"], unique=False)

    op.create_table(
        "task_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "task_id", "user_id"):
        op.create_index(op.f(f"ix_task_comments_{column}"), "task_comments", [column], unique=False)

    op.create_table(
        "workflow_artifact_publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("target", sa.String(length=30), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "document_type", "target", name="uq_workflow_artifact_target"),
    )
    op.create_index(op.f("ix_workflow_artifact_publications_id"), "workflow_artifact_publications", ["id"], unique=False)
    op.create_index(op.f("ix_workflow_artifact_publications_workflow_id"), "workflow_artifact_publications", ["workflow_id"], unique=False)
    op.create_index(op.f("ix_workflow_artifact_publications_request_id"), "workflow_artifact_publications", ["request_id"], unique=True)


def downgrade() -> None:
    for column in ("request_id", "workflow_id", "id"):
        op.drop_index(op.f(f"ix_workflow_artifact_publications_{column}"), table_name="workflow_artifact_publications")
    op.drop_table("workflow_artifact_publications")
    for column in ("user_id", "task_id", "id"):
        op.drop_index(op.f(f"ix_task_comments_{column}"), table_name="task_comments")
    op.drop_table("task_comments")
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tasks_due_at"))
        batch_op.drop_index(batch_op.f("ix_tasks_assignee_user_id"))
        batch_op.drop_constraint("fk_tasks_assignee_user_id", type_="foreignkey")
        batch_op.drop_column("due_at")
        batch_op.drop_column("assignee_user_id")
    for table in ("reports", "meetings", "requirements"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column("updated_at")
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_projects_status"))
        batch_op.drop_column("updated_at")
        batch_op.drop_column("status")
