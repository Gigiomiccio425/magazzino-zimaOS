import pytest

from app.models import Change, Component, Incident, Location, Machine, Operator, Service
from app.services.search import global_search
from app.timeutil import utcnow


@pytest.fixture
def data(client, db):
    s = Service(slug="immich", name="Immich")
    db.add_all([
        Component(name="RTX 3060", asset_tag="C-000001", serial_number="GPU-XYZ", attributes={}),
        Component(name="RTX nascosta", asset_tag="C-000002", deleted_at=utcnow(), attributes={}),
        Location(name="Scaffale RTX", asset_tag="L-0001"),
        Machine(name="Server", asset_tag="M-001"),
        s,
        Incident(title="Immich lento", severity="SEV3", status="open"),
        Operator(name="Gigio", name_key="gigio"),
    ])
    db.flush()
    db.add(Change(service_id=s.id, type="fix", title="Fix upload Immich"))
    db.commit()


def test_groups(db, data):
    groups = {g.label: [h.title for h in g.items] for g in global_search(db, "rtx")}
    assert groups == {"Componenti": ["RTX 3060"], "Posizioni": ["Scaffale RTX"]}
    groups = {g.label: [h.title for h in g.items] for g in global_search(db, "immich")}
    assert set(groups) == {"Servizi", "Incidenti", "Changelog"}
    hit = global_search(db, "GPU-XYZ")[0].items[0]
    assert hit.url.startswith("/components/") and "C-000001" in hit.subtitle


def test_excludes_deleted(db, data):
    assert "RTX nascosta" not in str([h.title for g in global_search(db, "nascosta") for h in g.items])


def test_min_length(db, data):
    assert global_search(db, "r") == [] and global_search(db, "  ") == []


def test_json_and_page(client, data):
    r = client.get("/search.json", params={"q": "server"}).json()
    assert r["groups"][0]["label"] == "Macchine" and r["groups"][0]["items"][0]["url"].startswith("/machines/")
    assert "Server" in client.get("/search", params={"q": "server"}).text


def test_palette_in_base(client):
    html = client.get("/").text
    assert 'id="palette"' in html and "/static/js/palette.js" in html
