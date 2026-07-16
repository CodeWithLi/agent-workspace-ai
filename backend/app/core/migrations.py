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

    tool_columns = columns("agent_tools")
    if "allowed_roles" not in tool_columns:
        statements.append("ALTER TABLE agent_tools ADD COLUMN allowed_roles VARCHAR(200) DEFAULT 'admin,member'")

    agent_columns = columns("agents")
    if "human_approval_required" not in agent_columns:
        statements.append("ALTER TABLE agents ADD COLUMN human_approval_required BOOLEAN DEFAULT false")

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
