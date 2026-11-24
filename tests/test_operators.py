import pytest
from fastapi.testclient import TestClient

from app.models import Operator, OperatorCredential
from tests.helpers import FETCH, critical_post, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        yield c


@pytest.fixture
def team(client, db):
    sign_new(client, "Gigio", "segreto1")
    sign_new(client, "Dany", "segreto2")
    ops = {o.name: o.id for o in db.query(Operator)}
    return ops


def test_list_page(client, team):
    html = client.get("/operators").text
    assert "Gigio" in html and "Dany" in html


def test_admin_disables_operator(client, db, team):
    r = critical_post(client, f"/operators/{team['Dany']}/disable", team["Gigio"])
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Operator, team["Dany"]).active is False


def test_non_admin_forbidden(client, team):
    r = critical_post(client, f"/operators/{team['Gigio']}/disable", team["Dany"], password="segreto2")
    assert r.status_code == 403


def test_disable_requires_critical(client, team):
    client.post("/sign/password", json={"operator_id": team["Gigio"], "password": "segreto1"}, headers=FETCH)
    r = client.post(f"/operators/{team['Dany']}/disable", headers=FETCH)
    assert r.status_code == 428 and r.json()["critical"] is True


def test_reset_password(client, db, team):
    r = critical_post(client, f"/operators/{team['Dany']}/reset-password", team["Gigio"], {"password": "nuova123"})
    assert r.status_code == 200
    ok = client.post("/sign/password", json={"operator_id": team["Dany"], "password": "nuova123"}, headers=FETCH)
    assert ok.status_code == 200


def test_reset_password_too_short(client, team):
    r = critical_post(client, f"/operators/{team['Dany']}/reset-password", team["Gigio"], {"password": "123"})
    assert r.status_code == 422


def test_remove_passkeys(client, db, team):
    db.add(OperatorCredential(operator_id=team["Dany"], credential_id=b"c", public_key=b"p", rp_id="x"))
    db.commit()
    critical_post(client, f"/operators/{team['Dany']}/remove-passkeys", team["Gigio"])
    assert db.query(OperatorCredential).count() == 0


def test_toggle_admin(client, db, team):
    critical_post(client, f"/operators/{team['Dany']}/toggle-admin", team["Gigio"])
    db.expire_all()
    assert db.get(Operator, team["Dany"]).is_admin is True


def test_last_admin_protected(client, db, team):
    r = critical_post(client, f"/operators/{team['Gigio']}/toggle-admin", team["Gigio"])
    assert r.status_code == 409
    r = critical_post(client, f"/operators/{team['Gigio']}/disable", team["Gigio"])
    assert r.status_code == 409


def test_profile_page(client, team):
    client.post("/sign/password", json={"operator_id": team["Dany"], "password": "segreto2"}, headers=FETCH)
    assert "Dany" in client.get("/profile").text


def test_change_own_password_requires_critical(client, team):
    client.post("/sign/password", json={"operator_id": team["Dany"], "password": "segreto2"}, headers=FETCH)
    assert client.post("/profile/password", data={"password": "altra123"}, headers=FETCH).status_code == 428
    r = critical_post(client, "/profile/password", team["Dany"], {"password": "altra123"}, password="segreto2")
    assert r.status_code == 200
    ok = client.post("/sign/password", json={"operator_id": team["Dany"], "password": "altra123"}, headers=FETCH)
    assert ok.status_code == 200
