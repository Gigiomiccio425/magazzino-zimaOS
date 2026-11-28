"""2.3: modelli pronti, riconoscimento dalla sigla, tag automatici, seriale di magazzino e codice di riferimento."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.migrations.runner import run_migrations
from app.models import Component
from app.services import codes, presets
from tests.helpers import FETCH, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


def test_catalog_covers_ddr1_to_ddr5_and_brands():
    rams = [p for p in presets.PRESETS if p.category == "RAM"]
    gens = {p.attributes["Tipo"].replace("SO-DIMM ", "") for p in rams}
    assert gens == {"DDR", "DDR2", "DDR3", "DDR4", "DDR5"}
    assert sum(p.manufacturer == "Kingston" for p in rams) >= 60
    assert {"Corsair", "Crucial", "G.Skill", "Samsung", "SK Hynix"} <= {p.manufacturer for p in rams}
    assert len({p.id for p in presets.PRESETS}) == len(presets.PRESETS)


@pytest.mark.parametrize("code, tipo, speed, gb, guessed", [
    ("KVR26N19S8/16", "DDR4", 2666, 16, False),            # in elenco
    ("SN:1234 kvr26n19s8/16 LOT 77", "DDR4", 2666, 16, False),  # dentro altro testo, minuscolo
    ("KVR29N21S8/16", "DDR4", 2933, 16, True),              # non in elenco: decodificato
    ("KVR16LS11/4", "SO-DIMM DDR3", 1600, 4, True),
    ("KVR800D2S6/1G", "SO-DIMM DDR2", 800, 1, True),
    ("KVR266X64C25/512", "DDR", 266, 0.5, True),
    ("KVR64U52BS8-16", "DDR5", 6400, 16, True),
    ("KF564C32BBK2-32", "DDR5", 6400, 32, True),
    ("CMK64GX4M2E3200C16", "DDR4", 3200, 64, True),
    ("CT32G56C46S5", "SO-DIMM DDR5", 5600, 32, True),
    ("F4-3600C18D-16GVK", "DDR4", 3600, 16, True),
])
def test_recognize(code, tipo, speed, gb, guessed):
    p = presets.recognize(code)
    assert p is not None and p.guessed is guessed
    assert (p.attributes["Tipo"], p.attributes["Velocita (MHz)"], p.attributes["Capacita (GB)"]) == (tipo, speed, gb)


def test_recognize_unknown():
    assert presets.recognize("4006381333931") is None and presets.recognize("") is None


def test_preset_search_api(client):
    data = client.get("/presets?q=kingston ddr5 so-dimm").json()
    assert data and all(d["manufacturer"] == "Kingston" and "SO-DIMM DDR5" == d["attributes"]["Tipo"] for d in data)
    assert client.get("/presets/recognize?v=KVR32N22S8/16").json()["found"]["part"] == "KVR32N22S8/16"


def test_new_form_prefilled_from_preset_and_part(client):
    html = client.get("/components/new?preset=kvr32n22s8-16").text
    assert 'value="KVR32N22S8/16"' in html and "Kingston" in html and "Riconosciuto" not in html
    html = client.get("/components/new?part=KVR29N21S8/16").text
    assert "Riconosciuto dalla sigla" in html and 'value="KVR29N21S8/16"' in html
    assert "Nessun modello riconosciuto" in client.get("/components/new?part=boh123").text


def test_create_assigns_codes_and_auto_tags(client, db):
    form = {"name": "RAM DDR4 16 GB", "category": "RAM", "manufacturer": "Kingston", "tags": "scaffale a",
            "quantity": "1", "status": "stock", "attr_key": ["Capacita (GB)"], "attr_value": ["16"]}
    r = client.post("/components/new", data=form, headers=FETCH)
    cid = int(r.json()["redirect"].rsplit("/", 1)[1])
    c = db.get(Component, cid)
    assert c.stock_serial.startswith("RAM-KIN-") and c.stock_serial.endswith("-0001")
    assert codes.is_valid_ref_code(c.ref_code)
    names = {t.name for t in c.tags}
    assert {"ram", "kingston", "scaffale a"} <= names
    r2 = client.post("/components/new", data=form, headers=FETCH)
    c2 = db.get(Component, int(r2.json()["redirect"].rsplit("/", 1)[1]))
    assert c2.stock_serial.endswith("-0002") and c2.ref_code != c.ref_code


def test_stock_serial_from_specs(db):
    c = Component(name="x", category="RAM", manufacturer="Kingston",
                  attributes={"Tipo": "SO-DIMM DDR5", "Capacita (GB)": 32})
    assert codes.stock_serial_prefix(c) == "RAM-KIN-SD5-32G"
    s = Component(name="y", category="SSD", manufacturer="Samsung", attributes={"Capacita (GB)": 1000})
    assert codes.stock_serial_prefix(s) == "SSD-SAM-1T"
    other = Component(name="z", category="Periferica", manufacturer="", model="MX Master 3")
    assert codes.stock_serial_prefix(other) == "PER-GEN-MXMAST"


def test_ref_code_check_digit():
    code = codes.new_ref_code()
    assert codes.is_valid_ref_code(code)
    wrong = code[:-1] + ("0" if code[-1] != "0" else "1")
    assert not codes.is_valid_ref_code(wrong)


def test_backfill_existing_and_scan_lookup(client, db):
    old = Component(name="Vecchio", category="GPU", attributes={"VRAM (GB)": 8}, asset_tag="C-000099")
    db.add(old)
    db.commit()
    assert codes.backfill(db) == 1
    db.commit()
    assert old.stock_serial == "GPU-GEN-8G-0001" and old.ref_code
    assert client.get(f"/scan/resolve?v={old.ref_code.lower()}").json() == {"url": f"/components/{old.id}"}
    assert client.get(f"/scan/resolve?v={old.stock_serial}").json() == {"url": f"/components/{old.id}"}
    assert codes.backfill(db) == 0


def test_scan_unknown_model_offers_new_component(client):
    r = client.get("/scan/resolve?v=KVR26N19S8/8").json()
    assert r["new"] == "/components/new?part=KVR26N19S8/8" and "Kingston" in r["model"]


def test_migration_adds_ram_types_without_losing_custom(tmp_path):
    db = tmp_path / "m.db"
    run_migrations(db, tmp_path / "b")
    conn = sqlite3.connect(db)
    choices = json.loads(conn.execute(
        "SELECT f.choices FROM category_fields f JOIN categories c ON c.id=f.category_id "
        "WHERE c.name='RAM' AND f.key='Tipo'").fetchone()[0])
    conn.close()
    assert choices[:5] == ["DDR", "DDR2", "DDR3", "DDR4", "DDR5"] and "SO-DIMM DDR2" in choices


def test_menu_filter_and_bottom_nav(client):
    html = client.get("/").text
    assert 'id="nav-filter"' in html and "data-close-menu" in html
    assert 'href="/print" class="bottom-nav__item"' in html and "data-scan-search" in html
