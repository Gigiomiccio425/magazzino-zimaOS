from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Category, CategoryField, Component, Movement, OutboxItem, Webhook
from app.services.component_form import parse_price
from tests.fixtures.v111 import build_v111_db
from tests.helpers import FETCH, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


def _field(db, category, key):
    return db.query(CategoryField).join(Category).filter(Category.name == category, CategoryField.key == key).one()


def create(client, **data):
    body = {"name": "Oggetto", "status": "stock", "tracking": "serial", **data}
    r = client.post("/components/new", data=body, headers=FETCH)
    assert r.status_code == 200, r.text
    client.get("/movements")  # consuma il messaggio flash (contiene il nome)
    return int(r.json()["redirect"].rsplit("/", 1)[1])


@pytest.mark.parametrize("text,cents", [("12,50", 1250), ("1.234,56", 123456), ("12.5", 1250), ("", None),
                                         ("  7 ", 700), ("0,99", 99)])
def test_parse_price(text, cents):
    assert parse_price(text) == cents


def test_parse_price_invalid():
    with pytest.raises(ValueError):
        parse_price("abc")


def test_create_quantity_item(client, db):
    cid = create(client, name="HDMI 2m", category="Cavo", tracking="quantity", quantity="30", unit="pz", min_stock="5")
    c = db.get(Component, cid)
    assert (c.tracking, c.quantity, c.min_stock, c.unit) == ("quantity", 30, 5, "pz")


def test_serial_item_forces_quantity_one(client, db):
    cid = create(client, name="GPU", tracking="serial", quantity="4")
    assert db.get(Component, cid).quantity == 1


def test_adjust_quantity_movement_and_stock_low_once(client, db):
    db.add(Webhook(name="d", kind="discord", url="https://discord.com/api/webhooks/1/x", events=["stock.low"],
                   enabled=True))
    db.commit()
    cid = create(client, name="Cavo", tracking="quantity", quantity="6", min_stock="5")
    client.post(f"/components/{cid}/qty", data={"delta": "-1", "reason": "uso", "notify": "1"}, headers=FETCH)
    assert db.query(OutboxItem).count() == 0  # 5 non e' sotto il minimo
    client.post(f"/components/{cid}/qty", data={"delta": "-1", "reason": "uso", "notify": "1"}, headers=FETCH)
    client.post(f"/components/{cid}/qty", data={"delta": "-1", "reason": "uso", "notify": "1"}, headers=FETCH)
    db.expire_all()
    assert db.get(Component, cid).quantity == 3
    assert db.query(OutboxItem).count() == 1  # solo al passaggio sotto soglia
    mv = db.query(Movement).filter_by(component_id=cid, action="qty").order_by(Movement.id).all()
    assert [m.qty_delta for m in mv] == [-1, -1, -1] and mv[0].reason == "uso"


def test_adjust_negative_refused(client, db):
    cid = create(client, name="Cavo", tracking="quantity", quantity="1")
    r = client.post(f"/components/{cid}/qty", data={"delta": "-2"}, headers=FETCH)
    assert r.status_code == 422
    db.expire_all()
    assert db.get(Component, cid).quantity == 1


def test_typed_number_saved_as_number(client, db):
    f = _field(db, "GPU", "VRAM (GB)")
    cid = create(client, name="RTX", category="GPU", **{f"cf_{f.id}": "12"})
    assert db.get(Component, cid).attributes["VRAM (GB)"] == 12


def test_legacy_attributes_kept_on_edit(client, db):
    cid = create(client, name="Vecchio", category="GPU", attr_key=["Nota storica"], attr_value=["valore"])
    f = _field(db, "GPU", "VRAM (GB)")
    client.post(f"/components/{cid}/edit", data={"name": "Vecchio", "category": "GPU", "status": "stock",
                                                 "tracking": "serial", f"cf_{f.id}": "8",
                                                 "attr_key": ["Nota storica"], "attr_value": ["valore"]}, headers=FETCH)
    db.expire_all()
    assert db.get(Component, cid).attributes == {"Nota storica": "valore", "VRAM (GB)": 8}


def test_numeric_filter_skips_non_numeric_legacy(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    build_v111_db(data / "magazzino.db")
    with TestClient(create_app(data, start_worker=False)) as c:
        from sqlalchemy.orm import Session

        with Session(bind=c.app.state.engine) as db:
            f = db.query(CategoryField).filter_by(key="Capacita (GB)").join(Category).filter(Category.name == "RAM").one()
            f_ssd = db.query(CategoryField).filter_by(key="Capacita (GB)").join(Category).filter(Category.name == "SSD").one()
        html = c.get(f"/components?category=RAM&f{f.id}_min=8").text
        assert "Corsair 16GB" in html
        html = c.get(f"/components?category=SSD&f{f_ssd.id}_min=0").text
        assert "Samsung 970" not in html


def test_choice_filter(client, db):
    f = _field(db, "Cavo", "Tipo")
    create(client, name="Cavo HDMI", category="Cavo", tracking="quantity", quantity="2", **{f"cf_{f.id}": "HDMI"})
    create(client, name="Cavo USB", category="Cavo", tracking="quantity", quantity="2", **{f"cf_{f.id}": "USB-C"})
    html = client.get(f"/components?category=Cavo&f{f.id}=HDMI").text
    assert "Cavo HDMI" in html and "Cavo USB" not in html


def test_tags_and_tag_filter(client, db):
    cid = create(client, name="Con tag", tags="ricambi, gaming , ricambi")
    assert [t.name for t in db.get(Component, cid).tags] == ["gaming", "ricambi"]
    create(client, name="Senza tag")
    html = client.get("/components?tag=gaming").text
    assert "Con tag" in html and "Senza tag" not in html


def test_new_statuses_labels(client):
    html = client.get("/components/new").text
    assert "Da testare" in html and "In RMA" in html


def test_purchase_and_warranty_saved(client, db):
    cid = create(client, name="SSD", supplier="Amazon", purchase_date="2026-01-10", purchase_price="89,90",
                 warranty_until="2028-01-10", invoice_ref="FT-1")
    c = db.get(Component, cid)
    assert (c.supplier, c.purchase_date, c.purchase_price, c.warranty_until, c.invoice_ref) == (
        "Amazon", date(2026, 1, 10), 8990, date(2028, 1, 10), "FT-1")


def test_invalid_price_rejected(client, db):
    r = client.post("/components/new", data={"name": "X", "purchase_price": "tanto"}, headers=FETCH)
    assert r.status_code == 422 and db.query(Component).count() == 0


def test_low_stock_filter_and_location_filter(client, db):
    from app.models import Location

    loc = Location(name="Box", kind="box")
    db.add(loc)
    db.commit()
    create(client, name="Scarso", tracking="quantity", quantity="1", min_stock="3", location_id=str(loc.id))
    create(client, name="Abbondante", tracking="quantity", quantity="10", min_stock="3")
    html = client.get("/components?low_stock=1").text
    assert "Scarso" in html and "Abbondante" not in html
    html = client.get(f"/components?location={loc.id}").text
    assert "Scarso" in html and "Abbondante" not in html
