import io
import json
import os
import sqlite3
import time
import zipfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.migrations.runner import LATEST_VERSION
from app.models import Component, Operator
from app.services import backup
from tests.fixtures.v111 import build_v111_db
from tests.helpers import FETCH, critical_post, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def settings(app, client):
    return app.state.settings


@pytest.fixture
def op_id(client, db):
    return db.query(Operator).one().id


def test_daily_backup_once_per_day(settings):
    assert backup.daily_backup(settings, datetime(2026, 11, 24, 2, 59)) is None
    first = backup.daily_backup(settings, datetime(2026, 11, 24, 3, 5))
    assert first.name == "2026-11-24.db" and first.exists()
    assert backup.daily_backup(settings, datetime(2026, 11, 24, 18, 0)) is None


def test_daily_rotation_14(settings):
    base = time.time() - 10_000  # mtime crescenti nel passato: l'ultimo creato resta il piu' recente
    for day in range(1, 17):
        backup.daily_backup(settings, datetime(2026, 10, day, 4, 0))
        p = settings.backups_dir / backup.DAILY_DIR / f"2026-10-{day:02d}.db"
        os.utime(p, (base + day, base + day))
    files = sorted(p.name for p in (settings.backups_dir / backup.DAILY_DIR).glob("*.db"))
    assert len(files) == 14 and files[0] == "2026-10-03.db"


def test_export_zip_contents(settings):
    (settings.uploads_dir / "2026" / "11").mkdir(parents=True)
    (settings.uploads_dir / "2026" / "11" / "foto.jpg").write_bytes(b"jpg")
    path = backup.export_zip(settings)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        manifest = json.loads(z.read("manifest.json"))
    assert {"magazzino.db", "manifest.json", "uploads/2026/11/foto.jpg"} <= names
    assert manifest["schema_version"] == LATEST_VERSION and manifest["app_version"] == "2.0.0"


def test_validate_rejects_bad_inputs(tmp_path):
    junk = tmp_path / "x.db"
    junk.write_bytes(b"not sqlite at all" * 100)
    assert not backup.validate_backup(junk).ok
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("magazzino.db", b"")
        z.writestr("../fuori.txt", b"x")
    assert not backup.validate_backup(evil).ok
    empty = tmp_path / "vuoto.db"
    sqlite3.connect(empty).execute("CREATE TABLE altro (id INTEGER)")
    check = backup.validate_backup(empty)
    assert not check.ok and "tabelle" in check.reason


def test_restore_zip_replaces_and_keeps_pre_restore(app, settings, db):
    db.add(Component(name="Prima del backup", attributes={}))
    db.commit()
    snap = backup.export_zip(settings)
    db.add(Component(name="Dopo il backup", attributes={}))
    db.commit()
    report = backup.restore_backup(app, snap)
    assert report.pre_restore_path.exists()
    with app.state.engine.connect() as conn:
        names = {r[0] for r in conn.exec_driver_sql("SELECT name FROM components")}
    assert names == {"Prima del backup"}


def test_restore_v111_db_runs_migrations(app, settings, tmp_path):
    old = tmp_path / "vecchio.db"
    build_v111_db(old)
    report = backup.restore_backup(app, old)
    assert report.from_schema == 0 and report.to_schema == LATEST_VERSION
    with app.state.engine.connect() as conn:
        tags = [r[0] for r in conn.exec_driver_sql("SELECT asset_tag FROM components ORDER BY id")]
    assert tags[0] == "C-000001"


def test_restore_invalid_leaves_data_untouched(app, settings, db, tmp_path):
    db.add(Component(name="Resta", attributes={}))
    db.commit()
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"garbage" * 500)
    with pytest.raises(backup.BackupError):
        backup.restore_backup(app, junk)
    with app.state.engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM components WHERE name='Resta'").scalar() == 1


def test_page_and_export_download(client):
    assert "Backup" in client.get("/backups").text
    r = client.get("/backups/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"


def test_restore_requires_critical(client, settings, op_id):
    snap = backup.export_zip(settings)
    files = {"file": ("b.zip", snap.read_bytes(), "application/zip")}
    assert client.post("/backups/restore", files=files, headers=FETCH).status_code == 428
    token = client.post("/sign/password", json={"operator_id": op_id, "password": "segreto1",
                                                "action": "POST /backups/restore"}, headers=FETCH).json()
    r = client.post("/backups/restore", files={"file": ("b.zip", io.BytesIO(snap.read_bytes()), "application/zip")},
                    headers={**FETCH, "X-Sig-Token": token["action_token"]})
    assert r.status_code == 200 and r.json()["redirect"] == "/backups"
