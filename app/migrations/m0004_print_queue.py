"""Migrazione 4: coda di stampa delle etichette (solo una tabella nuova, nessun dato esistente toccato)."""
import sqlite3

TABLE = """CREATE TABLE IF NOT EXISTS print_queue (
    id INTEGER NOT NULL,
    entity_type VARCHAR(20) NOT NULL,
    entity_id INTEGER NOT NULL,
    format VARCHAR(10) NOT NULL DEFAULT 'label',
    copies INTEGER NOT NULL DEFAULT 1,
    added_by VARCHAR(120),
    created_at DATETIME,
    PRIMARY KEY (id),
    UNIQUE (entity_type, entity_id)
)"""


def apply(conn: sqlite3.Connection) -> None:
    conn.execute(TABLE)
