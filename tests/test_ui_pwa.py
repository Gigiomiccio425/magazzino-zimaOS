import json
import re
from pathlib import Path

CSS = Path("static/css/style.css").read_text(encoding="utf-8")


def _tokens(block_selector: str) -> dict:
    m = re.search(re.escape(block_selector) + r"\s*\{(.*?)\}", CSS, flags=re.S)
    assert m, f"blocco {block_selector} mancante"
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", m.group(1)))


def _lum(hex_color: str) -> float:
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted([_lum(a), _lum(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_contrast_pairs():
    light = _tokens(":root")
    dark = {**light, **_tokens(':root[data-theme="dark"]')}
    for theme in (light, dark):
        # testo normale >= 4.5:1
        for fg, bg in [("ink", "paper"), ("ink", "white"), ("black", "paper"), ("paper", "black"),
                       ("red-dark", "paper"), ("muted", "paper"), ("muted", "white")]:
            assert contrast(theme[fg], theme[bg]) >= 4.5, (fg, bg, theme[fg], theme[bg])
    # testo grande / elementi grafici >= 3:1
    assert contrast(light["red"], light["paper"]) >= 3
    assert contrast("#ffffff", light["red"]) >= 4.5  # testo bianco su rosso (pulsanti, SEV1)


def test_small_red_text_uses_accessible_token():
    """Il rosso pieno su carta/fondo scuro non arriva a 4.5:1: i testi piccoli usano --red-dark."""
    for selector in (".link", ".mini", ".link-more"):
        rule = re.search(re.escape(selector) + r" \{([^}]*)\}", CSS).group(1)
        assert "color: var(--red-dark)" in rule, selector


def test_hidden_attribute_always_hides():
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", CSS)


def test_dark_theme_also_follows_system_preference():
    assert "prefers-color-scheme: dark" in CSS


def test_manifest(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = json.loads(r.text)
    assert m["start_url"] == "/" and m["display"] == "standalone" and m["theme_color"] == "#111111"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes and any(i.get("purpose") == "maskable" for i in m["icons"])
    for icon in m["icons"]:
        assert client.get(icon["src"]).headers["content-type"] == "image/png"


def test_sw_root_scope(client):
    r = client.get("/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert r.headers.get("service-worker-allowed") == "/" and "/offline" in r.text


def test_offline_page(client):
    r = client.get("/offline")
    assert r.status_code == 200 and "offline" in r.text.lower()


def test_base_has_pwa_and_bottom_nav(client):
    html = client.get("/").text
    assert 'rel="manifest"' in html and 'crossorigin="use-credentials"' in html
    assert 'class="bottom-nav"' in html and "data-scan-search" in html and "data-open-palette" in html
    assert "/static/js/theme.js" in html and 'id="theme-toggle"' in html


def test_static_assets_have_content_hash(app):
    """CSS e JS con impronta nell'URL: dopo un aggiornamento il browser non usa la copia vecchia."""
    import re

    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        html = c.get("/offline").text
        m = re.search(r'href="/static/css/style\.css\?v=([0-9a-f]{10})"', html)
        assert m, "style.css senza impronta"
        assert c.get(f"/static/css/style.css?v={m.group(1)}").status_code == 200
