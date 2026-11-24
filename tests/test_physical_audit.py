from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.models import Component, InventoryAudit, InventoryAuditItem, Location, OutboxItem, Webhook
from app.timeutil import utcnow
from tests.helpers import FETCH, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def setup(client, db):
    garage = Location(name="Garage", asset_tag="L-0001")
    db.add(garage)
    db.flush()
    box = Location(name="Box", asset_tag="L-0002", parent_id=garage.id)
    other = Location(name="Studio", asset_tag="L-0003")
    db.add_all([box, other])
    db.flush()
    a = Component(name="GPU", asset_tag="C-000001", location_id=garage.id, attributes={})
    b = Component(name="SSD", asset_tag="C-000002", location_id=box.id, attributes={})
    x = Component(name="RAM altrove", asset_tag="C-000003", location_id=other.id, attributes={})
    db.add_all([a, b, x])
    db.commit()
    return {"garage": garage, "box": box, "other": other, "a": a, "b": b, "x": x}


def start(client, loc, children=True):
    r = client.post("/audits/new", data={"location_id": str(loc.id), "include_children": "1" if children else ""},
                    headers=FETCH)
    assert r.status_code == 200, r.text
    return int(r.json()["redirect"].rsplit("/", 1)[1])


def scan(client, audit_id, value):
    return client.post(f"/audits/{audit_id}/scan", json={"value": value}, headers=FETCH).json()


def test_start_expected_includes_children(client, db, setup):
    aid = start(client, setup["garage"])
    states = {i.component.name: i.state for i in db.query(InventoryAuditItem).filter_by(audit_id=aid)}
    assert states == {"GPU": "expected", "SSD": "expected"}
    aid2 = start(client, setup["garage"], children=False)
    assert {i.component.name for i in db.query(InventoryAuditItem).filter_by(audit_id=aid2)} == {"GPU"}


def test_scan_found(client, db, setup):
    aid = start(client, setup["garage"])
    res = scan(client, aid, "https://mag.example/q/C-000001")
    assert res["state"] == "found" and res["component"] == "GPU"
    assert scan(client, aid, "C-000001")["state"] == "found"  # seconda lettura: nessun doppione
    assert db.query(InventoryAuditItem).filter_by(audit_id=aid).count() == 2


def test_scan_unexpected(client, db, setup):
    aid = start(client, setup["garage"])
    assert scan(client, aid, "C-000003")["state"] == "unexpected"
    assert scan(client, aid, "sconosciuto")["state"] == "unknown"


def test_move_here(client, db, setup):
    aid = start(client, setup["garage"])
    scan(client, aid, "C-000003")
    item = db.query(InventoryAuditItem).filter_by(audit_id=aid, state="unexpected").one()
    client.post(f"/audits/{aid}/items/{item.id}/move-here", headers=FETCH)
    db.expire_all()
    assert db.get(Component, setup["x"].id).location_id == setup["garage"].id
    assert db.get(InventoryAuditItem, item.id).state == "found"


def test_finish_marks_missing_and_dates(client, db, setup):
    db.add(Webhook(name="d", kind="discord", url="https://discord.com/api/webhooks/1/x", events=["audit.completed"],
                   enabled=True))
    db.commit()
    aid = start(client, setup["garage"])
    scan(client, aid, "C-000001")
    assert client.post(f"/audits/{aid}/finish", data={"notify": "1"}, headers=FETCH).status_code == 200
    db.expire_all()
    audit = db.get(InventoryAudit, aid)
    assert audit.status == "done" and audit.summary == {"found": 1, "missing": 1, "unexpected": 0}
    states = {i.component.name: i.state for i in audit.items}
    assert states == {"GPU": "found", "SSD": "missing"}
    assert db.get(Component, setup["a"].id).last_audit_at is not None
    assert db.get(Component, setup["b"].id).last_audit_at is None
    assert db.get(Location, setup["garage"].id).last_audit_at is not None
    assert db.query(OutboxItem).count() == 1
    assert scan(client, aid, "C-000002")["state"] == "closed"


def test_overdue_locations(client, db, setup):
    setup["garage"].last_audit_at = utcnow() - timedelta(days=10)
    setup["other"].last_audit_at = utcnow() - timedelta(days=400)
    db.commit()
    html = client.get("/audits").text
    overdue = html.split('id="overdue"')[1].split("</section>")[0]
    assert f'href="/locations/{setup["other"].id}"' in overdue and f'href="/locations/{setup["box"].id}"' in overdue
    assert f'href="/locations/{setup["garage"].id}"' not in overdue
