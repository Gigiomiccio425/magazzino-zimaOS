import os
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.migrations import runner
from app.migrations.runner import LATEST_VERSION, Migration, MigrationError, rotate, run_migrations
from tests.fixtures.v111 import build_v111_db


def _version(path):
    return sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0]


def _pre_dir(tmp_path):
    return tmp_path / "b" / "pre-migrazione"


def test_fresh_install(tmp_path):
    r = run_migrations(tmp_path / "m.db", tmp_path / "b")
    assert (r.from_version, r.to_version, r.backup_path) == (0, LATEST_VERSION, None)
    assert _version(tmp_path / "m.db") == LATEST_VERSION


def test_v111_backed_up_then_migrated(tmp_path):
    db = tmp_path / "m.db"
    build_v111_db(db)
    r = run_migrations(db, tmp_path / "b")
    assert r.from_version == 0
    assert r.backup_path.name.startswith(f"v0-a-v{LATEST_VERSION}-")
    assert r.backup_path.parent == _pre_dir(tmp_path)
    assert sqlite3.connect(r.backup_path).execute("select count(*) from components").fetchone()[0] == 4
    assert _version(db) == LATEST_VERSION


def test_second_run_noop(tmp_path):
    db = tmp_path / "m.db"
    build_v111_db(db)
    run_migrations(db, tmp_path / "b")
    r = run_migrations(db, tmp_path / "b")
    assert r.backup_path is None and r.from_version == r.to_version == LATEST_VERSION
    assert len(list(_pre_dir(tmp_path).glob("*.db"))) == 1


def test_failed_migration_rolls_back_and_no_duplicate_backup(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    build_v111_db(db)

    def boom(conn):
        conn.execute("CREATE TABLE boom (id INTEGER)")
        raise RuntimeError("rotto")

    monkeypatch.setattr(runner, "MIGRATIONS", runner.MIGRATIONS + [Migration(LATEST_VERSION + 1, "boom", boom)])
    for _ in range(2):
        with pytest.raises(MigrationError):
            run_migrations(db, tmp_path / "b")
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert conn.execute("select count(*) from sqlite_master where name='boom'").fetchone()[0] == 0
    assert conn.execute("select count(*) from components").fetchone()[0] == 4
    assert len(list(_pre_dir(tmp_path).glob("*.db"))) == 1


def test_corrupt_file_refused(tmp_path):
    db = tmp_path / "m.db"
    db.write_bytes(os.urandom(4096))
    with pytest.raises(MigrationError):
        run_migrations(db, tmp_path / "b")
    assert not _pre_dir(tmp_path).exists() or not list(_pre_dir(tmp_path).glob("*.db"))


def test_rotate_keeps_newest(tmp_path):
    now = time.time()
    for i in range(12):
        f = tmp_path / f"f{i:02d}.db"
        f.write_bytes(b"x")
        os.utime(f, (now + i, now + i))
    removed = rotate(tmp_path, keep=10)
    assert sorted(p.name for p in removed) == ["f00.db", "f01.db"]
    assert len(list(tmp_path.glob("*.db"))) == 10


def test_app_fails_to_start_on_migration_error(tmp_path):
    (tmp_path / "magazzino.db").write_bytes(os.urandom(4096))
    with pytest.raises(MigrationError):
        with TestClient(create_app(tmp_path, start_worker=False)):
            pass
