"""2.4: fornitori e ordini, riordino, compatibilità, ammortamento, avvisi, report, sedi."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.models import (Category, Component, Location, Machine, Maintenance, OutboxItem, PurchaseOrder, Site,
                        Supplier, SupplierPart, Webhook)
from app.services import alerts, compat, purchasing, valuation
from app.timeutil import utcnow
from tests.helpers import FETCH, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


def _comp(db, **kw):
    data = {"name": "Pezzo", "attributes": {}, "status": "stock"}
    data.update(kw)
    c = Component(**data)
    db.add(c)
    db.commit()
    return c


def test_reorder_and_receive_quantity(client, db):
    cable = _comp(db, name="Cavo HDMI", category="Cavo", tracking="quantity", quantity=2, min_stock=5, unit="pz")
    client.post("/suppliers/new", data={"name": "Amazon", "website": "https://www.amazon.it"}, headers=FETCH)
    sup = db.query(Supplier).one()
    client.post(f"/suppliers/{sup.id}/parts", data={"component_id": str(cable.id), "sku": "B0XYZ", "price": "7,90",
                                                    "preferred": "1"}, headers=FETCH)
    groups = purchasing.reorder_list(db)
    assert list(groups) == [sup.id] and groups[sup.id][0].suggested == 8  # 2*5 - 2
    r = client.post("/orders/new", data={"supplier_id": str(sup.id), "component_id": [str(cable.id)],
                                         f"qty_{cable.id}": "8"}, headers=FETCH)
    order = db.query(PurchaseOrder).one()
    assert r.json()["redirect"] == f"/orders/{order.id}" and order.number.endswith("-0001")
    assert order.lines[0].unit_price == 790
    assert purchasing.reorder_list(db) == {}  # già in ordine: non si suggerisce di nuovo
    assert client.post(f"/orders/{order.id}/receive", data={}, headers=FETCH).status_code == 409  # bozza
    client.post(f"/orders/{order.id}/status", data={"status": "ordered"}, headers=FETCH)
    client.post(f"/orders/{order.id}/receive", data={f"recv_{order.lines[0].id}": "5"}, headers=FETCH)
    db.expire_all()
    assert order.status == "partial" and db.get(Component, cable.id).quantity == 7
    client.post(f"/orders/{order.id}/receive", data={f"recv_{order.lines[0].id}": "9"}, headers=FETCH)
    db.expire_all()
    assert order.status == "received" and db.get(Component, cable.id).quantity == 10  # non oltre l'ordinato


def test_receive_serial_creates_new_cards(client, db):
    gpu = _comp(db, name="RTX 3060", category="GPU", manufacturer="NVIDIA", attributes={"VRAM (GB)": 12},
                asset_tag="C-000001")
    r = client.post("/orders/new", data={"component_id": [str(gpu.id)], f"qty_{gpu.id}": "2"}, headers=FETCH)
    oid = int(r.json()["redirect"].rsplit("/", 1)[1])
    client.post(f"/orders/{oid}/status", data={"status": "ordered"}, headers=FETCH)
    line_id = db.get(PurchaseOrder, oid).lines[0].id
    client.post(f"/orders/{oid}/receive", data={f"recv_{line_id}": "2"}, headers=FETCH)
    new = db.query(Component).filter(Component.id != gpu.id).all()
    assert len(new) == 2 and all(c.status == "to_test" and c.ref_code and c.stock_serial for c in new)
    assert {c.invoice_ref for c in new} == {db.get(PurchaseOrder, oid).number}


def test_compatibility_rules(db):
    m = Machine(name="Desktop")
    board = Component(name="B550", category="Scheda madre", attributes={"Socket": "AM4", "Slot RAM": 2})
    cpu = Component(name="7600", category="CPU", attributes={"Socket": "AM5", "TDP": 65})
    ram = Component(name="RAM", category="RAM", attributes={"Tipo": "SO-DIMM DDR5"}, quantity=1)
    ram2 = Component(name="RAM2", category="RAM", attributes={"Tipo": "DDR4"}, quantity=1)
    gpu = Component(name="4090", category="GPU", attributes={"TDP": 450})
    psu = Component(name="PSU", category="Alimentatore", attributes={"Potenza (W)": 550})
    msgs = [(f.level, f.message) for f in compat.check(m, [board, cpu, ram, ram2, gpu, psu])]
    text = " ".join(x for _, x in msgs)
    assert "socket AM5" in text and "generazioni diverse" in text and "SO-DIMM" in text and "Consumo stimato" in text
    assert compat.check(m, [Component(name="CPU", category="CPU", attributes={"Socket": "AM4"}),
                            Component(name="PSU", category="Alimentatore", attributes={"Potenza (W)": 650})])[0].level == "ok"


def test_machine_page_shows_compat(client, db):
    m = Machine(name="PC", asset_tag="M-001")
    db.add(m)
    db.flush()
    db.add(Component(name="R", category="RAM", attributes={"Tipo": "DDR3"}, machine_id=m.id, status="in_use"))
    db.add(Component(name="C", category="CPU", attributes={"Socket": "AM5"}, machine_id=m.id, status="in_use"))
    db.commit()
    html = client.get(f"/machines/{m.id}").text
    assert "Compatibilità" in html and "usa DDR5" in html


def test_depreciation(db):
    c = Component(name="GPU", category="GPU", purchase_price=60000, purchase_date=date(2024, 1, 15), tracking="serial")
    assert valuation.current_value(c, 36, today=date(2025, 7, 15)) == 30000
    assert valuation.current_value(c, 36, today=date(2030, 1, 1)) == 0
    assert valuation.current_value(Component(name="x", purchase_price=None), 36) is None
    stock = Component(name="viti", purchase_price=10, quantity=100, tracking="quantity")
    assert valuation.current_value(stock, 60) == 1000  # senza data: prezzo pieno x quantità


def test_category_life_and_reports(client, db):
    gpu_cat = db.query(Category).filter_by(name="GPU").one()
    assert gpu_cat.useful_life_months == 36  # predefinito dalla migrazione
    client.post(f"/categories/{gpu_cat.id}/life", data={"months": "24"}, headers=FETCH)
    db.expire_all()
    assert db.get(Category, gpu_cat.id).useful_life_months == 24
    _comp(db, name="RTX", category="GPU", purchase_price=50000, purchase_date=utcnow().date(), status="faulty",
          manufacturer="MSI", model="Ventus")
    html = client.get("/reports").text
    assert "Valore per categoria" in html and "500 €" in html and "Ventus" in html


def test_warranty_and_maintenance_alerts(client, db):
    db.add(Webhook(name="Discord", kind="generic", url="http://192.168.1.10/hook", enabled=True,
                   events=["warranty.expiring", "maintenance.reminder"]))
    _comp(db, name="SSD", warranty_until=utcnow().date() + timedelta(days=10))
    _comp(db, name="Lontana", warranty_until=utcnow().date() + timedelta(days=200))
    db.add(Maintenance(title="Cambio dischi", starts_at=utcnow() + timedelta(hours=5),
                       ends_at=utcnow() + timedelta(hours=6), status="scheduled"))
    db.commit()
    assert alerts.run(db) == 2
    assert sorted(i.event for i in db.query(OutboxItem)) == ["maintenance.reminder", "warranty.expiring"]
    assert alerts.run(db) == 0  # una volta sola
    assert "Scadenze e riordino" in client.get("/").text and "SSD" in client.get("/").text


def test_sites_assign_and_filter(client, db):
    client.post("/sites/new", data={"name": "Cantina"}, headers=FETCH)
    site = db.query(Site).one()
    room = Location(name="Stanza", kind="stanza")
    db.add(room)
    db.flush()
    shelf = Location(name="Scaffale", kind="ripiano", parent_id=room.id)
    db.add(shelf)
    db.flush()
    inside = _comp(db, name="Dentro", location_id=shelf.id)
    _comp(db, name="Fuori")
    client.post("/sites/assign", data={"kind": "location", "id": str(room.id), "site_id": str(site.id)}, headers=FETCH)
    html = client.get(f"/components?site={site.id}").text
    assert inside.name in html and "Fuori" not in html
    assert "Cantina" in client.get("/sites").text


def test_reserve_from_component_page(client, db):
    from app.models import Project

    p = Project(name="Build NAS", status="draft")
    db.add(p)
    db.commit()
    c = _comp(db, name="RAM", category="RAM", asset_tag="C-000009")
    assert "Riserva per" in client.get(f"/components/{c.id}").text
    r = client.post(f"/projects/{p.id}/items", data={"component_id": str(c.id), "next": f"/components/{c.id}"},
                    headers=FETCH)
    assert r.json()["redirect"] == f"/components/{c.id}"
    assert "Build NAS" in client.get(f"/components/{c.id}").text
