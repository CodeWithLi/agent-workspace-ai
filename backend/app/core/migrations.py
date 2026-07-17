from sqlalchemy import inspect, text
from contextlib import nullcontext

from sqlalchemy.engine import Connection, Engine


def run_lightweight_migrations(bind: Engine | Connection) -> None:
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    dialect = bind.dialect.name

    def columns(table: str) -> set[str]:
        if table not in tables:
            return set()
        return {column["name"] for column in inspector.get_columns(table)}

    statements: list[str] = []

    user_columns = columns("users")
    if "is_active" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT true")
    if "permissions" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN permissions TEXT DEFAULT ''")
    if "ai_token_balance" not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN ai_token_balance INTEGER DEFAULT 1000")

    project_columns = columns("projects")
    if "projects" in tables and "status" not in project_columns:
        statements.append("ALTER TABLE projects ADD COLUMN status VARCHAR(30) DEFAULT 'ACTIVE'")
    if "projects" in tables and "updated_at" not in project_columns:
        statements.append("ALTER TABLE projects ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    tool_columns = columns("agent_tools")
    if "allowed_roles" not in tool_columns:
        statements.append("ALTER TABLE agent_tools ADD COLUMN allowed_roles VARCHAR(200) DEFAULT 'admin,member'")

    agent_columns = columns("agents")
    if "human_approval_required" not in agent_columns:
        statements.append("ALTER TABLE agents ADD COLUMN human_approval_required BOOLEAN DEFAULT false")
    if "concurrency_limit" not in agent_columns:
        statements.append("ALTER TABLE agents ADD COLUMN concurrency_limit INTEGER DEFAULT 4")
    if "current_version" not in agent_columns:
        statements.append("ALTER TABLE agents ADD COLUMN current_version INTEGER DEFAULT 1")

    message_columns = columns("messages")
    if "messages" in tables and "parent_message_id" not in message_columns:
        statements.append("ALTER TABLE messages ADD COLUMN parent_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL")
    if "messages" in tables and "regenerated_from_id" not in message_columns:
        statements.append("ALTER TABLE messages ADD COLUMN regenerated_from_id INTEGER REFERENCES messages(id) ON DELETE SET NULL")

    task_columns = columns("tasks")
    if "tasks" in tables and "assignee_user_id" not in task_columns:
        statements.append("ALTER TABLE tasks ADD COLUMN assignee_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
    if "tasks" in tables and "due_at" not in task_columns:
        statements.append("ALTER TABLE tasks ADD COLUMN due_at TIMESTAMP")

    workflow_columns = columns("workflow_runs")
    if "workflow_runs" in tables and "lease_token" not in workflow_columns:
        statements.append("ALTER TABLE workflow_runs ADD COLUMN lease_token VARCHAR(64)")

    for table in ("requirements", "meetings", "reports"):
        table_columns = columns(table)
        if table in tables and "updated_at" not in table_columns:
            statements.append(f"ALTER TABLE {table} ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

    workflow_columns = columns("workflow_runs")
    if "workflow_runs" in tables and "request_id" not in workflow_columns:
        statements.append("ALTER TABLE workflow_runs ADD COLUMN request_id VARCHAR(64)")
        statements.append("CREATE UNIQUE INDEX IF NOT EXISTS ix_workflow_runs_request_id ON workflow_runs(request_id)")
    workflow_additions = {
        "billing_transaction_id": "INTEGER REFERENCES token_transactions(id) ON DELETE SET NULL",
        "pause_before_report": "BOOLEAN DEFAULT true",
        "attempt_count": "INTEGER DEFAULT 0",
        "max_attempts": "INTEGER DEFAULT 2",
        "error": "TEXT DEFAULT ''",
        "locked_at": "TIMESTAMP",
        "cancel_requested_at": "TIMESTAMP",
        "started_at": "TIMESTAMP",
        "finished_at": "TIMESTAMP",
    }
    for name, definition in workflow_additions.items():
        if "workflow_runs" in tables and name not in workflow_columns:
            statements.append(f"ALTER TABLE workflow_runs ADD COLUMN {name} {definition}")

    notification_columns = columns("notifications")
    notification_additions = {
        "recipient_user_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
        "recipient_email": "VARCHAR(255) DEFAULT ''",
        "scheduled_for": "TIMESTAMP",
        "attempts": "INTEGER DEFAULT 0",
        "locked_at": "TIMESTAMP",
        "sent_at": "TIMESTAMP",
        "last_error": "TEXT DEFAULT ''",
    }
    for name, definition in notification_additions.items():
        if "notifications" in tables and name not in notification_columns:
            statements.append(f"ALTER TABLE notifications ADD COLUMN {name} {definition}")

    embedding_columns = columns("embeddings")
    if "embeddings" in tables and "vector_json" not in embedding_columns:
        statements.append("ALTER TABLE embeddings ADD COLUMN vector_json TEXT DEFAULT '[]'")
    embedding_additions = {
        "stable_id": "VARCHAR(64) DEFAULT ''",
        "index_version": "INTEGER DEFAULT 0",
        "parent_stable_id": "VARCHAR(64) DEFAULT ''",
        "parent_content": "TEXT DEFAULT ''",
        "token_count": "INTEGER DEFAULT 0",
        "heading_path_json": "TEXT DEFAULT '[]'",
        "page_start": "INTEGER",
        "page_end": "INTEGER",
        "element_ids_json": "TEXT DEFAULT '[]'",
        "metadata_json": "TEXT DEFAULT '{}'",
        "content_hash": "VARCHAR(64) DEFAULT ''",
    }
    for name, definition in embedding_additions.items():
        if "embeddings" in tables and name not in embedding_columns:
            statements.append(f"ALTER TABLE embeddings ADD COLUMN {name} {definition}")
    if "embeddings" in tables and "stable_id" not in embedding_columns:
        statements.append("CREATE INDEX IF NOT EXISTS ix_embeddings_stable_id ON embeddings(stable_id)")
    if "embeddings" in tables and "index_version" not in embedding_columns:
        statements.append("CREATE INDEX IF NOT EXISTS ix_embeddings_index_version ON embeddings(index_version)")

    document_columns = columns("documents")
    document_additions = {
        "content_hash": "VARCHAR(64) DEFAULT ''",
        "dedup_key": "VARCHAR(150)",
        "source_label": "VARCHAR(100) DEFAULT 'upload'",
        "metadata_json": "TEXT DEFAULT '{}'",
        "version": "INTEGER DEFAULT 1",
        "attempts": "INTEGER DEFAULT 0",
        "max_attempts": "INTEGER DEFAULT 3",
        "error": "TEXT DEFAULT ''",
        "locked_at": "TIMESTAMP",
        "indexed_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "active_index_version": "INTEGER DEFAULT 0",
        "pending_index_version": "INTEGER",
        "parser_name": "VARCHAR(100) DEFAULT ''",
        "parser_version": "VARCHAR(50) DEFAULT ''",
        "chunker_name": "VARCHAR(100) DEFAULT ''",
        "chunker_version": "VARCHAR(50) DEFAULT ''",
        "element_count": "INTEGER DEFAULT 0",
        "chunk_count": "INTEGER DEFAULT 0",
        "index_config_json": "TEXT DEFAULT '{}'",
    }
    for name, definition in document_additions.items():
        if "documents" in tables and name not in document_columns:
            statements.append(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
    if "documents" in tables and "dedup_key" not in document_columns:
        statements.append("CREATE UNIQUE INDEX IF NOT EXISTS ix_documents_dedup_key ON documents(dedup_key)")
    if "documents" in tables and "active_index_version" not in document_columns:
        statements.append(
            "CREATE INDEX IF NOT EXISTS ix_documents_active_index_version ON documents(active_index_version)"
        )

    if dialect != "sqlite" and "tasks" in tables:
        statements.append("UPDATE tasks SET status = UPPER(status) WHERE status IN ('todo', 'running', 'done', 'failed')")
    if dialect != "sqlite" and "workflow_runs" in tables:
        statements.append("UPDATE workflow_runs SET status = UPPER(status) WHERE status IN ('running', 'paused', 'completed', 'failed')")

    if "agents" in tables:
        approval_roles = "'product_manager','project_manager','architect','meeting_summarizer','notification_secretary'"
        statements.append(f"UPDATE agents SET human_approval_required = true WHERE role IN ({approval_roles})")

    if "project_members" in tables:
        if dialect == "sqlite":
            statements.append(
                "INSERT OR IGNORE INTO project_members (project_id, user_id, role) "
                "SELECT id, owner_id, 'owner' FROM projects"
            )
        else:
            statements.append(
                "INSERT INTO project_members (project_id, user_id, role) "
                "SELECT id, owner_id, 'owner' FROM projects ON CONFLICT (project_id, user_id) DO NOTHING"
            )

    if "document_index_versions" in tables and "documents" in tables and "embeddings" in tables:
        index_version_select = (
            "SELECT d.id, COALESCE(d.active_index_version, 0), 'ACTIVE', "
            "CASE WHEN COALESCE(d.parser_name, '') = '' THEN 'legacy' ELSE d.parser_name END, "
            "CASE WHEN COALESCE(d.parser_version, '') = '' THEN '1' ELSE d.parser_version END, "
            "CASE WHEN COALESCE(d.chunker_name, '') = '' THEN 'legacy-character-window' ELSE d.chunker_name END, "
            "CASE WHEN COALESCE(d.chunker_version, '') = '' THEN '1' ELSE d.chunker_version END, "
            "COALESCE(d.element_count, 0), COALESCE(d.chunk_count, 0), COALESCE(d.index_config_json, '{}'), "
            "d.indexed_at FROM documents d WHERE EXISTS ("
            "SELECT 1 FROM embeddings e WHERE e.document_id = d.id "
            "AND e.index_version = COALESCE(d.active_index_version, 0))"
        )
        columns_sql = (
            "(document_id, version, status, parser_name, parser_version, chunker_name, chunker_version, "
            "element_count, chunk_count, config_json, activated_at) "
        )
        if dialect == "sqlite":
            statements.append(
                "INSERT OR IGNORE INTO document_index_versions " + columns_sql + index_version_select
            )
        else:
            statements.append(
                "INSERT INTO document_index_versions "
                + columns_sql
                + index_version_select
                + " ON CONFLICT (document_id, version) DO NOTHING"
            )

    if "token_transactions" in tables:
        if dialect == "sqlite":
            statements.append(
                "INSERT OR IGNORE INTO token_transactions "
                "(user_id, amount, balance_after, transaction_type, reference_type, reference_id, idempotency_key, description) "
                "SELECT id, ai_token_balance, ai_token_balance, 'WELCOME', '', '', 'welcome:' || id, '存量用户赠送' FROM users"
            )
        else:
            statements.append(
                "INSERT INTO token_transactions "
                "(user_id, amount, balance_after, transaction_type, reference_type, reference_id, idempotency_key, description) "
                "SELECT id, ai_token_balance, ai_token_balance, 'WELCOME', '', '', 'welcome:' || CAST(id AS VARCHAR), '存量用户赠送' "
                "FROM users ON CONFLICT (idempotency_key) DO NOTHING"
            )

    if "requirements" not in tables:
        serial_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if dialect == "sqlite" else "SERIAL PRIMARY KEY"
        statements.append(
            f"""
            CREATE TABLE requirements (
                id {serial_type},
                project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title VARCHAR(200) NOT NULL,
                content TEXT NOT NULL,
                status VARCHAR(30) DEFAULT 'NEW',
                analysis TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    if not statements:
        return

    context = bind.begin() if isinstance(bind, Engine) else nullcontext(bind)
    with context as connection:
        for statement in statements:
            connection.execute(text(statement))
