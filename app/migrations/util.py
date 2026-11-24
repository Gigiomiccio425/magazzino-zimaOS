"""Helper SQL condivisi dalle migrazioni."""
import sqlite3


def add_column(conn: sqlite3.Connection, table: str, ddl: str) -> None:
    """ALTER TABLE ADD COLUMN idempotente. `ddl` = 'nome TIPO ...'."""
    name = ddl.split()[0]
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
