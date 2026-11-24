"""2.0.1: correzioni dei punti minori rimandati dalla revisione finale."""
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.migrations.runner import LATEST_VERSION, MigrationError, run_migrations
from app.models import Attachment, Component, Machine, Operator, OperatorCredential, Service, Webhook
from app.services import csv_io, uploads, webauthn_svc
from app.services.signing import normalize_name
from tests.helpers import FETCH, critical_post, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def op(client, db):
    return db.query(Operator).one()


# 6. credenziale sconosciuta rifiutata anche se l'operatore ne ha una sola
def test_unknown_credential_id_refused(client, db, op, monkeypatch):
    db.add(OperatorCredential(operator_id=op.id, credential_id=b"giusta", public_key=b"pk", rp_id="testserver"))
    db.commit()
    monkeypatch.setattr(webauthn_svc, "verify_authentication", lambda *a, **k: 1)
    client.post("/sign/passkey/auth/begin", json={"operator_id": op.id}, headers=FETCH)
    r = client.post("/sign/passkey/auth/finish", json={"credential": {"id": "c2JhZ2xpYXRh"}}, headers=FETCH)
    assert r.status_code == 400


# 7. stato di massa con la stessa regola della scheda singola
def test_bulk_status_keeps_machine_rule(client, db):
    m = Machine(name="PC", asset_tag="M-001")
    db.add(m)
    db.flush()
    mounted = Component(name="Montato", machine_id=m.id, status="in_use", attributes={})
    loose = Component(name="Sfuso", status="stock", attributes={})
    db.add_all([mounted, loose])
    db.commit()
    client.post("/components/bulk", data={"ids": [str(loose.id)], "action": "set_status", "status": "in_use"},
                headers=FETCH)
    db.expire_all()
    assert db.get(Component, loose.id).status == "stock"  # "in uso" senza macchina non ha senso


# 8. import CSV: macchina inesistente = errore, non smontaggio silenzioso
def test_import_unknown_machine_is_error(client, db):
    plan = csv_io.plan_import(db, "name;machine\nGPU;Macchina che non esiste\n")
    assert plan.rows[0].action == "error" and "macchina" in plan.rows[0].errors[0].lower()


# 9a. import CSV: i valori restano testo (niente "007" -> 7)
def test_import_keeps_attribute_text(client, db, op):
    c = Component(name="Cavo", asset_tag="C-000001", attributes={"Codice": "007"})
    db.add(c)
    db.commit()
    plan = csv_io.plan_import(db, "asset_tag;name;attr:Codice;attr:Lunghezza (m)\nC-000001;Cavo;007;2\n")
    from app.services.signing import SignerInfo

    csv_io.apply_import(db, plan, SignerInfo(op.id, op.name, True, None, 0))
    db.commit()
    db.expire_all()
    assert db.get(Component, c.id).attributes == {"Codice": "007", "Lunghezza (m)": "2"}


# 9b. export CSV protetto dalle formule di Excel, e l'import le riconosce
def test_export_escapes_formulas_and_roundtrip(client, db):
    db.add(Component(name="=HYPERLINK(\"x\")", asset_tag="C-000001", notes="+1", attributes={}))
    db.commit()
    text = client.get("/components/export.csv").content.decode("utf-8")
    assert "'=HYPERLINK" in text and ";'+1" in text
    assert [r.action for r in csv_io.plan_import(db, text).rows] == ["unchanged"]


# 11. webhook: solo gli amministratori possono configurarli
def test_webhook_create_admin_only(client, db, op):
    sign_new(client, "Dany", "segreto2")
    dany = db.query(Operator).filter_by(name="Dany").one()
    data = {"name": "X", "kind": "generic", "url": "http://192.168.1.10:5678/hook", "events": ["stock.low"]}
    assert critical_post(client, "/webhooks/new", dany.id, data, password="segreto2").status_code == 403
    assert critical_post(client, "/webhooks/new", op.id, data).status_code == 200
    assert db.query(Webhook).count() == 1


# 12a. token di azione critica: non riusabile neanche ripresentando un cookie vecchio
def test_action_token_single_use_even_with_old_cookie(client, op):
    token = client.post("/sign/password", json={"operator_id": op.id, "password": "segreto1",
                                                "action": "POST /settings"}, headers=FETCH).json()["action_token"]
    old_cookies = dict(client.cookies)
    data = {"signature_window_min": "10", "audit_interval_days": "180", "public_base_url": ""}
    assert client.post("/settings", data=data, headers={**FETCH, "X-Sig-Token": token}).status_code == 200
    client.cookies.clear()
    for k, v in old_cookies.items():
        client.cookies.set(k, v)
    assert client.post("/settings", data=data, headers={**FETCH, "X-Sig-Token": token}).status_code == 428


# 12b. "Esci" non annullabile ripresentando il cookie di prima
def test_logout_not_undone_by_old_cookie(client, op):
    old_cookies = dict(client.cookies)
    client.post("/sign/logout", headers=FETCH)
    client.cookies.clear()
    for k, v in old_cookies.items():
        client.cookies.set(k, v)
    assert client.get("/sign/state").json()["signed"] is False


# 15a. data scritta male: 422, non 500
def test_bad_datetime_is_422(client, db):
    s = Service(slug="a", name="A")
    db.add(s)
    db.commit()
    r = client.post(f"/services/{s.id}/changes", data={"title": "X", "occurred_at": "ieri sera"}, headers=FETCH)
    assert r.status_code == 422
    r = client.post("/incidents/new", data={"title": "X", "started_at": "boh"}, headers=FETCH)
    assert r.status_code == 422


# 15b. immagine "bomba" rifiutata, niente file orfani
def test_decompression_bomb_rejected_without_orphans(client, db, app, monkeypatch):
    comp = Component(name="GPU", attributes={})
    db.add(comp)
    db.commit()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, "PNG")
    files = [("files", ("ok.txt", b"ciao", "text/plain")), ("files", ("bomba.png", buf.getvalue(), "image/png"))]
    r = client.post("/attachments", data={"entity_type": "component", "entity_id": str(comp.id)}, files=files,
                    headers=FETCH)
    assert r.status_code == 415
    assert db.query(Attachment).count() == 0
    up = app.state.settings.uploads_dir
    assert not up.exists() or not [f for f in up.rglob("*") if f.is_file()]


# 15c. allegato verso un elemento inesistente rifiutato
def test_attachment_to_missing_entity_refused(client):
    r = client.post("/attachments", data={"entity_type": "component", "entity_id": "9999"},
                    files={"files": ("a.txt", b"x", "text/plain")}, headers=FETCH)
    assert r.status_code == 404


# 15d. nomi operatore con accenti scritti in modo diverso = stesso operatore
def test_operator_name_unicode_normalized():
    assert normalize_name("Niccolò")[1] == normalize_name("Niccolò")[1]


# 15e. database di una versione futura dell'app: rifiutato, file intatto
def test_newer_schema_refused(tmp_path):
    db = tmp_path / "m.db"
    run_migrations(db, tmp_path / "b")
    sqlite3.connect(db).execute(f"PRAGMA user_version = {LATEST_VERSION + 5}")
    with pytest.raises(MigrationError, match="più recente"):
        run_migrations(db, tmp_path / "b")
