"""Test per i problemi trovati nella revisione finale."""
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Category, CategoryField, Component, Operator, OutboxItem, TestRun, Webhook
from app.services import audit, backup, outbox
from tests.helpers import FETCH, critical_post, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


def _field(db, category, key):
    return db.query(CategoryField).join(Category).filter(Category.name == category, CategoryField.key == key).one()


# 1. Valori storici v1.1.1 fuori dalle scelte / non numerici non devono sparire modificando altro
def test_edit_keeps_legacy_offlist_choice_and_text_number(client, db):
    comp = Component(name="SSD vecchio", category="SSD", attributes={"Interfaccia": "NVMe", "Capacita (GB)": "1TB"})
    db.add(comp)
    db.commit()
    html = client.get(f"/components/{comp.id}/edit").text
    iface, cap = _field(db, "SSD", "Interfaccia"), _field(db, "SSD", "Capacita (GB)")
    assert re.search(r'<option value="NVMe" selected>', html)
    r = client.post(f"/components/{comp.id}/edit", data={
        "name": "SSD vecchio", "category": "SSD", "status": "stock", "tracking": "serial", "notes": "solo note",
        f"cf_{iface.id}": "NVMe", f"cf_{cap.id}": "1TB"}, headers=FETCH)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Component, comp.id).attributes == {"Interfaccia": "NVMe", "Capacita (GB)": "1TB"}


# 2. Eliminazione definitiva di un elemento collegato: 409 chiaro, non 500
def test_purge_with_dependents_refused(client, db):
    comp = Component(name="Testato", attributes={})
    db.add(comp)
    db.flush()
    db.add(TestRun(component_id=comp.id, result="pass"))
    db.commit()
    op = db.query(Operator).one()
    critical_post(client, f"/components/{comp.id}/delete", op.id)
    r = critical_post(client, f"/trash/component/{comp.id}/purge", op.id)
    assert r.status_code == 409 and "collegat" in r.json()["message"]
    db.expire_all()
    assert db.get(Component, comp.id) is not None


# 3. Ripristino fallito: anche gli allegati tornano com'erano
def test_failed_restore_puts_uploads_back(app, client, monkeypatch):
    settings = app.state.settings
    (settings.uploads_dir / "2026").mkdir(parents=True)
    (settings.uploads_dir / "2026" / "mio.txt").write_text("attuale")
    snap = backup.export_zip(settings)
    (settings.uploads_dir / "2026" / "mio.txt").write_text("attuale-modificato")

    def boom(*a, **k):
        raise RuntimeError("migrazione rotta")

    monkeypatch.setattr(backup, "run_migrations", boom)
    with pytest.raises(backup.BackupError):
        backup.restore_backup(app, snap)
    assert (settings.uploads_dir / "2026" / "mio.txt").read_text() == "attuale-modificato"


# 4. L'audit prende il lock di scrittura prima di leggere l'ultimo hash (niente catene biforcate)
def test_audit_record_locks_before_reading_last_hash(app, client):
    from sqlalchemy import event

    statements = []

    def spy(conn, cursor, statement, params, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    event.listen(app.state.engine, "before_cursor_execute", spy)
    try:
        with Session(bind=app.state.engine) as db:
            audit.record(db, entity_type="x", entity_id=1, action="create", after={})
            other = sqlite3.connect(app.state.settings.db_path, timeout=0)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
            other.close()
            db.commit()
    finally:
        event.remove(app.state.engine, "before_cursor_execute", spy)
    first_select = statements.index("SELECT")
    assert any(s in ("UPDATE", "INSERT", "DELETE") for s in statements[:first_select]), statements


# 10. Invio di prova webhook: la riga in coda e' gia' salvata (nessun lock tenuto durante l'HTTP)
def test_webhook_test_commits_before_delivery(client, db, app, monkeypatch):
    hook = Webhook(name="d", kind="discord", url="https://discord.com/api/webhooks/1/x", events=["stock.low"],
                   enabled=True)
    db.add(hook)
    db.commit()
    seen = []

    async def fake(dbs, item, http, now):
        with Session(bind=app.state.engine) as other:
            seen.append(other.query(OutboxItem).count())
        item.status = "sent"

    monkeypatch.setattr(outbox, "deliver_one", fake)
    client.post(f"/webhooks/{hook.id}/test", headers=FETCH)
    assert seen == [1]


# 14. Redirect di ritorno senza firma: mai verso un altro host
def test_signature_redirect_never_offsite(client):
    client.post("/sign/logout", headers=FETCH)
    r = client.post("/machines/new", data={"name": "X"},
                    headers={"Referer": "http://testserver//evil.example/x"}, follow_redirects=False)
    assert r.status_code == 303 and not r.headers["location"].startswith("//")
