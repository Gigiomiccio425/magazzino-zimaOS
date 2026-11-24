import pytest
from fastapi.testclient import TestClient

from app.models import Component, Location, Machine, Operator
from app.services.locations import descendant_ids, location_options, location_path, would_cycle
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


def new_loc(client, name, parent=None, kind="altro"):
    r = client.post("/locations/new", data={"name": name, "kind": kind, "parent_id": str(parent or "")}, headers=FETCH)
    assert r.status_code == 200, r.text
    return int(r.json()["redirect"].rsplit("/", 1)[1])


def test_nested_path(client, db):
    g = new_loc(client, "Garage", kind="stanza")
    s = new_loc(client, "Scaffale A", g, "scaffale")
    b = new_loc(client, "Box 3", s, "box")
    assert location_path(db.get(Location, b)) == "Garage › Scaffale A › Box 3"
    assert sorted(descendant_ids(db, g)) == sorted([g, s, b])
    assert [label for _, label in location_options(db)] == ["Garage", "Garage › Scaffale A", "Garage › Scaffale A › Box 3"]


def test_tag_assigned(client, db):
    lid = new_loc(client, "Studio")
    assert db.get(Location, lid).asset_tag == f"L-{lid:04d}"


def test_cycle_refused(client, db):
    a = new_loc(client, "A")
    b = new_loc(client, "B", a)
    assert would_cycle(db, a, b) and would_cycle(db, a, a) and not would_cycle(db, b, None)
    r = client.post(f"/locations/{a}/edit", data={"name": "A", "kind": "altro", "parent_id": str(b)}, headers=FETCH)
    assert r.status_code == 422


def test_delete_nonempty_refused(client, db, op_id):
    a = new_loc(client, "Piena")
    new_loc(client, "Figlia", a)
    assert critical_post(client, f"/locations/{a}/delete", op_id).status_code == 409
    e = new_loc(client, "Vuota")
    assert critical_post(client, f"/locations/{e}/delete", op_id).status_code == 200
    db.expire_all()
    assert db.get(Location, e).deleted_at is not None


def test_detail_includes_children_items(client, db):
    a = new_loc(client, "Garage")
    b = new_loc(client, "Box", a)
    db.add(Component(name="Cavo nel box", location_id=b, attributes={}))
    db.commit()
    html = client.get(f"/locations/{a}").text
    assert "Cavo nel box" in html and "Box" in html


def test_machine_location_saved(client, db):
    a = new_loc(client, "Rack")
    r = client.post("/machines/new", data={"name": "Server", "location_id": str(a), "hostname": "umbrel",
                                            "ip_address": "192.168.1.10", "os": "umbrelOS"}, headers=FETCH)
    mid = int(r.json()["redirect"].rsplit("/", 1)[1])
    m = db.get(Machine, mid)
    assert (m.location_id, m.hostname, m.ip_address, m.os) == (a, "umbrel", "192.168.1.10", "umbrelOS")
