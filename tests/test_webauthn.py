import json

import pytest
from fastapi.testclient import TestClient

from app.models import Operator, OperatorCredential
from app.services import webauthn_svc
from app.services.webauthn_svc import RegisteredCredential
from tests.helpers import get_csrf

ORIGIN = "https://mag.example"
H = {"X-Requested-With": "fetch", "Origin": ORIGIN}
CRED_ID = "Y3JlZC0x"  # base64url di b"cred-1"


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        yield c


@pytest.fixture
def fake_verify(monkeypatch):
    calls = {}

    def reg(credential_json, challenge, origin, rp_id):
        calls["reg"] = (challenge, origin, rp_id)
        return RegisteredCredential(credential_id=b"cred-1", public_key=b"pk", sign_count=0, transports=["internal"])

    def auth(credential_json, challenge, origin, rp_id, public_key, sign_count):
        calls["auth"] = (challenge, origin, rp_id, public_key, sign_count)
        return sign_count + 1

    monkeypatch.setattr(webauthn_svc, "verify_registration", reg)
    monkeypatch.setattr(webauthn_svc, "verify_authentication", auth)
    return calls


def register(client, name="Gigio", **extra):
    begin = client.post("/sign/passkey/register/begin", json={"new_name": name}, headers=H)
    assert begin.status_code == 200, begin.text
    return client.post("/sign/passkey/register/finish", json={"credential": {"id": "x"}, **extra}, headers=H)


def test_register_begin_uses_origin_host(client):
    r = client.post("/sign/passkey/register/begin", json={"new_name": "Gigio"}, headers=H)
    opts = json.loads(r.json()["options"]) if isinstance(r.json()["options"], str) else r.json()["options"]
    assert opts["rp"]["id"] == "mag.example"
    assert opts["authenticatorSelection"]["userVerification"] == "required"


def test_env_rp_id_overrides(monkeypatch, data_dir):
    monkeypatch.setenv("WEBAUTHN_RP_ID", "fisso.example")
    from app.main import create_app

    with TestClient(create_app(data_dir, start_worker=False)) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        r = c.post("/sign/passkey/register/begin", json={"new_name": "Gigio"}, headers=H)
        assert json.loads(r.json()["options"])["rp"]["id"] == "fisso.example"


def test_register_finish_creates_operator_and_credential(client, db, fake_verify):
    r = register(client, password="segreto1")
    assert r.status_code == 200 and r.json()["ok"] is True
    op = db.query(Operator).one()
    assert op.name == "Gigio" and op.is_admin and op.password_hash
    cred = db.query(OperatorCredential).one()
    assert cred.rp_id == "mag.example" and cred.credential_id == b"cred-1"
    assert fake_verify["reg"][1:] == (ORIGIN, "mag.example")
    assert client.get("/sign/state").json()["signed"] is True


def test_register_existing_name_refused(client, fake_verify):
    register(client)
    r = client.post("/sign/passkey/register/begin", json={"new_name": " gigio "}, headers=H)
    assert r.status_code == 409


def test_auth_begin_without_credential_for_rp(client, db, fake_verify):
    register(client)
    op_id = db.query(Operator).one().id
    other = {**H, "Origin": "http://umbrel.local"}
    r = client.post("/sign/passkey/auth/begin", json={"operator_id": op_id}, headers=other)
    assert r.status_code == 409
    assert r.json()["message"] == "Nessuna impronta registrata per questo indirizzo: usa la password"


def test_auth_finish_updates_sign_count_and_session(client, db, fake_verify):
    register(client)
    client.post("/sign/logout", headers=H)
    op_id = db.query(Operator).one().id
    begin = client.post("/sign/passkey/auth/begin", json={"operator_id": op_id, "action": "POST /x"}, headers=H)
    opts = json.loads(begin.json()["options"])
    assert opts["userVerification"] == "required" and len(opts["allowCredentials"]) == 1
    r = client.post("/sign/passkey/auth/finish", json={"credential": {"id": CRED_ID}}, headers=H)
    assert r.status_code == 200 and r.json()["action_token"]
    db.expire_all()
    assert db.query(OperatorCredential).one().sign_count == 1
    assert client.get("/sign/state").json()["operator"] == "Gigio"


def test_challenge_single_use(client, db, fake_verify):
    register(client)
    op_id = db.query(Operator).one().id
    client.post("/sign/passkey/auth/begin", json={"operator_id": op_id}, headers=H)
    cred = {"credential": {"id": CRED_ID}}
    assert client.post("/sign/passkey/auth/finish", json=cred, headers=H).status_code == 200
    assert client.post("/sign/passkey/auth/finish", json=cred, headers=H).status_code == 400


def test_failed_verification_rejected(client, monkeypatch):
    def bad(*a, **k):
        raise webauthn_svc.PasskeyError("firma non valida")

    monkeypatch.setattr(webauthn_svc, "verify_registration", bad)
    client.post("/sign/passkey/register/begin", json={"new_name": "Gigio"}, headers=H)
    r = client.post("/sign/passkey/register/finish", json={"credential": {}}, headers=H)
    assert r.status_code == 400
