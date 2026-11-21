"""Migrazione 1: schema originale v1.1.1 (crea le tabelle solo se mancano)."""
import sqlite3

DDL = [
    """CREATE TABLE IF NOT EXISTS machines (
        id INTEGER NOT NULL,
        name VARCHAR(120) NOT NULL,
        kind VARCHAR(60),
        location VARCHAR(160),
        description TEXT,
        created_at DATETIME,
        PRIMARY KEY (id),
        UNIQUE (name)
    )""",
    """CREATE TABLE IF NOT EXISTS categories (
        id INTEGER NOT NULL,
        name VARCHAR(80) NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (name)
    )""",
    """CREATE TABLE IF NOT EXISTS components (
        id INTEGER NOT NULL,
        object_code VARCHAR(80),
        name VARCHAR(160) NOT NULL,
        category VARCHAR(80),
        model VARCHAR(160),
        manufacturer VARCHAR(120),
        serial_number VARCHAR(160),
        quantity INTEGER,
        status VARCHAR(30),
        location VARCHAR(160),
        attributes JSON,
        notes TEXT,
        machine_id INTEGER,
        created_at DATETIME,
        updated_at DATETIME,
        PRIMARY KEY (id),
        FOREIGN KEY(machine_id) REFERENCES machines (id)
    )""",
    """CREATE TABLE IF NOT EXISTS movements (
        id INTEGER NOT NULL,
        component_id INTEGER NOT NULL,
        action VARCHAR(40),
        from_machine VARCHAR(120),
        to_machine VARCHAR(120),
        note TEXT,
        timestamp DATETIME,
        PRIMARY KEY (id),
        FOREIGN KEY(component_id) REFERENCES components (id)
    )""",
]


def apply(conn: sqlite3.Connection) -> None:
    for stmt in DDL:
        conn.execute(stmt)
