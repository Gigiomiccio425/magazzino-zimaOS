import sqlite3

from app.database import Base
from app.migrations.runner import run_migrations
from tests.fixtures.v111 import build_v111_db

V111_TABLES = ["machines", "categories", "components", "movements"]


def _columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _assert_matches_models(db_path):
    import app.models  # noqa: F401  registra tutti i modelli

    conn = sqlite3.connect(db_path)
    for table in Base.metadata.sorted_tables:
        cols = set(_columns(conn, table.name))
        assert cols, f"tabella mancante: {table.name}"
        missing = {c.name for c in table.columns} - cols
        assert not missing, f"{table.name}: colonne mancanti {missing}"


def test_schema_matches_models_fresh(tmp_path):
    db = tmp_path / "m.db"
    run_migrations(db, tmp_path / "b")
    _assert_matches_models(db)


def test_schema_matches_models_from_v111(tmp_path):
    db = tmp_path / "m.db"
    build_v111_db(db)
    run_migrations(db, tmp_path / "b")
    _assert_matches_models(db)


def test_v111_columns_preserved(tmp_path):
    db = tmp_path / "m.db"
    build_v111_db(db)
    conn = sqlite3.connect(db)
    before = {t: _columns(conn, t) for t in V111_TABLES}
    conn.close()
    run_migrations(db, tmp_path / "b")
    conn = sqlite3.connect(db)
    for t, cols in before.items():
        assert set(cols) <= set(_columns(conn, t))


def test_v111_values_identical(tmp_path):
    db = tmp_path / "m.db"
    build_v111_db(db)
    conn = sqlite3.connect(db)
    cols = {t: _columns(conn, t) for t in V111_TABLES}
    before = {t: conn.execute(f"SELECT {', '.join(c)} FROM {t} ORDER BY id").fetchall() for t, c in cols.items()}
    conn.close()
    run_migrations(db, tmp_path / "b")
    conn = sqlite3.connect(db)
    for t, c in cols.items():
        assert conn.execute(f"SELECT {', '.join(c)} FROM {t} ORDER BY id").fetchall() == before[t]
