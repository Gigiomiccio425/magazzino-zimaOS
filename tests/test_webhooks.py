import asyncio
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.models import Operator, OutboxItem, Webhook
from app.services import discord, events, outbox
from app.timeutil import utcnow
from tests.helpers import FETCH, critical_post, get_csrf, sign_new

URL = "https://discord.com/api/webhooks/123456/abcDEF-_x"
INC = {"title": "Immich giù", "description": "Non risponde", "url_path": "/incidents/1",
       "fields": [["Servizi", "Immich"]], "severity": "SEV1", "status_label": "Aperto", "operator": "Gigio",
       "resolved": False}


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.fixture
def op_id(client, db):
    return db.query(Operator).one().id


def _hook(db, **kw):
    data = {"name": "Server", "kind": "discord", "url": URL, "enabled": True,
            "events": ["incident.opened", "stock.low"], "min_severity": None, "service_ids": None}
    data.update(kw)
    h = Webhook(**data)
    db.add(h)
    db.commit()
    return h


def test_discord_url_validation():
    assert discord.is_valid_discord_url(URL)
    assert discord.is_valid_discord_url("https://discordapp.com/api/webhooks/1/x")
    assert not discord.is_valid_discord_url("http://discord.com/api/webhooks/1/x")
    assert not discord.is_valid_discord_url("https://evil.com/api/webhooks/1/x")


def test_payload_no_mentions_by_default():
    p = discord.build_payload("incident.opened", INC, base_url="https://mag.example", app_name="MAGAZZINO")
    assert p["allowed_mentions"] == {"parse": []}
    assert "content" not in p
    e = p["embeds"][0]
    assert e["title"] == "[SEV1] Immich giù" and e["color"] == 0xE2231A
    assert e["url"] == "https://mag.example/incidents/1"
    assert e["footer"]["text"] == "MAGAZZINO" and e["timestamp"].endswith("Z")


def test_payload_role_only_sev1_opened():
    p = discord.build_payload("incident.opened", INC, base_url="", app_name="M", mention_role_id="999")
    assert p["content"] == "<@&999>" and p["allowed_mentions"] == {"parse": [], "roles": ["999"]}
    assert "url" not in p["embeds"][0]
    sev2 = discord.build_payload("incident.opened", {**INC, "severity": "SEV2"}, base_url="", app_name="M",
                                 mention_role_id="999")
    assert "content" not in sev2 and sev2["allowed_mentions"] == {"parse": []}


def test_payload_truncates_limits():
    data = {**INC, "title": "🔥" * 300, "description": "x" * 5000,
            "fields": [[f"n{i}" * 200, "v" * 2000] for i in range(30)]}
    e = discord.build_payload("incident.updated", data, base_url="", app_name="M")["embeds"][0]
    assert len(e["title"]) <= 256 and len(e["description"]) <= 4096 and e["description"].endswith("…")
    assert len(e["fields"]) == 25
    assert all(len(f["name"]) <= 256 and len(f["value"]) <= 1024 for f in e["fields"])


def test_emit_matches_rules(db):
    _hook(db, name="tutto")
    _hook(db, name="solo SEV1", min_severity="SEV1")
    _hook(db, name="altro evento", events=["test.failed"])
    _hook(db, name="spento", enabled=False)
    _hook(db, name="servizio 5", service_ids=[5])
    n = events.emit(db, "incident.opened", {**INC, "severity": "SEV2"}, base_url="", severity="SEV2", service_ids=[1])
    db.commit()
    names = sorted(i.webhook.name for i in db.query(OutboxItem))
    assert n == 1 and names == ["tutto"]


def test_emit_notify_false_enqueues_nothing(db):
    _hook(db)
    assert events.emit(db, "stock.low", INC, base_url="", notify=False) == 0
    assert db.query(OutboxItem).count() == 0


def test_default_notify(db):
    assert events.default_notify(db, "stock.low") is False
    _hook(db)
    assert events.default_notify(db, "stock.low") is True


def _run(engine, handler, now=None):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await outbox.deliver_due(engine, c, now=now)
    return asyncio.run(go())


def _queued(db):
    _hook(db)
    events.emit(db, "stock.low", INC, base_url="")
    db.commit()
    return db.query(OutboxItem).one()


def test_deliver_success(app, db):
    item = _queued(db)
    seen = []
    assert _run(app.state.engine, lambda req: seen.append(req) or httpx.Response(204)) == 1
    db.refresh(item)
    assert item.status == "sent" and item.sent_at and seen[0].url == URL


def test_deliver_429_retry_after(app, db):
    item = _queued(db)
    now = utcnow() + timedelta(minutes=1)  # sempre dopo la creazione in coda
    _run(app.state.engine, lambda req: httpx.Response(429, json={"retry_after": 2.5}), now=now)
    db.refresh(item)
    assert item.status == "pending" and item.attempts == 0
    assert item.next_attempt_at == now + timedelta(seconds=2.5)


def test_deliver_4xx_dead(app, db):
    item = _queued(db)
    _run(app.state.engine, lambda req: httpx.Response(404))
    db.refresh(item)
    assert item.status == "dead" and "404" in item.last_error


def test_deliver_5xx_backoff_then_dead(app, db):
    item = _queued(db)
    now = utcnow() + timedelta(minutes=1)  # sempre dopo la creazione in coda
    for i, delay in enumerate(outbox.BACKOFF_SECONDS):
        _run(app.state.engine, lambda req: httpx.Response(502), now=now)
        db.refresh(item)
        if i < len(outbox.BACKOFF_SECONDS) - 1:
            assert item.status == "pending" and item.next_attempt_at == now + timedelta(seconds=delay)
        now = item.next_attempt_at
    assert item.status == "dead" and item.attempts == 8


def test_webhook_create_requires_critical(client, db, op_id):
    data = {"name": "Canale", "kind": "discord", "url": URL, "events": ["incident.opened"], "enabled": "1"}
    assert client.post("/webhooks/new", data=data, headers=FETCH).status_code == 428
    r = critical_post(client, "/webhooks/new", op_id, data)
    assert r.status_code == 200
    assert db.query(Webhook).one().events == ["incident.opened"]


def test_webhook_invalid_url_rejected(client, db, op_id):
    data = {"name": "X", "kind": "discord", "url": "https://evil.com/x", "events": ["incident.opened"]}
    assert critical_post(client, "/webhooks/new", op_id, data).status_code == 422


def test_list_masks_url(client, db):
    _hook(db)
    html = client.get("/webhooks").text
    assert "abcDEF" not in html and "discord.com/api/webhooks/…" in html


def test_send_test(client, db, app, monkeypatch):
    h = _hook(db)
    sent = []

    async def fake_deliver_one(dbs, item, http, now):
        sent.append(item.event)
        item.status = "sent"

    monkeypatch.setattr(outbox, "deliver_one", fake_deliver_one)
    r = client.post(f"/webhooks/{h.id}/test", headers=FETCH)
    assert r.status_code == 200 and sent == ["webhook.test"]
