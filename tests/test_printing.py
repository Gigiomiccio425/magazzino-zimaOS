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
    assert "Foglio unico ottimizzato" in client.get("/print").text
    html = client.get("/print?mode=separate&sheet=flag&diam=8").text
    assert "Bandiere per cavi" in html and "giro 29 mm" in html and "pflag__wrap" in html
    sheets = client.get("/print/sheets").text  # predefinito: foglio unico ottimizzato
    assert sheets.count('class="sheet sheet--cuts"') == 1 and "C-000002" in sheets and "<svg" in sheets
    separate = client.get("/print/sheets?mode=separate").text
    assert separate.count('class="sheet sheet--cuts"') == 2  # un foglio etichette + un foglio bandiere


def test_next_param_cannot_redirect_offsite(client, db, parts):
    r = client.post("/print/add", data={"entity_type": "component", "id": str(parts[0].id),
                                        "next": "//evil.example/x"}, headers=FETCH)
    assert r.json()["redirect"] == "/print"


def test_menu_shows_queue_count(client, db, parts):
    client.post("/print/add", data={"entity_type": "component", "ids": [str(p.id) for p in parts]}, headers=FETCH)
    assert 'class="nav__count">3<' in client.get("/components").text


def _entry(fmt, copies, n=1):
    return printing.Entry(n, "component", n, f"C-{n:06d}", "Pezzo", "A-01", "", fmt, copies)


def _overlap(a, b):
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def test_pack_mixed_fits_page_without_overlaps():
    entries = [_entry("label", 10, 1), _entry("qr", 12, 2), _entry("flag", 9, 3)]
    pages = printing.pack(entries, 6)
    placed = [pl for page in pages for pl in page]
    assert len(placed) == 31  # tutte le copie
    for page in pages:
        for pl in page:
            assert pl.x >= printing.MIX_MARGIN and pl.y >= printing.MIX_MARGIN
            assert pl.x + pl.w <= printing.A4_W - printing.MIX_MARGIN + 1e-6
            assert pl.y + pl.h <= printing.A4_H - printing.MIX_MARGIN + 1e-6
        for i, a in enumerate(page):
            assert not any(_overlap(a, b) for b in page[i + 1:])
    assert len(pages) < printing.separate_page_count(entries, 6)  # 3 fogli separati -> meno con il misto


def test_pack_fills_gaps_next_to_labels_with_qr():
    pages = printing.pack([_entry("label", 2, 1), _entry("qr", 1, 2)], 6)
    assert len(pages) == 1
    label_row = {round(pl.y, 2) for pl in pages[0] if pl.format == "label"}
    qr = next(pl for pl in pages[0] if pl.format == "qr")
    assert round(qr.y, 2) in label_row  # il QR entra nel resto della riga delle etichette


def test_pack_many_copies_spill_to_new_pages():
    pages = printing.pack([_entry("label", 50, 1)], 6)
    per_page = len(pages[0])
    assert per_page == 14 and len(pages) == 4  # 2 per riga x 7 righe con bordi e spazi di taglio
