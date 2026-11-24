import pytest
from fastapi.testclient import TestClient

from app.models import Incident, IncidentUpdate, OutboxItem, Problem, Service, Webhook
from tests.helpers import FETCH, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def svc(client, db):
    a, b = Service(slug="immich", name="Immich"), Service(slug="jellyfin", name="Jellyfin")
    db.add_all([a, b])
    db.add(Webhook(name="d", kind="discord", url="https://discord.com/api/webhooks/1/x",
                   events=["incident.opened", "incident.updated", "incident.resolved"], enabled=True))
    db.commit()
    return a, b


def open_incident(client, svc, **extra):
    a, b = svc
    data = {"title": "Immich non risponde", "severity": "SEV2", "summary": "502 dal proxy",
            "service_ids": [str(a.id), str(b.id)], f"svc_status_{a.id}": "major_outage",
            f"svc_status_{b.id}": "", **extra}
    r = client.post("/incidents/new", data=data, headers=FETCH)
    assert r.status_code == 200, r.text
    return int(r.json()["redirect"].rsplit("/", 1)[1])


def test_open_incident_changes_service_status_only_when_chosen(client, db, svc):
    iid = open_incident(client, svc, notify="1")
    db.expire_all()
    a, b = (db.get(Service, s.id) for s in svc)
    assert a.status == "major_outage" and b.status == "operational"
    inc = db.get(Incident, iid)
    assert inc.status == "open" and {s.name for s in inc.services} == {"Immich", "Jellyfin"}
    assert db.query(OutboxItem).filter_by(event="incident.opened").count() == 1


def test_open_without_notify_sends_nothing(client, db, svc):
    open_incident(client, svc)
    assert db.query(OutboxItem).count() == 0


def test_update_transition_event(client, db, svc):
    iid = open_incident(client, svc)
    r = client.post(f"/incidents/{iid}/updates", data={"status": "identified", "message": "Disco pieno",
                                                        "notify": "1"}, headers=FETCH)
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Incident, iid).status == "identified"
    up = db.query(IncidentUpdate).filter_by(incident_id=iid, status="identified").one()
    assert up.message == "Disco pieno" and up.notified and up.operator_id
    assert db.query(OutboxItem).filter_by(event="incident.updated").count() == 1


def test_resolve_sets_resolved_at_and_event(client, db, svc):
    iid = open_incident(client, svc)
    a, _ = svc
    client.post(f"/incidents/{iid}/updates", data={"status": "resolved", "message": "Ripristinato", "notify": "1",
                                                    f"svc_status_{a.id}": "operational"}, headers=FETCH)
    db.expire_all()
    inc = db.get(Incident, iid)
    assert inc.status == "resolved" and inc.resolved_at is not None
    assert db.get(Service, a.id).status == "operational"
    assert db.query(OutboxItem).filter_by(event="incident.resolved").count() == 1


def test_postmortem_html_escaped(client, db, svc):
    iid = open_incident(client, svc)
    client.post(f"/incidents/{iid}/postmortem", data={"root_cause": "Disco", "postmortem_md": "## Cosa\n<script>x</script>"},
                headers=FETCH)
    html = client.get(f"/incidents/{iid}").text
    assert "<h2>Cosa</h2>" in html and "<script>x</script>" not in html


def test_problem_links(client, db, svc):
    iid = open_incident(client, svc)
    a, _ = svc
    r = client.post("/problems/new", data={"title": "Disco si riempie", "description_md": "log enormi",
                                           "workaround_md": "pulire /tmp", "status": "workaround",
                                           "service_ids": [str(a.id)], "incident_ids": [str(iid)]}, headers=FETCH)
    assert r.status_code == 200
    p = db.query(Problem).one()
    assert [s.name for s in p.services] == ["Immich"] and [i.id for i in p.incidents] == [iid]
    client.get("/movements")
    assert "Disco si riempie" in client.get("/problems").text
    assert "Disco si riempie" in client.get(f"/incidents/{iid}").text


def test_pages(client, db, svc):
    iid = open_incident(client, svc)
    client.get("/movements")
    assert "Immich non risponde" in client.get("/incidents").text
    assert client.get("/incidents/new").status_code == 200
    assert client.get(f"/incidents/new?service={svc[0].id}").status_code == 200
