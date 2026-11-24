import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.models import Attachment, Component, Operator
from app.services import uploads
from tests.helpers import FETCH, critical_post, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def comp(client, db):
    c = Component(name="GPU", asset_tag="C-000001", attributes={})
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def settings(app, client):
    return app.state.settings


def jpeg_with_exif(orientation=1, size=(1200, 600)) -> bytes:
    img = Image.new("RGB", size, (200, 30, 20))
    exif = Image.Exif()
    exif[0x0112] = orientation               # Orientation
    exif[0x8825] = {2: (45.0, 30.0, 0.0)}    # GPSInfo (latitudine)
    exif[0x010F] = "FotocameraTest"          # Make
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def upload(client, comp, name, data, mime="image/jpeg"):
    return client.post("/attachments", data={"entity_type": "component", "entity_id": str(comp.id)},
                       files={"files": (name, data, mime)}, headers=FETCH)


def test_jpeg_exif_gps_removed_and_thumb(client, db, comp, settings):
    assert upload(client, comp, "foto.jpg", jpeg_with_exif()).status_code == 200
    att = db.query(Attachment).one()
    stored = settings.uploads_dir / att.path
    with Image.open(stored) as img:
        assert not img.getexif()
    with Image.open(settings.uploads_dir / att.thumb_path) as th:
        assert max(th.size) <= 400 and th.format == "WEBP"
    assert att.mime == "image/jpeg" and att.filename == "foto.jpg"


def test_orientation_applied(client, db, comp, settings):
    upload(client, comp, "ruotata.jpg", jpeg_with_exif(orientation=6, size=(1200, 600)))
    att = db.query(Attachment).one()
    with Image.open(settings.uploads_dir / att.path) as img:
        assert img.size == (600, 1200)


def test_fake_jpeg_rejected_415(client, db, comp):
    r = upload(client, comp, "finta.jpg", b"<html><script>alert(1)</script></html>")
    assert r.status_code == 415 and db.query(Attachment).count() == 0


def test_svg_rejected(client, comp):
    r = upload(client, comp, "x.svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/svg+xml")
    assert r.status_code == 415


def test_text_and_pdf_accepted(client, db, comp):
    assert upload(client, comp, "log.txt", "riga 1\nàèì".encode(), "text/plain").status_code == 200
    assert upload(client, comp, "doc.pdf", b"%PDF-1.4\n%fine", "application/pdf").status_code == 200
    assert sorted(a.mime for a in db.query(Attachment)) == ["application/pdf", "text/plain"]


def test_too_large_413(client, comp, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_BYTES", 1000)
    assert upload(client, comp, "grande.txt", b"a" * 1001, "text/plain").status_code == 413


def test_served_headers(client, db, comp):
    upload(client, comp, "log.txt", b"ciao", "text/plain")
    upload(client, comp, "foto.jpg", jpeg_with_exif())
    txt, img = sorted(db.query(Attachment), key=lambda a: a.mime, reverse=True)
    r = client.get(f"/attachments/{txt.id}")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"].startswith("attachment")
    r = client.get(f"/attachments/{img.id}")
    assert r.headers["content-disposition"].startswith("inline") and r.headers["content-type"] == "image/jpeg"
    assert client.get(f"/attachments/{img.id}/thumb").headers["content-type"] == "image/webp"


def test_trash_moves_file(client, db, comp, settings):
    upload(client, comp, "log.txt", b"ciao", "text/plain")
    att = db.query(Attachment).one()
    client.post(f"/attachments/{att.id}/delete", headers=FETCH)
    db.expire_all()
    att = db.get(Attachment, att.id)
    assert att.deleted_at is not None
    assert not (settings.uploads_dir / att.path).exists()
    assert list((settings.uploads_dir / ".cestino").rglob("*.txt"))
    assert client.get(f"/attachments/{att.id}").status_code == 404


def test_empty_trash_critical(client, db, comp, settings):
    upload(client, comp, "log.txt", b"ciao", "text/plain")
    att = db.query(Attachment).one()
    client.post(f"/attachments/{att.id}/delete", headers=FETCH)
    assert client.post("/attachments/trash/empty", headers=FETCH).status_code == 428
    op = db.query(Operator).one()
    assert critical_post(client, "/attachments/trash/empty", op.id).status_code == 200
    assert not list((settings.uploads_dir / ".cestino").rglob("*.txt"))


def test_component_page_shows_attachments(client, db, comp):
    upload(client, comp, "foto.jpg", jpeg_with_exif())
    client.get("/movements")
    html = client.get(f"/components/{comp.id}").text
    assert "foto.jpg" in html and "/thumb" in html
