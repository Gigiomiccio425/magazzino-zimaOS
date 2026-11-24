import pytest
from fastapi.testclient import TestClient

from app.models import Component, Location, Machine
from app.services.qr import qr_svg, resolve_scan, resolve_tag, tag_url
from app.timeutil import utcnow
from tests.helpers import get_csrf


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        yield c


@pytest.fixture
def items(client, db):
    garage = Location(name="Garage", asset_tag="L-0001")
    db.add(garage)
    db.flush()
    box = Location(name="Box 3", asset_tag="L-0002", parent_id=garage.id)
    db.add(box)
    db.flush()
    gpu = Component(name="RTX 3060", asset_tag="C-000001", serial_number="GPU-XYZ", object_code="INV-9",
                    location_id=box.id, attributes={})
    cable = Component(name="HDMI", asset_tag="C-000002", location_id=garage.id, attributes={})
    gone = Component(name="Eliminato", asset_tag="C-000003", serial_number="GONE", deleted_at=utcnow(), attributes={})
    m = Machine(name="Server", asset_tag="M-001")
    db.add_all([gpu, cable, gone, m])
    db.commit()
    return {"garage": garage, "box": box, "gpu": gpu, "cable": cable, "gone": gone, "machine": m}


def test_tag_url():
    assert tag_url("https://mag.example/", "C-000001") == "https://mag.example/q/C-000001"


def test_qr_svg():
    svg = qr_svg("https://mag.example/q/C-000001")
    assert svg.lstrip().startswith("<svg")
    assert "#111" in svg.lower()


def test_q_redirects(client, items):
    for tag, url in [("C-000001", f"/components/{items['gpu'].id}"), ("L-0002", f"/locations/{items['box'].id}"),
                     ("M-001", f"/machines/{items['machine'].id}")]:
        r = client.get(f"/q/{tag}", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == url


def test_q_unknown_404(client, items):
    assert client.get("/q/C-999999", follow_redirects=False).status_code == 404
    assert client.get("/q/C-000003", follow_redirects=False).status_code == 404  # nel cestino


def test_qr_svg_response(client, items):
    r = client.get("/qr/C-000001.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert 'xmlns="http://www.w3.org/2000/svg"' in r.text  # file SVG autonomo, decodificabile come immagine
    assert client.get("/qr/XYZ.svg").status_code == 404


def test_scan_resolve_cases(client, db, items):
    gpu = f"/components/{items['gpu'].id}"
    assert resolve_scan(db, "https://altro.host/q/C-000001") == {"url": gpu}
    assert resolve_scan(db, "c-000001") == {"url": gpu}
    assert resolve_scan(db, "GPU-XYZ") == {"url": gpu}
    assert resolve_scan(db, "INV-9") == {"url": gpu}
    assert resolve_scan(db, "qualcosa") == {"search": "/components?q=qualcosa"}
    assert client.get("/scan/resolve", params={"v": "M-001"}).json() == {"url": f"/machines/{items['machine'].id}"}


def test_scan_ignores_deleted(db, items):
    assert resolve_scan(db, "GONE") == {"search": "/components?q=GONE"}
    assert resolve_tag(db, "C-000003") is None


def test_labels_formats(client, items):
    for fmt in ("small", "medium", "a4"):
        html = client.get("/labels", params={"components": str(items["gpu"].id), "format": fmt}).text
        assert f"labels--{fmt}" in html and "C-000001" in html and "<svg" in html


def test_labels_location_includes_children(client, items):
    html = client.get("/labels", params={"locations": str(items["garage"].id), "format": "medium"}).text
    for tag in ("L-0001", "L-0002", "C-000001", "C-000002"):
        assert tag in html
