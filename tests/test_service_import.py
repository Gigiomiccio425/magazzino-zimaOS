"""Import dei servizi da JSON (elenco app di Umbrel)."""
import json

import pytest
from fastapi.testclient import TestClient

from app.models import AuditLog, Machine, Operator, Service, ServiceModule
from tests.helpers import FETCH, critical_post, get_csrf, sign_new

DATA = {
    "machine": {"name": "main", "kind": "Server", "hostname": "umbrel", "ip_address": "192.168.1.77",
                "os": "umbrelOS 2.0.1"},
    "services": [
        {"name": "Immich", "url": "http://umbrel.local:2283", "description": "Foto",
         "runbook_md": "## Note", "modules": [{"name": "server", "kind": "web", "current_version": "v3.4.2"},
                                              {"name": "database", "kind": "boh"}]},
        {"name": "Kan", "status": "maintenance", "url": "javascript:alert(1)"},
    ],
}


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def op_id(client, db):
    return db.query(Operator).one().id


def _import(client, op_id, data=DATA):
    return critical_post(client, "/services/import", op_id, {"json": json.dumps(data)})


def test_requires_critical_signature(client, db):
    r = client.post("/services/import", data={"json": json.dumps(DATA)}, headers=FETCH)
    assert r.status_code == 428
    assert db.query(Service).count() == 0


def test_creates_machine_services_and_modules(client, db, op_id):
    r = _import(client, op_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == ["Immich", "Kan"] and body["warnings"]
    main = db.query(Machine).one()
    assert main.name == "main" and main.asset_tag == "M-%03d" % main.id and main.ip_address == "192.168.1.77"
    immich = db.query(Service).filter_by(name="Immich").one()
    assert immich.machine_id == main.id and immich.url == "http://umbrel.local:2283"
    kinds = sorted((m.name, m.kind) for m in db.query(ServiceModule).filter_by(service_id=immich.id))
    assert kinds == [("database", "altro"), ("server", "web")]
    kan = db.query(Service).filter_by(name="Kan").one()
    assert kan.url == "" and kan.status == "maintenance"
    assert db.query(AuditLog).filter_by(entity_type="service", action="create").count() == 2


def test_existing_untouched_and_machine_reused(client, db, op_id):
    pc = Machine(name="Main", asset_tag="M-009", description="già qui")
    db.add(pc)
    db.add(Service(slug="immich", name="immich", description="mia descrizione"))
    db.add(Service(slug="kan", name="Kan", description="altro"))
    db.commit()
    other = Machine(name="Altro")
    db.add(other)
    db.flush()
    db.query(Service).filter_by(slug="kan").one().machine_id = other.id
    db.commit()
    body = _import(client, op_id).json()
    assert body["created"] == [] and body["linked"] == ["immich"] and body["skipped"] == ["Kan"]
    db.expire_all()
    assert db.query(Machine).count() == 2 and db.get(Machine, pc.id).description == "già qui"
    immich = db.query(Service).filter_by(slug="immich").one()
    assert immich.description == "mia descrizione" and immich.machine_id == pc.id
    assert db.query(Service).filter_by(slug="kan").one().machine_id == other.id
    assert db.query(ServiceModule).count() == 0


def test_second_import_is_noop(client, db, op_id):
    _import(client, op_id)
    body = _import(client, op_id).json()
    assert body["created"] == [] and sorted(body["skipped"]) == ["Immich", "Kan"]
    assert db.query(Service).count() == 2 and db.query(Machine).count() == 1


@pytest.mark.parametrize("payload", ["non json", "[]", '{"services": []}', '{"services": "x"}'])
def test_invalid_json_refused(client, db, op_id, payload):
    r = critical_post(client, "/services/import", op_id, {"json": payload})
    assert r.status_code == 422
    assert db.query(Service).count() == 0 and db.query(Machine).count() == 0


def test_trashed_machine_refused_without_changes(client, db, op_id):
    from app.timeutil import utcnow

    db.add(Machine(name="main", deleted_at=utcnow()))
    db.commit()
    r = _import(client, op_id)
    assert r.status_code == 422 and "cestino" in r.json()["message"]
    assert db.query(Service).count() == 0


def test_file_upload_and_page(client, db, op_id):
    assert "Importa servizi" in client.get("/services/import").text
    from tests.helpers import sign_as

    token = sign_as(client, op_id, action="POST /services/import")["action_token"]
    r = client.post("/services/import", files={"file": ("app.json", json.dumps(DATA).encode(), "application/json")},
                    headers={**FETCH, "X-Sig-Token": token})
    assert r.status_code == 200 and db.query(Service).count() == 2
