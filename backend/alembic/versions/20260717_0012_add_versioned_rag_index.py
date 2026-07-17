"""add versioned structured RAG index

Revision ID: 20260717_0012
Revises: 20260717_0011
Create Date: 2026-07-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260717_0012"
down_revision: Union[str, None] = "20260717_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("active_index_version", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("pending_index_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("parser_name", sa.String(length=100), server_default="", nullable=False))
        batch_op.add_column(sa.Column("parser_version", sa.String(length=50), server_default="", nullable=False))
        batch_op.add_column(sa.Column("chunker_name", sa.String(length=100), server_default="", nullable=False))
        batch_op.add_column(sa.Column("chunker_version", sa.String(length=50), server_default="", nullable=False))
        batch_op.add_column(sa.Column("element_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("index_config_json", sa.Text(), server_default="{}", nullable=False))
        batch_op.create_index(batch_op.f("ix_documents_active_index_version"), ["active_index_version"], unique=False)

    with op.batch_alter_table("embeddings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("stable_id", sa.String(length=64), server_default="", nullable=False))
        batch_op.add_column(sa.Column("index_version", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("parent_stable_id", sa.String(length=64), server_default="", nullable=False))
        batch_op.add_column(sa.Column("parent_content", sa.Text(), server_default="", nullable=False))
        batch_op.add_column(sa.Column("token_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("heading_path_json", sa.Text(), server_default="[]", nullable=False))
        batch_op.add_column(sa.Column("page_start", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("page_end", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("element_ids_json", sa.Text(), server_default="[]", nullable=False))
        batch_op.add_column(sa.Column("metadata_json", sa.Text(), server_default="{}", nullable=False))
        batch_op.add_column(sa.Column("content_hash", sa.String(length=64), server_default="", nullable=False))
        batch_op.create_index(batch_op.f("ix_embeddings_stable_id"), ["stable_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_embeddings_index_version"), ["index_version"], unique=False)

    op.create_table(
        "document_elements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.Column("stable_id", sa.String(length=64), nullable=False),
        sa.Column("element_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("heading_path_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), server_default="0", nullable=False),
        sa.Column("char_end", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metadata_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "index_version", "element_index", name="uq_document_element_version_index"),
    )
    op.create_index(op.f("ix_document_elements_id"), "document_elements", ["id"], unique=False)
    op.create_index(op.f("ix_document_elements_document_id"), "document_elements", ["document_id"], unique=False)
    op.create_index(op.f("ix_document_elements_index_version"), "document_elements", ["index_version"], unique=False)
    op.create_index(op.f("ix_document_elements_stable_id"), "document_elements", ["stable_id"], unique=False)
    op.create_index(op.f("ix_document_elements_kind"), "document_elements", ["kind"], unique=False)

    op.create_table(
        "document_index_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="STAGING", nullable=False),
        sa.Column("parser_name", sa.String(length=100), server_default="", nullable=False),
        sa.Column("parser_version", sa.String(length=50), server_default="", nullable=False),
        sa.Column("chunker_name", sa.String(length=100), server_default="", nullable=False),
        sa.Column("chunker_version", sa.String(length=50), server_default="", nullable=False),
        sa.Column("embedding_model", sa.String(length=100), server_default="", nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("element_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("config_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version", name="uq_document_index_version"),
    )
    op.create_index(op.f("ix_document_index_versions_id"), "document_index_versions", ["id"], unique=False)
    op.create_index(
        op.f("ix_document_index_versions_document_id"),
        "document_index_versions",
        ["document_id"],
        unique=False,
    )
    op.create_index(op.f("ix_document_index_versions_status"), "document_index_versions", ["status"], unique=False)
    op.execute(
        sa.text(
            "INSERT INTO document_index_versions "
            "(document_id, version, status, parser_name, parser_version, chunker_name, chunker_version, "
            "embedding_model, embedding_dimensions, element_count, chunk_count, config_json, error, activated_at) "
            "SELECT d.id, 0, 'ACTIVE', 'legacy', '1', 'legacy-character-window', '1', '', 0, 0, "
            "(SELECT COUNT(*) FROM embeddings e WHERE e.document_id = d.id), '{}', '', d.indexed_at "
            "FROM documents d WHERE EXISTS (SELECT 1 FROM embeddings e WHERE e.document_id = d.id)"
        )
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_index_versions_status"), table_name="document_index_versions")
    op.drop_index(op.f("ix_document_index_versions_document_id"), table_name="document_index_versions")
    op.drop_index(op.f("ix_document_index_versions_id"), table_name="document_index_versions")
    op.drop_table("document_index_versions")

    for name in (
        "ix_document_elements_kind",
        "ix_document_elements_stable_id",
        "ix_document_elements_index_version",
        "ix_document_elements_document_id",
        "ix_document_elements_id",
    ):
        op.drop_index(name, table_name="document_elements")
    op.drop_table("document_elements")

    with op.batch_alter_table("embeddings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_embeddings_index_version"))
        batch_op.drop_index(batch_op.f("ix_embeddings_stable_id"))
        for column in (
            "content_hash",
            "metadata_json",
            "element_ids_json",
            "page_end",
            "page_start",
            "heading_path_json",
            "token_count",
            "parent_content",
            "parent_stable_id",
            "index_version",
            "stable_id",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_documents_active_index_version"))
        for column in (
            "index_config_json",
            "chunk_count",
            "element_count",
            "chunker_version",
            "chunker_name",
            "parser_version",
            "parser_name",
            "pending_index_version",
            "active_index_version",
        ):
            batch_op.drop_column(column)
