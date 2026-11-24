import re
from datetime import datetime
from pathlib import Path

from tests.helpers import get_csrf


def test_post_without_csrf_403(client):
    assert client.post("/machines/new", data={"name": "X"}).status_code == 403


def test_post_without_csrf_fetch_json(client):
    r = client.post("/machines/new", data={"name": "X"}, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 403 and r.json() == {"error": "csrf"}


def test_post_with_csrf_field_passes_csrf(client):
    token = get_csrf(client)
    assert token
    r = client.post("/machines/new", data={"name": "X", "csrf_token": token}, follow_redirects=False)
    assert r.status_code != 403


def test_csrf_header_accepted(client):
    token = get_csrf(client)
    r = client.post("/machines/new", data={"name": "Y"}, headers={"X-CSRF-Token": token}, follow_redirects=False)
    assert r.status_code != 403


def test_security_headers(client):
    h = client.get("/").headers
    csp = h["content-security-policy"]
    assert "default-src 'self'" in csp and "'wasm-unsafe-eval'" in csp and "frame-ancestors 'self'" in csp
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "same-origin"
    assert h["permissions-policy"] == "camera=(self)"


def test_dt_filter_local(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Rome")
    from app.deps import templates

    assert templates.env.filters["dt"](datetime(2026, 7, 1, 10, 0)) == "01/07/2026 12:00"


def test_base_accessibility_markers(client):
    html = client.get("/").text
    assert 'href="#main"' in html and 'id="main"' in html and 'aria-live="polite"' in html
    assert 'aria-current="page"' in html


def test_all_post_forms_have_csrf():
    for tpl in Path("templates").rglob("*.html"):
        text = tpl.read_text(encoding="utf-8")
        for form in re.findall(r"<form[^>]*method=\"post\"[^>]*>(.*?)</form>", text, flags=re.S | re.I):
            assert "csrf_field()" in form, f"{tpl}: form POST senza csrf_field()"


def test_no_nested_forms():
    """Un <form> dentro un altro viene scartato dal browser (bug v1.1.1 del tasto Elimina)."""
    for tpl in Path("templates").rglob("*.html"):
        depth = 0
        for tag in re.findall(r"<(/?)form\b", tpl.read_text(encoding="utf-8"), flags=re.I):
            depth += -1 if tag else 1
            assert depth <= 1, f"{tpl}: form annidato"


def test_no_native_dialogs_in_js():
    for js in Path("static/js").glob("*.js"):
        text = js.read_text(encoding="utf-8")
        # MAG.confirm(...) e' il dialog dell'app; vietati alert/confirm/prompt nativi
        assert not re.search(r"(?<!MAG\.)\b(alert|confirm|prompt)\(", text), js.name
