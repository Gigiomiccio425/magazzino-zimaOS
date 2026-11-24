import io

import pytest
from fastapi.testclient import TestClient

from app.models import Component, Location, Movement, Operator
from app.services import csv_io
from tests.helpers import FETCH, critical_post, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def three(client, db):
    comps = [Component(name=f"Cavo {i}", asset_tag=f"C-00000{i}", tracking="quantity", quantity=5,
                       category="Cavo", attributes={"Lunghezza (m)": i}) for i in (1, 2, 3)]
    db.add_all(comps)
    db.commit()
    return comps


def ids(comps):
    return [str(c.id) for c in comps]


def test_bulk_move_location_with_movements(client, db, three):
    loc = Location(name="Box", kind="box", asset_tag="L-0001")
    db.add(loc)
    db.commit()
    r = client.post("/components/bulk", data={"ids": ids(three), "action": "move_location", "location_id": str(loc.id)},
                    headers=FETCH)
    assert r.status_code == 200
    db.expire_all()
    assert {c.location_id for c in db.query(Component)} == {loc.id}
    assert db.query(Movement).filter_by(action="moved").count() == 3


def test_bulk_status(client, db, three):
    client.post("/components/bulk", data={"ids": ids(three[:2]), "action": "set_status", "status": "to_test"},
                headers=FETCH)
    db.expire_all()
    assert [c.status for c in db.query(Component).order_by(Component.id)] == ["to_test", "to_test", "stock"]


def test_bulk_add_tag(client, db, three):
    client.post("/components/bulk", data={"ids": ids(three), "action": "add_tag", "tag": "Scaffale Nuovo"},
                headers=FETCH)
    db.expire_all()
    assert all([t.name for t in c.tags] == ["scaffale nuovo"] for c in db.query(Component))


def test_bulk_delete_critical(client, db, three):
    data = {"ids": ids(three)}
    assert client.post("/components/bulk/delete", data=data, headers=FETCH).status_code == 428
    op = db.query(Operator).one()
    assert critical_post(client, "/components/bulk/delete", op.id, data).status_code == 200
    db.expire_all()
    assert all(c.deleted_at is not None for c in db.query(Component))


def test_export_bom_and_separator(client, three):
    r = client.get("/components/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8")
    assert text.startswith("﻿asset_tag;object_code;name;")
    assert "attr:Lunghezza (m)" in text.splitlines()[0]
    assert "C-000001;" in text


def test_import_plan_actions(db, three):
    text = ("asset_tag;name;status;quantity\n"
            "C-000001;Cavo 1 rinominato;stock;5\n"
            ";Nuovo SSD;stock;1\n"
            ";Senza stato valido;boh;1\n"
            ";;stock;1\n")
    plan = csv_io.plan_import(db, text)
    assert [r.action for r in plan.rows] == ["update", "create", "error", "error"]
    assert plan.rows[0].match == "C-000001"
    assert "stato" in plan.rows[2].errors[0].lower() and "nome" in plan.rows[3].errors[0].lower()


def test_import_apply_creates_locations(client, db):
    text = "name;location_path;tracking;quantity\nViti M3;Garage › Box viti;quantity;200\n"
    files = {"file": ("imp.csv", text.encode("utf-8"), "text/csv")}
    r = client.post("/components/import", files=files, headers=FETCH)
    assert r.status_code == 200 and "redirect" in r.json()
    r = client.post("/components/import/apply", headers=FETCH)
    assert r.status_code == 200
    comp = db.query(Component).filter_by(name="Viti M3").one()
    assert comp.quantity == 200 and comp.asset_tag == f"C-{comp.id:06d}"
    box = db.get(Location, comp.location_id)
    assert box.name == "Box viti" and box.parent.name == "Garage"


def test_export_import_roundtrip_unchanged(client, db, three):
    text = client.get("/components/export.csv").content.decode("utf-8")
    plan = csv_io.plan_import(db, text)
    assert [r.action for r in plan.rows] == ["unchanged"] * 3
