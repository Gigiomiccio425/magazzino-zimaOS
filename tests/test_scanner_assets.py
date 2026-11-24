import re
from pathlib import Path

VENDOR = Path("static/vendor")


def test_vendor_files_present():
    assert (VENDOR / "barcode-detector" / "ponyfill.min.js").stat().st_size > 10_000
    assert (VENDOR / "zxing" / "zxing_reader.wasm").read_bytes()[:4] == b"\0asm"
    assert (VENDOR / "barcode-detector" / "LICENSE").exists() and (VENDOR / "zxing" / "LICENSE").exists()


def test_wasm_mime(client):
    r = client.get("/static/vendor/zxing/zxing_reader.wasm")
    assert r.status_code == 200 and r.headers["content-type"] == "application/wasm"


def test_own_js_no_cdn():
    for js in Path("static/js").glob("*.js"):
        assert not re.search(r"jsdelivr|unpkg|fastly|cdnjs", js.read_text(encoding="utf-8")), js.name


def test_scanner_uses_local_wasm_and_resolver():
    text = Path("static/js/scanner.js").read_text(encoding="utf-8")
    assert "/static/vendor/zxing/" in text and "/scan/resolve" in text and "prepareZXingModule" in text


def test_ponyfill_loaded_in_base(client):
    assert "/static/vendor/barcode-detector/ponyfill.min.js" in client.get("/").text
