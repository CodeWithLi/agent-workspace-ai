"""add Agent evaluation lab

Revision ID: 20260718_0018
Revises: 20260718_0017
Create Date: 2026-07-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260718_0018"
down_revision: Union[str, None] = "20260718_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_suite_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("cases_snapshot_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint"),
        sa.UniqueConstraint("version"),
    )
    for column in ("id", "version", "fingerprint"):
        op.create_index(
            op.f(f"ix_evaluation_suite_revisions_{column}"),
            "evaluation_suite_revisions",
            [column],
            unique=column in {"version", "fingerprint"},
        )

    with op.batch_alter_table("evaluation_cases") as batch_op:
        batch_op.add_column(sa.Column("forbidden_keywords_json", sa.Text(), server_default="[]", nullable=False))
        batch_op.add_column(sa.Column("rubric", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("minimum_score", sa.Float(), server_default="0.8", nullable=False))
        batch_op.add_column(sa.Column("weight", sa.Float(), server_default="1.0", nullable=False))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_evaluation_case_minimum_score",
            "minimum_score >= 0 AND minimum_score <= 1",
        )
        batch_op.create_check_constraint("ck_evaluation_case_weight", "weight > 0")

    with op.batch_alter_table("evaluation_runs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=30),
            server_default="QUEUED",
            existing_nullable=False,
        )
        batch_op.add_column(sa.Column("request_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("request_payload_hash", sa.String(length=64), server_default="", nullable=False))
        batch_op.add_column(sa.Column("suite_revision_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("baseline_run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("completed_cases", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("baseline_average_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("score_delta", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("gate_passed", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("gate_failures_json", sa.Text(), server_default="[]", nullable=False))
        batch_op.add_column(sa.Column("dimension_averages_json", sa.Text(), server_default="{}", nullable=False))
        batch_op.add_column(
            sa.Column("baseline_dimension_averages_json", sa.Text(), server_default="{}", nullable=False)
        )
        batch_op.add_column(sa.Column("agent_snapshot_json", sa.Text(), server_default="{}", nullable=False))
        batch_op.add_column(sa.Column("error", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("max_attempts", sa.Integer(), server_default="2", nullable=False))
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("lease_token", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_evaluation_runs_suite_revision_id",
            "evaluation_suite_revisions",
            ["suite_revision_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_evaluation_runs_baseline_run_id",
            "evaluation_runs",
            ["baseline_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint("ck_evaluation_run_completed_cases", "completed_cases >= 0")
        batch_op.create_check_constraint("ck_evaluation_run_attempt_count", "attempt_count >= 0")
        batch_op.create_check_constraint("ck_evaluation_run_max_attempts", "max_attempts > 0")

    op.execute(
        sa.text(
            "UPDATE evaluation_runs SET completed_cases = total_cases "
            "WHERE status = 'COMPLETED'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE evaluation_runs SET status = 'FAILED', "
            "error = 'Legacy evaluation was interrupted before durable execution was enabled', "
            "finished_at = CURRENT_TIMESTAMP WHERE status = 'RUNNING'"
        )
    )

    for column in (
        "request_id",
        "suite_revision_id",
        "baseline_run_id",
        "next_attempt_at",
        "locked_at",
        "lease_token",
    ):
        op.create_index(
            op.f(f"ix_evaluation_runs_{column}"),
            "evaluation_runs",
            [column],
            unique=column == "request_id",
        )
    op.create_index(
        "ix_evaluation_runs_queue",
        "evaluation_runs",
        ["status", "next_attempt_at", "created_at"],
        unique=False,
    )

    with op.batch_alter_table("evaluation_results") as batch_op:
        batch_op.add_column(sa.Column("baseline_result_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("case_snapshot_json", sa.Text(), server_default="{}", nullable=False))
        batch_op.add_column(sa.Column("agent_snapshot_json", sa.Text(), server_default="{}", nullable=False))
        batch_op.add_column(sa.Column("baseline_answer", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("baseline_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("score_delta", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("dimension_scores_json", sa.Text(), server_default="{}", nullable=False))
        batch_op.add_column(
            sa.Column("baseline_dimension_scores_json", sa.Text(), server_default="{}", nullable=False)
        )
        batch_op.add_column(
            sa.Column("score_source", sa.String(length=30), server_default="deterministic_fallback", nullable=False)
        )
        batch_op.add_column(sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("regressed", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.create_foreign_key(
            "fk_evaluation_results_baseline_result_id",
            "evaluation_results",
            ["baseline_result_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint("ck_evaluation_result_latency_ms", "latency_ms >= 0")


def downgrade() -> None:
    with op.batch_alter_table("evaluation_results") as batch_op:
        batch_op.drop_constraint("ck_evaluation_result_latency_ms", type_="check")
        batch_op.drop_constraint("fk_evaluation_results_baseline_result_id", type_="foreignkey")
        for column in (
            "regressed",
            "latency_ms",
            "score_source",
            "baseline_dimension_scores_json",
            "dimension_scores_json",
            "score_delta",
            "baseline_score",
            "baseline_answer",
            "agent_snapshot_json",
            "case_snapshot_json",
            "baseline_result_id",
        ):
            batch_op.drop_column(column)

    op.drop_index("ix_evaluation_runs_queue", table_name="evaluation_runs")
    for column in (
        "lease_token",
        "locked_at",
        "next_attempt_at",
        "baseline_run_id",
        "suite_revision_id",
        "request_id",
    ):
        op.drop_index(op.f(f"ix_evaluation_runs_{column}"), table_name="evaluation_runs")
    with op.batch_alter_table("evaluation_runs") as batch_op:
        batch_op.drop_constraint("ck_evaluation_run_max_attempts", type_="check")
        batch_op.drop_constraint("ck_evaluation_run_attempt_count", type_="check")
        batch_op.drop_constraint("ck_evaluation_run_completed_cases", type_="check")
        batch_op.drop_constraint("fk_evaluation_runs_baseline_run_id", type_="foreignkey")
        batch_op.drop_constraint("fk_evaluation_runs_suite_revision_id", type_="foreignkey")
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=30),
            server_default="RUNNING",
            existing_nullable=False,
        )
        for column in (
            "started_at",
            "updated_at",
            "lease_token",
            "locked_at",
            "next_attempt_at",
            "max_attempts",
            "attempt_count",
            "error",
            "agent_snapshot_json",
            "baseline_dimension_averages_json",
            "dimension_averages_json",
            "gate_failures_json",
            "gate_passed",
            "score_delta",
            "baseline_average_score",
            "completed_cases",
            "baseline_run_id",
            "suite_revision_id",
            "request_payload_hash",
            "request_id",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("evaluation_cases") as batch_op:
        batch_op.drop_constraint("ck_evaluation_case_weight", type_="check")
        batch_op.drop_constraint("ck_evaluation_case_minimum_score", type_="check")
        for column in ("updated_at", "weight", "minimum_score", "rubric", "forbidden_keywords_json"):
            batch_op.drop_column(column)

    for column in ("fingerprint", "version", "id"):
        op.drop_index(op.f(f"ix_evaluation_suite_revisions_{column}"), table_name="evaluation_suite_revisions")
    op.drop_table("evaluation_suite_revisions")
