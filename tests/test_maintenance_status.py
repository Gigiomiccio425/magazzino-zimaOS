from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.models import Incident, Maintenance, OutboxItem, Service, Webhook
from app.timeutil import format_local_input, utcnow
from app.worker import Worker
from tests.helpers import FETCH, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def svc(client, db):
    s = Service(slug="immich", name="Immich")
    db.add(s)
    db.add(Webhook(name="d", kind="discord", url="https://discord.com/api/webhooks/1/x",
                   events=["maintenance.scheduled", "maintenance.started", "maintenance.completed",
                           "maintenance.cancelled"], enabled=True))
    db.commit()
    return s


def schedule(client, svc, start, end, notify="1"):
    r = client.post("/maintenance/new", data={
        "title": "Aggiornamento umbrelOS", "description_md": "Riavvio", "service_ids": [str(svc.id)],
        "starts_at": format_local_input(start), "ends_at": format_local_input(end), "notify": notify}, headers=FETCH)
    assert r.status_code == 200, r.text
    return r


def test_transitions_manual_only(app, client, db, svc):
    past = utcnow() - timedelta(hours=2)
    schedule(client, svc, past, past + timedelta(hours=1))
    m = db.query(Maintenance).one()
    # il worker ha solo backup e consegna webhook: nessun job cambia le manutenzioni da solo
    # (alerts_job manda solo promemoria: non cambia lo stato delle manutenzioni)
    assert {job.__name__ for _, job in Worker(app).jobs} == {"backup_job", "outbox_job", "purge_job", "alerts_job"}
    db.expire_all()
    assert db.get(Maintenance, m.id).status == "scheduled"

    client.post(f"/maintenance/{m.id}/start", data={"set_service_status": "1", "notify": "1"}, headers=FETCH)
    db.expire_all()
    assert db.get(Maintenance, m.id).status == "in_progress"
    assert db.get(Service, svc.id).status == "maintenance"
    client.post(f"/maintenance/{m.id}/complete", data={"set_service_status": "1", "notify": "1"}, headers=FETCH)
    db.expire_all()
    assert db.get(Maintenance, m.id).status == "completed"
    assert db.get(Service, svc.id).status == "operational"


def test_end_before_start_refused(client, svc):
    now = utcnow()
    r = client.post("/maintenance/new", data={"title": "X", "starts_at": format_local_input(now),
                                              "ends_at": format_local_input(now - timedelta(hours=1))}, headers=FETCH)
    assert r.status_code == 422


def test_overdue_flag(client, db, svc):
    past = utcnow() - timedelta(hours=3)
    schedule(client, svc, past, past + timedelta(hours=1), notify="")
    client.get("/movements")
    html = client.get("/maintenance").text
    assert "in ritardo" in html


def test_events(client, db, svc):
    now = utcnow()
    schedule(client, svc, now + timedelta(days=1), now + timedelta(days=1, hours=1))
    m = db.query(Maintenance).one()
    client.post(f"/maintenance/{m.id}/cancel", data={"notify": "1"}, headers=FETCH)
    events = [i.event for i in db.query(OutboxItem).order_by(OutboxItem.id)]
    assert events == ["maintenance.scheduled", "maintenance.cancelled"]
    db.expire_all()
    assert db.get(Maintenance, m.id).status == "cancelled"


def test_status_page_content(client, db, svc):
    svc.status = "degraded"
    db.add(Incident(title="Lentezza", severity="SEV3", status="investigating", services=[svc]))
    db.add(Incident(title="Vecchio risolto", severity="SEV4", status="resolved", started_at=utcnow() - timedelta(days=2),
                    resolved_at=utcnow() - timedelta(days=1)))
    db.add(Incident(title="Antichissimo", severity="SEV4", status="resolved", started_at=utcnow() - timedelta(days=60),
                    resolved_at=utcnow() - timedelta(days=59)))
    db.commit()
    now = utcnow()
    schedule(client, svc, now + timedelta(days=1), now + timedelta(days=1, hours=2), notify="")
    client.get("/movements")
    html = client.get("/status").text
    assert "Immich" in html and "Degradato" in html and "Lentezza" in html
    assert "Aggiornamento umbrelOS" in html and "Vecchio risolto" in html and "Antichissimo" not in html
