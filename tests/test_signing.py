import pytest
from fastapi import APIRouter, Depends, Request
from fastapi.testclient import TestClient

from app.core.csrf import verify_csrf
from app.models import Operator, Setting
from app.services import signing
from app.services.signing import SignerInfo, hash_password, require_signer, verify_password
from tests.helpers import get_csrf

FETCH = {"X-Requested-With": "fetch"}


@pytest.fixture
def client(app):
    r = APIRouter()

    @r.post("/_t/write")
    def _w(request: Request, signer: SignerInfo = Depends(require_signer())):
        return {"op": signer.operator_name}

    @r.post("/_t/critical")
    def _c(request: Request, signer: SignerInfo = Depends(require_signer(critical=True))):
        return {"op": signer.operator_name}

    app.include_router(r, dependencies=[Depends(verify_csrf)])
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        yield c


def sign(client, **body):
    return client.post("/sign/password", json=body, headers=FETCH)


def test_password_hash_roundtrip():
    h = hash_password("segreto1")
    assert h.startswith("scrypt$")
    assert verify_password("segreto1", h)
    assert not verify_password("sbagliata", h)


def test_first_operator_is_admin(client, db):
    assert sign(client, new_name="Gigio", password="segreto1").json()["ok"] is True
    assert sign(client, new_name="Dany", password="segreto2").status_code == 200
    ops = {o.name: o.is_admin for o in db.query(Operator)}
    assert ops == {"Gigio": True, "Dany": False}


def test_operator_names_case_and_space_insensitive(client):
    assert sign(client, new_name="  dany  ", password="segreto1").status_code == 200
    r = sign(client, new_name="Dany", password="segreto2")
    assert r.status_code == 409


def test_password_too_short(client):
    assert sign(client, new_name="Gigio", password="12345").status_code == 422


def test_new_operator_requires_method(client):
    assert sign(client, new_name="Gigio").status_code == 422


def test_lock_after_5_failures(client, db):
    sign(client, new_name="Gigio", password="segreto1")
    op_id = db.query(Operator).one().id
    for _ in range(5):
        assert sign(client, operator_id=op_id, password="sbagliata").status_code == 401
    assert sign(client, operator_id=op_id, password="segreto1").status_code == 423


def test_fetch_write_without_signer_gets_428(client):
    r = client.post("/_t/write", headers=FETCH)
    assert r.status_code == 428
    assert r.json() == {"error": "signature_required", "critical": False}


def test_plain_form_without_signer_redirects(client):
    r = client.post("/_t/write", headers={"Referer": "http://testserver/machines"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/machines"


def test_session_window(client, monkeypatch):
    t = [1_000_000.0]
    monkeypatch.setattr(signing, "_now", lambda: t[0])
    sign(client, new_name="Gigio", password="segreto1")
    assert client.post("/_t/write", headers=FETCH).json() == {"op": "Gigio"}
    t[0] += 11 * 60
    assert client.post("/_t/write", headers=FETCH).status_code == 428


def test_sign_state(client):
    assert client.get("/sign/state").json()["signed"] is False
    sign(client, new_name="Gigio", password="segreto1")
    state = client.get("/sign/state").json()
    assert state["signed"] is True and state["operator"] == "Gigio" and 0 < state["expires_in"] <= 600


def test_window_zero_needs_token_each_time(client, db):
    db.merge(Setting(key="signature_window_min", value={"v": 0}))
    db.commit()
    r = sign(client, new_name="Gigio", password="segreto1", action="POST /_t/write")
    assert client.post("/_t/write", headers=FETCH).status_code == 428
    token = r.json()["action_token"]
    assert client.post("/_t/write", headers={**FETCH, "X-Sig-Token": token}).status_code == 200


def test_critical_token_single_use_and_bound(client, monkeypatch, db):
    t = [1_000_000.0]
    monkeypatch.setattr(signing, "_now", lambda: t[0])
    sign(client, new_name="Gigio", password="segreto1")
    op_id = db.query(Operator).one().id
    # sessione valida non basta per un'azione critica
    r = client.post("/_t/critical", headers=FETCH)
    assert r.status_code == 428 and r.json()["critical"] is True
    token = sign(client, operator_id=op_id, password="segreto1", action="POST /_t/critical").json()["action_token"]
    assert client.post("/_t/critical", headers={**FETCH, "X-Sig-Token": token}).status_code == 200
    assert client.post("/_t/critical", headers={**FETCH, "X-Sig-Token": token}).status_code == 428
    other = sign(client, operator_id=op_id, password="segreto1", action="POST /_t/altro").json()["action_token"]
    assert client.post("/_t/critical", headers={**FETCH, "X-Sig-Token": other}).status_code == 428
    late = sign(client, operator_id=op_id, password="segreto1", action="POST /_t/critical").json()["action_token"]
    t[0] += 121
    assert client.post("/_t/critical", headers={**FETCH, "X-Sig-Token": late}).status_code == 428


def test_disabled_operator_session_rejected(client, db):
    sign(client, new_name="Gigio", password="segreto1")
    op = db.query(Operator).one()
    op.active = False
    db.commit()
    assert client.post("/_t/write", headers=FETCH).status_code == 428


def test_sign_logout(client):
    sign(client, new_name="Gigio", password="segreto1")
    client.post("/sign/logout", headers=FETCH)
    assert client.get("/sign/state").json()["signed"] is False


def test_operators_list(client):
    sign(client, new_name="Gigio", password="segreto1")
    ops = client.get("/sign/operators").json()
    assert ops == [{"id": ops[0]["id"], "name": "Gigio", "has_password": True, "passkey_here": False}]
