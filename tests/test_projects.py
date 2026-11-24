import pytest
from fastapi.testclient import TestClient

from app.models import Component, Machine, Movement, Project
from app.services.inventory import available_quantity
from tests.helpers import FETCH, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def stuff(client, db):
    m = Machine(name="PC nuovo", asset_tag="M-001")
    gpu = Component(name="RTX", asset_tag="C-000001", tracking="serial", status="tested_ok", attributes={})
    cables = Component(name="Cavi SATA", asset_tag="C-000002", tracking="quantity", quantity=10, attributes={})
    db.add_all([m, gpu, cables])
    db.commit()
    return {"m": m, "gpu": gpu, "cables": cables}


def new_project(client, stuff):
    r = client.post("/projects/new", data={"name": "Build gaming", "description": "",
                                           "target_machine_id": str(stuff["m"].id)}, headers=FETCH)
    assert r.status_code == 200, r.text
    return int(r.json()["redirect"].rsplit("/", 1)[1])


def add(client, pid, comp, qty=1):
    return client.post(f"/projects/{pid}/items", data={"component_id": str(comp.id), "qty": str(qty)}, headers=FETCH)


def test_reserve_serial_and_cancel_restores(client, db, stuff):
    pid = new_project(client, stuff)
    assert add(client, pid, stuff["gpu"]).status_code == 200
    db.expire_all()
    assert db.get(Component, stuff["gpu"].id).status == "reserved"
    client.post(f"/projects/{pid}/cancel", headers=FETCH)
    db.expire_all()
    assert db.get(Component, stuff["gpu"].id).status == "tested_ok"
    assert db.get(Project, pid).status == "cancelled"


def test_reserve_quantity_reduces_available(client, db, stuff):
    pid = new_project(client, stuff)
    add(client, pid, stuff["cables"], 4)
    db.expire_all()
    cables = db.get(Component, stuff["cables"].id)
    assert cables.quantity == 10 and available_quantity(db, cables) == 6


def test_over_reservation_refused(client, db, stuff):
    pid = new_project(client, stuff)
    add(client, pid, stuff["cables"], 8)
    pid2 = new_project(client, stuff)
    assert add(client, pid2, stuff["cables"], 3).status_code == 422
    assert add(client, pid2, stuff["gpu"]).status_code == 200
    pid3 = new_project(client, stuff)
    assert add(client, pid3, stuff["gpu"]).status_code == 422  # gia' riservato


def test_complete_build(client, db, stuff):
    pid = new_project(client, stuff)
    add(client, pid, stuff["gpu"])
    add(client, pid, stuff["cables"], 4)
    assert client.post(f"/projects/{pid}/complete", headers=FETCH).status_code == 200
    db.expire_all()
    gpu, cables = db.get(Component, stuff["gpu"].id), db.get(Component, stuff["cables"].id)
    assert (gpu.machine_id, gpu.status) == (stuff["m"].id, "in_use")
    assert cables.quantity == 6 and available_quantity(db, cables) == 6
    assert db.get(Project, pid).status == "done"
    assert db.query(Movement).filter_by(component_id=cables.id, action="qty").one().qty_delta == -4


def test_pages(client, stuff):
    pid = new_project(client, stuff)
    assert "Build gaming" in client.get("/projects").text
    assert "PC nuovo" in client.get(f"/projects/{pid}").text
