import pytest
from fastapi.testclient import TestClient

from app.models import Change, Link, OutboxItem, Service, ServiceModule, Webhook
from app.services.links import is_safe_url, parse_link
from app.services.markdown import render_markdown
from tests.helpers import FETCH, get_csrf, sign_new


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        c.headers["X-CSRF-Token"] = get_csrf(c)
        sign_new(c, "Gigio", "segreto1")
        yield c


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/getumbrel/umbrel/commit/abc1234", ("github_commit", "getumbrel", "umbrel", "abc1234")),
    ("https://github.com/o/r/pull/42", ("github_pr", "o", "r", "42")),
    ("https://github.com/o/r/issues/7#issuecomment-1", ("github_issue", "o", "r", "7")),
    ("https://github.com/o/r/releases/tag/v2.0.0", ("github_release", "o", "r", "v2.0.0")),
    ("https://github.com/o/r.git", ("github_repo", "o", "r", "")),
    ("https://www.github.com/o/r/", ("github_repo", "o", "r", "")),
    ("https://gitlab.com/o/r", ("altro", "", "", "")),
])
def test_parse_link_cases(url, expected):
    info = parse_link(url)
    assert (info.kind, info.owner, info.repo, info.ref) == expected


def test_is_safe_url():
    assert is_safe_url("https://x.y/a") and is_safe_url("http://umbrel.local:8000")
    assert not is_safe_url("javascript:alert(1)") and not is_safe_url("data:text/html,x") and not is_safe_url("")


def test_markdown_escapes_html():
    html = str(render_markdown("**ciao** <script>alert(1)</script> [x](https://a.b)"))
    assert "<strong>ciao</strong>" in html and "<script>" not in html
    assert 'rel="noopener noreferrer"' in html


def new_service(client, **data):
    body = {"name": "Immich", "description": "Foto", "url": "https://immich.local", "status": "operational",
            "runbook_md": "", **data}
    r = client.post("/services/new", data=body, headers=FETCH)
    assert r.status_code == 200, r.text
    return int(r.json()["redirect"].rsplit("/", 1)[1])


def test_service_slug_unique(client, db):
    a = new_service(client)
    b = new_service(client)
    assert db.get(Service, a).slug == "immich" and db.get(Service, b).slug == "immich-2"


def test_javascript_url_refused(client):
    r = client.post("/services/new", data={"name": "X", "url": "javascript:alert(1)", "status": "operational"},
                    headers=FETCH)
    assert r.status_code == 422


def test_module_crud(client, db):
    sid = new_service(client)
    r = client.post(f"/services/{sid}/modules", data={"name": "App Android", "kind": "app_android",
                                                       "current_version": "1.0", "repo_url": "https://github.com/o/r"},
                    headers=FETCH)
    assert r.status_code == 200
    assert db.query(ServiceModule).one().kind == "app_android"


def test_change_with_links_updates_module_version_when_checked(client, db):
    sid = new_service(client)
    client.post(f"/services/{sid}/modules", data={"name": "Server", "kind": "web", "current_version": "1.0"},
                headers=FETCH)
    mod = db.query(ServiceModule).one()
    data = {"type": "release", "module_id": str(mod.id), "version": "1.1", "title": "Nuova versione",
            "body_md": "Fix vari", "link_url": ["https://github.com/o/r/pull/5", "", "javascript:x"],
            "link_title": ["PR fix", "", "cattivo"]}
    assert client.post(f"/services/{sid}/changes", data=data, headers=FETCH).status_code == 422  # link non sicuro
    data["link_url"][2] = ""
    assert client.post(f"/services/{sid}/changes", data=data, headers=FETCH).status_code == 200
    db.expire_all()
    assert db.get(ServiceModule, mod.id).current_version == "1.0"
    link = db.query(Link).one()
    assert (link.kind, link.ref, link.title) == ("github_pr", "5", "PR fix")
    client.post(f"/services/{sid}/changes", data={**data, "update_version": "1"}, headers=FETCH)
    db.expire_all()
    assert db.get(ServiceModule, mod.id).current_version == "1.1"
    assert db.query(Change).count() == 2


def test_change_published_event(client, db):
    db.add(Webhook(name="d", kind="discord", url="https://discord.com/api/webhooks/1/x",
                   events=["change.published", "service.status_changed"], enabled=True))
    db.commit()
    sid = new_service(client)
    client.post(f"/services/{sid}/changes", data={"type": "fix", "title": "Bug login", "notify": "1"}, headers=FETCH)
    client.post(f"/services/{sid}/changes", data={"type": "fix", "title": "Silenzioso"}, headers=FETCH)
    assert db.query(OutboxItem).filter_by(event="change.published").count() == 1


def test_status_change_event(client, db):
    db.add(Webhook(name="d", kind="discord", url="https://discord.com/api/webhooks/1/x",
                   events=["service.status_changed"], enabled=True))
    db.commit()
    sid = new_service(client)
    client.post(f"/services/{sid}/status", data={"status": "degraded", "note": "lento", "notify": "1"}, headers=FETCH)
    db.expire_all()
    assert db.get(Service, sid).status == "degraded"
    assert db.query(OutboxItem).count() == 1


def test_pages(client, db):
    sid = new_service(client, runbook_md="## Riavvio\n`docker restart`")
    client.post(f"/services/{sid}/changes", data={"type": "note", "title": "Nota visibile"}, headers=FETCH)
    client.get("/movements")
    assert "Immich" in client.get("/services").text
    html = client.get(f"/services/{sid}").text
    assert "Nota visibile" in html and "<h2>Riavvio</h2>" in html
    assert "Nota visibile" in client.get("/changes").text
