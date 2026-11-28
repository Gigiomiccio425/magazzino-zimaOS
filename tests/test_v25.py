"""2.5: schede Icecat, stampanti a rotolo, OCR incluso, consultazione senza rete."""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.models import Component, PrintItem
from app.services import icecat, printing
from app.services.settings_store import set_setting
from tests.helpers import FETCH, critical_post, get_csrf, sign_new

SAMPLE = {"msg": "OK", "data": {
    "GeneralInfo": {"Title": "Kingston ValueRAM 16GB DDR4 2666MHz", "Brand": "Kingston", "BrandPartCode": "KVR26N19S8/16",
                    "IcecatId": 123, "Description": {"LongDesc": "<b>Memoria</b> affidabile"}},
    "Image": {"HighPic": "https://images.icecat.biz/img/x.jpg"},
    "FeaturesGroups": [{"FeatureGroup": {"Name": {"Value": "Memoria"}},
                        "Features": [{"Feature": {"Name": {"Value": "Capacità"}}, "PresentationValue": "16 GB"},
                                     {"Feature": {"Name": {"Value": "Velocità"}}, "PresentationValue": "2666 MHz"}]}]}}


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


def _lookup(handler, user="utente"):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await icecat.lookup(http, user, "Kingston", "KVR26N19S8/16")
    return asyncio.run(go())


def test_icecat_parse_and_lookup():
    seen = []
    res = _lookup(lambda req: seen.append(req) or httpx.Response(200, json=SAMPLE))
    f = res["found"]
    assert f["title"].startswith("Kingston") and f["description"] == "Memoria  affidabile"
    assert [s["name"] for s in f["specs"]] == ["Capacità", "Velocità"]
    assert seen[0].url.params["ProductCode"] == "KVR26N19S8/16" and seen[0].url.params["UserName"] == "utente"
    assert _lookup(lambda req: httpx.Response(404))["error"] == "not_found"
    assert _lookup(lambda req: httpx.Response(403))["error"] == "auth"
    assert _lookup(lambda req: httpx.Response(200, json=SAMPLE), user="")["error"] == "not_configured"


def test_icecat_endpoint_requires_username(client):
    r = client.get("/presets/icecat?brand=Kingston&part=KVR26N19S8/16")
    assert r.status_code == 422 and "Impostazioni" in r.json()["message"]


def test_settings_save_icecat_username(client, db):
    from app.models import Operator
    from app.services.settings_store import get_setting

    op = db.query(Operator).one()
    data = {"signature_window_min": "10", "audit_interval_days": "180", "public_base_url": "", "icecat_username": "gigio_ice"}
    assert critical_post(client, "/settings", op.id, data).status_code == 200
    db.expire_all()
    assert get_setting(db, "icecat_username") == "gigio_ice"
    bad = {**data, "icecat_username": "a b<c>"}
    assert critical_post(client, "/settings", op.id, bad).status_code == 422


def test_icecat_button_on_form(client):
    assert "data-icecat" in client.get("/components/new").text


def _entries():
    return [printing.Entry(1, "component", 1, "C-000001", "RAM DDR4", "A-01", "", "label", 2),
            printing.Entry(2, "component", 2, "C-000002", "Cavo HDMI", "B-01", "", "flag", 1),
            printing.Entry(3, "component", 3, "C-000003", "SSD", "A-02", "", "qr", 1)]


def test_roll_pages_continuous_and_diecut():
    cont = printing.roll_pages(_entries(), "62c", 6)
    assert len(cont) == 4 and all(p.w == 62 for p in cont)
    flag = next(p for p in cont if p.slot.format == "flag")
    assert flag.rotate and flag.h == pytest.approx(95 + 3)
    die = printing.roll_pages(_entries(), "50x30", 6)
    assert {(p.w, p.h) for p in die} == {(50, 30)} and {p.slot.format for p in die} == {"label", "qr"}


def test_roll_print_routes(client, db):
    comps = [Component(name="Cavo HDMI", category="Cavo", asset_tag="C-000001", attributes={})]
    db.add_all(comps)
    db.flush()
    db.add(PrintItem(entity_type="component", entity_id=comps[0].id, format="flag", copies=2))
    db.commit()
    assert "Stampante a rotolo" in client.get("/print?mode=roll&roll=62c").text
    html = client.get("/print/sheets?mode=roll&roll=62c").text
    assert "@page roll-62-98" in html and html.count("sheet--roll") >= 2 and "rotate(90deg)" in html


def test_ocr_assets_served(client):
    for path in ["/static/vendor/tesseract/tesseract.min.js", "/static/vendor/tesseract/worker.min.js",
                 "/static/vendor/tesseract/core/tesseract-core-simd-lstm.wasm.js",
                 "/static/vendor/tesseract/lang/eng.traineddata.gz"]:
        assert client.get(path).status_code == 200, path
    js = client.get("/static/js/scanner.js").text
    assert "Leggi testo" in js and "workerBlobURL: false" in js


def test_offline_read_only(client):
    sw = client.get("/sw.js").text
    assert "magazzino-pagine" in sw and "caches.match(\"/offline\")" in sw
    assert "is-offline" in client.get("/static/js/app.js").text
