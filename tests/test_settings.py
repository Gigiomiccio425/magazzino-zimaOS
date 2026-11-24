import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.models import Operator
from app.services.settings_store import DEFAULTS, base_url, get_setting, set_setting
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


VALID = {"signature_window_min": "15", "audit_interval_days": "90", "public_base_url": "https://mag.example/"}


def test_defaults(client, db):
    assert DEFAULTS == {"signature_window_min": 10, "audit_interval_days": 180, "public_base_url": ""}
    assert get_setting(db, "signature_window_min") == 10
    assert get_setting(db, "inesistente") is None


def test_set_and_get(db):
    set_setting(db, "audit_interval_days", 30)
    db.commit()
    assert get_setting(db, "audit_interval_days") == 30


def test_page_renders(client):
    assert "Impostazioni" in client.get("/settings").text


def test_update_requires_critical(client):
    assert client.post("/settings", data=VALID, headers=FETCH).status_code == 428


def test_update_saves(client, db, op_id):
    assert critical_post(client, "/settings", op_id, VALID).status_code == 200
    db.expire_all()
    assert get_setting(db, "signature_window_min") == 15
    assert get_setting(db, "public_base_url") == "https://mag.example"


@pytest.mark.parametrize("field,value", [
    ("signature_window_min", "61"), ("signature_window_min", "-1"), ("audit_interval_days", "0"),
    ("public_base_url", "javascript:alert(1)"), ("public_base_url", "mag.example"),
])
def test_invalid_values_rejected(client, db, op_id, field, value):
    r = critical_post(client, "/settings", op_id, {**VALID, field: value})
    assert r.status_code == 422
    db.expire_all()
    assert get_setting(db, "signature_window_min") == 10


def _req(host="testserver"):
    return Request({"type": "http", "scheme": "http", "server": (host, 80), "path": "/", "headers": [], "query_string": b"",
                    "app": None})


def test_base_url_precedence(db, monkeypatch):
    class S:
        public_base_url = ""

    req = _req()
    req.scope["app"] = type("A", (), {"state": type("St", (), {"settings": S})})()
    assert base_url(req, db) == "http://testserver"
    S.public_base_url = "https://env.example"
    assert base_url(req, db) == "https://env.example"
    set_setting(db, "public_base_url", "https://db.example")
    assert base_url(req, db) == "https://db.example"
