import pytest
from fastapi.testclient import TestClient

from app.models import AuditLog, Component, Machine, Movement, Operator
from tests.helpers import FETCH, critical_post, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def op_id(client, db):
    return db.query(Operator).one().id


def new_component(client, **data):
    body = {"name": "RTX 3060", "category": "GPU", "status": "stock", "quantity": "1", **data}
    r = client.post("/components/new", data=body, headers=FETCH)
    assert r.status_code == 200, r.text
    return int(r.json()["redirect"].rsplit("/", 1)[1])


def test_write_requires_signature(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        r = c.post("/components/new", data={"name": "X"}, headers=FETCH)
        assert r.status_code == 428


def test_create_component_signed_and_audited(client, db, op_id):
    cid = new_component(client)
    comp = db.get(Component, cid)
    assert comp.created_by == op_id and comp.asset_tag == f"C-{cid:06d}"
    log = db.query(AuditLog).filter_by(entity_type="component", entity_id=cid).one()
    assert log.action == "create" and log.operator_id == op_id and log.signature_id
    mv = db.query(Movement).filter_by(component_id=cid).one()
    assert mv.operator_id == op_id and mv.signature_id == log.signature_id


def test_edit_audits_only_changes(client, db):
    cid = new_component(client)
    client.post(f"/components/{cid}/edit",
                data={"name": "RTX 3060", "category": "GPU", "status": "faulty", "quantity": "1"}, headers=FETCH)
    log = db.query(AuditLog).filter_by(entity_type="component", action="update").one()
    assert log.before == {"status": "stock"} and log.after == {"status": "faulty"}


def test_delete_is_soft_and_hidden(client, db, op_id):
    cid = new_component(client, name="Da cancellare")
    r = critical_post(client, f"/components/{cid}/delete", op_id)
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Component, cid).deleted_at is not None
    client.get("/movements")  # consuma il messaggio flash che contiene il nome
    assert "Da cancellare" not in client.get("/components").text
    assert "Da cancellare" in client.get("/trash").text


def test_restore(client, db, op_id):
    cid = new_component(client, name="Torna")
    critical_post(client, f"/components/{cid}/delete", op_id)
    client.post(f"/trash/component/{cid}/restore", headers=FETCH)
    db.expire_all()
    assert db.get(Component, cid).deleted_at is None


def test_purge_requires_critical(client, db, op_id):
    cid = new_component(client, name="Via")
    critical_post(client, f"/components/{cid}/delete", op_id)
    r = client.post(f"/trash/component/{cid}/purge", headers=FETCH)
    assert r.status_code == 428 and r.json()["critical"] is True
    critical_post(client, f"/trash/component/{cid}/purge", op_id)
    db.expire_all()
    assert db.get(Component, cid) is None


def test_machine_delete_returns_components_with_movements(client, db, op_id):
    r = client.post("/machines/new", data={"name": "Server"}, headers=FETCH)
    mid = int(r.json()["redirect"].rsplit("/", 1)[1])
    assert db.get(Machine, mid).asset_tag == f"M-{mid:03d}"
    cid = new_component(client, machine_id=str(mid))
    assert db.get(Component, cid).status == "in_use"
    critical_post(client, f"/machines/{mid}/delete", op_id)
    db.expire_all()
    comp = db.get(Component, cid)
    assert comp.machine_id is None and comp.status == "stock"
    assert db.get(Machine, mid).deleted_at is not None
    moved = db.query(Movement).filter_by(component_id=cid, action="moved").one()
    assert moved.from_machine == "Server" and moved.operator_id == op_id


def test_duplicate_resets_unique_fields(client, db):
    cid = new_component(client, serial_number="SN1", object_code="INV-1")
    r = client.post(f"/components/{cid}/duplicate", headers=FETCH)
    new_id = int(r.json()["redirect"].split("/")[2])
    dup = db.get(Component, new_id)
    assert dup.serial_number == "" and dup.object_code == "" and dup.asset_tag == f"C-{new_id:06d}"


def test_dashboard_excludes_deleted(client, db, op_id):
    cid = new_component(client, name="Nascosto")
    critical_post(client, f"/components/{cid}/delete", op_id)
    client.get("/movements")  # consuma il messaggio flash che contiene il nome
    assert "Nascosto" not in client.get("/").text
