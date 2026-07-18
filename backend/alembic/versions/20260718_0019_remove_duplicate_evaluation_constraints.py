"""remove duplicate evaluation revision constraints

Revision ID: 20260718_0019
Revises: 20260718_0018
Create Date: 2026-07-18
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260718_0019"
down_revision: Union[str, None] = "20260718_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "evaluation_suite_revisions_fingerprint_key",
        "evaluation_suite_revisions",
        type_="unique",
    )
    op.drop_constraint(
        "evaluation_suite_revisions_version_key",
        "evaluation_suite_revisions",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "evaluation_suite_revisions_version_key",
        "evaluation_suite_revisions",
        ["version"],
    )
    op.create_unique_constraint(
        "evaluation_suite_revisions_fingerprint_key",
        "evaluation_suite_revisions",
        ["fingerprint"],
    )
