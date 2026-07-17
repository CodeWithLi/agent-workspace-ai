"""add agent versions feedback usage and evaluations

Revision ID: 20260717_0008
Revises: 20260717_0007
Create Date: 2026-07-17 15:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0008"
down_revision: Union[str, None] = "20260717_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("current_version", sa.Integer(), server_default="1", nullable=False))
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_message_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("regenerated_from_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_messages_parent_message_id", "messages", ["parent_message_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_messages_regenerated_from_id", "messages", ["regenerated_from_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index(batch_op.f("ix_messages_parent_message_id"), ["parent_message_id"], unique=False)

    op.create_table(
        "agent_prompt_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("memory_enable", sa.Boolean(), nullable=False),
        sa.Column("knowledge_access", sa.Boolean(), nullable=False),
        sa.Column("human_approval_required", sa.Boolean(), nullable=False),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False),
        sa.Column("release_note", sa.String(length=500), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_prompt_version"),
    )
    op.create_index(op.f("ix_agent_prompt_versions_id"), "agent_prompt_versions", ["id"], unique=False)
    op.create_index(op.f("ix_agent_prompt_versions_agent_id"), "agent_prompt_versions", ["agent_id"], unique=False)
    op.create_index(op.f("ix_agent_prompt_versions_status"), "agent_prompt_versions", ["status"], unique=False)

    op.create_table(
        "message_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_feedback_user"),
    )
    for column in ("id", "message_id", "user_id"):
        op.create_index(op.f(f"ix_message_feedback_{column}"), "message_feedback", [column], unique=False)

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("workflow_id", sa.Integer(), nullable=True),
        sa.Column("agent_run_id", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_micros", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("usage_source", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("id", "user_id", "project_id", "agent_id", "workflow_id", "agent_run_id", "operation", "created_at"):
        op.create_index(op.f(f"ix_llm_usage_{column}"), "llm_usage", [column], unique=False)

    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("agent_role", sa.String(length=50), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("expected_keywords_json", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evaluation_cases_id"), "evaluation_cases", ["id"], unique=False)
    op.create_index(op.f("ix_evaluation_cases_agent_role"), "evaluation_cases", ["agent_role"], unique=False)

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("passed_cases", sa.Integer(), nullable=False),
        sa.Column("average_score", sa.Float(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evaluation_runs_id"), "evaluation_runs", ["id"], unique=False)
    op.create_index(op.f("ix_evaluation_runs_status"), "evaluation_runs", ["status"], unique=False)

    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["evaluation_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "case_id", name="uq_evaluation_run_case"),
    )
    for column in ("id", "run_id", "case_id"):
        op.create_index(op.f(f"ix_evaluation_results_{column}"), "evaluation_results", [column], unique=False)

    op.execute(
        sa.text(
            "INSERT INTO agent_prompt_versions "
            "(agent_id, version, status, description, system_prompt, model, memory_enable, knowledge_access, "
            "human_approval_required, concurrency_limit, release_note, published_at) "
            "SELECT id, 1, 'PUBLISHED', description, system_prompt, model, memory_enable, knowledge_access, "
            "human_approval_required, concurrency_limit, 'Initial imported version', CURRENT_TIMESTAMP FROM agents"
        )
    )


def downgrade() -> None:
    for column in ("case_id", "run_id", "id"):
        op.drop_index(op.f(f"ix_evaluation_results_{column}"), table_name="evaluation_results")
    op.drop_table("evaluation_results")
    for column in ("status", "id"):
        op.drop_index(op.f(f"ix_evaluation_runs_{column}"), table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    for column in ("agent_role", "id"):
        op.drop_index(op.f(f"ix_evaluation_cases_{column}"), table_name="evaluation_cases")
    op.drop_table("evaluation_cases")
    for column in ("created_at", "operation", "agent_run_id", "workflow_id", "agent_id", "project_id", "user_id", "id"):
        op.drop_index(op.f(f"ix_llm_usage_{column}"), table_name="llm_usage")
    op.drop_table("llm_usage")
    for column in ("user_id", "message_id", "id"):
        op.drop_index(op.f(f"ix_message_feedback_{column}"), table_name="message_feedback")
    op.drop_table("message_feedback")
    for column in ("status", "agent_id", "id"):
        op.drop_index(op.f(f"ix_agent_prompt_versions_{column}"), table_name="agent_prompt_versions")
    op.drop_table("agent_prompt_versions")
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_messages_parent_message_id"))
        batch_op.drop_constraint("fk_messages_regenerated_from_id", type_="foreignkey")
        batch_op.drop_constraint("fk_messages_parent_message_id", type_="foreignkey")
        batch_op.drop_column("regenerated_from_id")
        batch_op.drop_column("parent_message_id")
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_column("current_version")
