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

    embedding_columns = columns("embeddings")
    if "embeddings" in tables and "vector_json" not in embedding_columns:
        statements.append("ALTER TABLE embeddings ADD COLUMN vector_json TEXT DEFAULT '[]'")

    if dialect != "sqlite" and "tasks" in tables:
        statements.append("UPDATE tasks SET status = UPPER(status) WHERE status IN ('todo', 'running', 'done', 'failed')")
    if dialect != "sqlite" and "workflow_runs" in tables:
        statements.append("UPDATE workflow_runs SET status = UPPER(status) WHERE status IN ('running', 'paused', 'completed', 'failed')")

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
