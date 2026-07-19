from sqlalchemy import create_engine, inspect, text

from app.core.migrations import run_lightweight_migrations


def test_sqlite_backfills_timestamp_columns_when_upgrading_populated_tables() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, is_active BOOLEAN, permissions TEXT, "
                "ai_token_balance INTEGER)"
            )
        )
        connection.execute(
            text("CREATE TABLE agent_tools (id INTEGER PRIMARY KEY, allowed_roles TEXT)")
        )
        connection.execute(
            text(
                "CREATE TABLE agents ("
                "id INTEGER PRIMARY KEY, role TEXT, human_approval_required BOOLEAN, "
                "concurrency_limit INTEGER, current_version INTEGER)"
            )
        )
        for table in ("projects", "requirements", "meetings", "reports", "documents"):
            connection.execute(
                text(
                    f"""
                    CREATE TABLE {table} (
                        id INTEGER PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))

    run_lightweight_migrations(engine)
    run_lightweight_migrations(engine)

    inspector = inspect(engine)
    with engine.begin() as connection:
        for table in ("projects", "requirements", "meetings", "reports", "documents"):
            connection.execute(text(f"INSERT INTO {table} (id) VALUES (2)"))

    with engine.connect() as connection:
        for table in ("projects", "requirements", "meetings", "reports", "documents"):
            assert "updated_at" in {
                column["name"] for column in inspector.get_columns(table)
            }
            assert connection.scalar(
                text(f"SELECT updated_at FROM {table} WHERE id = 1")
            ) is not None
            assert connection.scalar(
                text(f"SELECT updated_at FROM {table} WHERE id = 2")
            ) is not None
