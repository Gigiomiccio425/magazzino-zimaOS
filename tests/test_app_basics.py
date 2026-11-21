import pytest

from app.config import load_settings


def test_health_ok(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_no_login_required(client):
    assert client.get("/", follow_redirects=False).status_code == 200


def test_login_redirects_home(client):
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


@pytest.mark.parametrize(
    "path", ["/", "/components", "/components/new", "/machines", "/machines/new", "/movements"]
)
def test_pages_render(client, path):
    assert client.get(path).status_code == 200


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_NAME", "TEST")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://x.y/")
    s = load_settings(tmp_path)
    assert s.app_name == "TEST"
    assert s.public_base_url == "https://x.y"
    assert s.db_path == tmp_path / "magazzino.db"
