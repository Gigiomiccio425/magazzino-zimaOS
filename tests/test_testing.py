import pytest
from fastapi.testclient import TestClient

from app.models import Component, OutboxItem, TestRun, TestTemplate, Webhook
from app.services.testing import suggest_result
from tests.helpers import FETCH, get_csrf, sign_new

GPU_FIELDS = [
    {"key": "temp_max", "label": "Temp", "type": "number", "unit": "°C", "min": None, "max": 85},
    {"key": "durata_min", "label": "Durata", "type": "number", "min": 15, "max": None},
    {"key": "artefatti", "label": "Artefatti", "type": "bool", "pass_value": False},
    {"key": "tool", "label": "Strumento", "type": "text"},
]


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def gpu(client, db):
    c = Component(name="RTX", category="GPU", asset_tag="C-000001", status="to_test", attributes={})
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def tpl(db, client):
    return db.query(TestTemplate).filter_by(category="GPU").first()


def test_suggest_result_rules():
    assert suggest_result(GPU_FIELDS, {"temp_max": "78", "durata_min": "20", "artefatti": ""}) == "pass"
    assert suggest_result(GPU_FIELDS, {"temp_max": "90", "durata_min": "20"}) == "fail"
    assert suggest_result(GPU_FIELDS, {"temp_max": "70", "durata_min": "10"}) == "fail"
    assert suggest_result(GPU_FIELDS, {"temp_max": "70", "artefatti": "1"}) == "fail"
    assert suggest_result(GPU_FIELDS, {"tool": "FurMark"}) is None
    assert suggest_result([], {}) is None


def run_test(client, gpu, tpl, **data):
    body = {"template_id": str(tpl.id), "result": "pass", "tool": "FurMark", **data}
    r = client.post(f"/components/{gpu.id}/tests/new", data=body, headers=FETCH)
    assert r.status_code == 200, r.text
    return r


def test_run_updates_last_test(client, db, gpu, tpl):
    run_test(client, gpu, tpl, v_temp_max="78")
    db.expire_all()
    c = db.get(Component, gpu.id)
    run = db.query(TestRun).one()
    assert c.last_test_result == "pass" and c.last_test_at is not None
    assert run.values == {"temp_max": 78} and run.operator_id and run.signature_id


def test_status_changes_only_when_checked(client, db, gpu, tpl):
    run_test(client, gpu, tpl)
    db.expire_all()
    assert db.get(Component, gpu.id).status == "to_test"
    run_test(client, gpu, tpl, set_status="tested_ok")
    db.expire_all()
    assert db.get(Component, gpu.id).status == "tested_ok"


def test_failed_emits_when_notify(client, db, gpu, tpl):
    db.add(Webhook(name="d", kind="discord", url="https://discord.com/api/webhooks/1/x", events=["test.failed"],
                   enabled=True))
    db.commit()
    run_test(client, gpu, tpl, result="fail")
    assert db.query(OutboxItem).count() == 0
    run_test(client, gpu, tpl, result="fail", notify="1")
    assert db.query(OutboxItem).count() == 1


def test_invalid_result_refused(client, gpu, tpl):
    r = client.post(f"/components/{gpu.id}/tests/new", data={"template_id": str(tpl.id), "result": "boh"},
                    headers=FETCH)
    assert r.status_code == 422


def test_queue_lists_to_test(client, gpu):
    assert "RTX" in client.get("/tests/queue").text


def test_form_and_history_pages(client, db, gpu, tpl):
    assert "Stress test GPU" in client.get(f"/components/{gpu.id}/tests/new").text
    run_test(client, gpu, tpl)
    client.get("/movements")
    assert "FurMark" in client.get(f"/components/{gpu.id}").text
    run = db.query(TestRun).one()
    assert client.get(f"/tests/runs/{run.id}").status_code == 200


def test_template_crud(client, db):
    r = client.post("/tests/templates/new", data={
        "name": "Test HDMI", "category": "Cavo", "description": "",
        "field_label": ["Risoluzione max", "Continuità"], "field_type": ["text", "bool"],
        "field_unit": ["", ""], "field_min": ["", ""], "field_max": ["", ""], "field_pass": ["", "1"],
        "checklist": "Collega a monitor 4K\nVerifica audio"}, headers=FETCH)
    assert r.status_code == 200
    t = db.query(TestTemplate).filter_by(name="Test HDMI").one()
    assert [f["key"] for f in t.fields] == ["risoluzione_max", "continuita"]
    assert t.fields[1]["pass_value"] is True and t.checklist == ["Collega a monitor 4K", "Verifica audio"]
    assert "Test HDMI" in client.get("/tests/templates").text
