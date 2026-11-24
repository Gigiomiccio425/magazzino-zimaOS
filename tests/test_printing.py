"""Zona stampa: coda multipla, formati (etichetta, solo QR, bandiera per cavi), impaginazione A4."""
import pytest
from fastapi.testclient import TestClient

from app.models import Component, Location, Machine, PrintItem
from app.services import printing
from tests.helpers import FETCH, get_csrf


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        yield c


@pytest.fixture
def parts(db):
    shelf = Location(name="B-01-1", asset_tag="L-0001")
    db.add(shelf)
    db.flush()
    items = [
        Component(name="Cavo HDMI 2.1, 2 m", category="Cavo", asset_tag="C-000001", location_id=shelf.id, attributes={}),
        Component(name="RTX 3080", category="GPU", asset_tag="C-000002", attributes={}),
        Component(name="RAM DDR4 16 GB", category="RAM", asset_tag="C-000003", attributes={}),
    ]
    db.add_all(items)
    db.commit()
    return items


def test_wrap_length_and_flag_geometry():
    assert printing.wrap_length(6) == 23
    thin, thick = printing.sheet_geometry("flag", 6), printing.sheet_geometry("flag", 14)
    assert thin.cell_w == 95 and thin.cols == 2
    assert thick.cols == 1  # cavo grosso: striscia più lunga, una colonna
    assert printing.clamp_diameter("99") == printing.DIAM_MAX and printing.clamp_diameter("x") == printing.DIAM_DEFAULT


def test_bulk_add_uses_cable_default_and_format(client, db, parts):
    ids = [str(p.id) for p in parts]
    r = client.post("/print/add", data={"entity_type": "component", "ids": ids, "next": "/components"}, headers=FETCH)
    assert r.json()["redirect"] == "/components"
    formats = {db.get(Component, i.entity_id).name: i.format for i in db.query(PrintItem)}
    assert formats == {"Cavo HDMI 2.1, 2 m": "flag", "RTX 3080": "label", "RAM DDR4 16 GB": "label"}
    client.post("/print/add", data={"entity_type": "component", "ids": ids[1:], "format": "qr"}, headers=FETCH)
    assert db.query(PrintItem).count() == 3  # nessun doppione, solo formato aggiornato
    assert {i.format for i in db.query(PrintItem).filter(PrintItem.entity_id != parts[0].id)} == {"qr"}


def test_add_location_and_machine(client, db, parts):
    m = Machine(name="main", asset_tag="M-001")
    db.add(m)
    db.commit()
    client.post("/print/add", data={"entity_type": "location", "id": "1"}, headers=FETCH)
    client.post("/print/add", data={"entity_type": "machine", "id": str(m.id)}, headers=FETCH)
    assert sorted(i.entity_type for i in db.query(PrintItem)) == ["location", "machine"]


def test_update_copies_format_remove_clear(client, db, parts):
    client.post("/print/add", data={"entity_type": "component", "ids": [str(parts[1].id)]}, headers=FETCH)
    item = db.query(PrintItem).one()
    client.post(f"/print/item/{item.id}", data={"copies": "5"}, headers=FETCH)
    client.post(f"/print/item/{item.id}", data={"copies": "500"}, headers=FETCH)
    client.post(f"/print/item/{item.id}", data={"format": "flag"}, headers=FETCH)
    db.expire_all()
    assert (item.copies, item.format) == (printing.MAX_COPIES, "flag")
    client.post("/print/all", data={"format": "qr"}, headers=FETCH)
    db.expire_all()
    assert item.format == "qr"
    client.post(f"/print/item/{item.id}/remove", headers=FETCH)
    assert db.query(PrintItem).count() == 0
    client.post("/print/add", data={"entity_type": "component", "ids": [str(p.id) for p in parts]}, headers=FETCH)
    client.post("/print/clear", headers=FETCH)
    assert db.query(PrintItem).count() == 0


def test_layout_copies_pages_and_start(db, parts):
    entries = [printing.Entry(1, "component", 1, "C-000001", "Cavo", "B-01-1", "", "flag", 30)]
    sheet = printing.layout(entries, "flag", 6, start=1)
    assert sheet.per_page == 24 and len(sheet.pages) == 2
    assert sum(1 for s in sheet.pages[0] if s) == 24 and sum(1 for s in sheet.pages[1] if s) == 6
    shifted = printing.layout(entries, "flag", 6, start=20)
    assert shifted.pages[0][:19] == [None] * 19 and len(shifted.pages) == 3  # 19 saltate + 30 = 49 caselle
    assert printing.layout(entries, "label").pages == []


def test_deleted_items_skipped(client, db, parts):
    from app.timeutil import utcnow

    client.post("/print/add", data={"entity_type": "component", "ids": [str(p.id) for p in parts]}, headers=FETCH)
    parts[2].deleted_at = utcnow()
    db.commit()
    assert [e.tag for e in printing.queue_entries(db)] == ["C-000001", "C-000002"]


def test_print_pages_render(client, db, parts):
    assert "La coda è vuota" in client.get("/print").text
    client.post("/print/add", data={"entity_type": "component", "ids": [str(p.id) for p in parts]}, headers=FETCH)
    html = client.get("/print?sheet=flag&diam=8").text
    assert "Bandiere per cavi" in html and "giro 29 mm" in html and "pflag__wrap" in html
    sheets = client.get("/print/sheets").text
    assert sheets.count('class="sheet sheet--') == 2  # un foglio etichette + un foglio bandiere
    assert "C-000002" in sheets and "<svg" in sheets


def test_next_param_cannot_redirect_offsite(client, db, parts):
    r = client.post("/print/add", data={"entity_type": "component", "id": str(parts[0].id),
                                        "next": "//evil.example/x"}, headers=FETCH)
    assert r.json()["redirect"] == "/print"


def test_menu_shows_queue_count(client, db, parts):
    client.post("/print/add", data={"entity_type": "component", "ids": [str(p.id) for p in parts]}, headers=FETCH)
    assert 'class="nav__count">3<' in client.get("/components").text
