import pytest
from fastapi.testclient import TestClient

from app.models import Category, CategoryField
from tests.helpers import FETCH, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def cavo(db, client):
    return db.query(Category).filter_by(name="Cavo").one()


def add(client, cat_id, **data):
    body = {"label": "Schermatura", "type": "text", "unit": "", "choices": "", **data}
    return client.post(f"/categories/{cat_id}/fields", data=body, headers=FETCH)


def test_pages(client, cavo):
    assert "Cavo" in client.get("/categories").text
    assert "Lunghezza (m)" in client.get(f"/categories/{cavo.id}/fields").text


def test_add_field_key_from_label(client, db, cavo):
    assert add(client, cavo.id, label="Schermatura").status_code == 200
    f = db.query(CategoryField).filter_by(category_id=cavo.id, label="Schermatura").one()
    assert f.key == "Schermatura" and f.sort_order > 0


def test_add_choice_field(client, db, cavo):
    add(client, cavo.id, label="Guaina", type="choice", choices="PVC, Nylon,  PVC ")
    assert db.query(CategoryField).filter_by(label="Guaina").one().choices == ["PVC", "Nylon"]


def test_rename_keeps_key(client, db, cavo):
    f = db.query(CategoryField).filter_by(category_id=cavo.id, key="Colore").one()
    r = client.post(f"/categories/fields/{f.id}/edit", data={"label": "Colore guaina", "unit": "", "choices": "",
                                                              "sort_order": "9", "filterable": "1", "active": "1"},
                    headers=FETCH)
    assert r.status_code == 200
    db.expire_all()
    f = db.get(CategoryField, f.id)
    assert (f.key, f.label, f.sort_order) == ("Colore", "Colore guaina", 9)


def test_key_with_quote_refused(client, cavo):
    assert add(client, cavo.id, label='Bad "quote"').status_code == 422


def test_duplicate_key_refused(client, cavo):
    assert add(client, cavo.id, label="Colore").status_code == 409


def test_deactivate(client, db, cavo):
    f = db.query(CategoryField).filter_by(category_id=cavo.id, key="Colore").one()
    client.post(f"/categories/fields/{f.id}/edit", data={"label": "Colore", "unit": "", "choices": "",
                                                         "sort_order": "5"}, headers=FETCH)
    db.expire_all()
    assert db.get(CategoryField, f.id).active is False


def test_requires_signer(app, cavo):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        assert add(c, cavo.id).status_code == 428
