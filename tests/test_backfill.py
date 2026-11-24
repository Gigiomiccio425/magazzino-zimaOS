import json
import sqlite3

import pytest

from app.migrations.runner import run_migrations
from tests.fixtures.v111 import build_v111_db


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "m.db"
    build_v111_db(db)
    run_migrations(db, tmp_path / "b")
    c = sqlite3.connect(db)
    yield c
    c.close()


def _by_name(conn, col):
    return dict(conn.execute(f"SELECT name, {col} FROM components"))


def test_asset_tags(conn):
    tags = [r[0] for r in conn.execute("SELECT asset_tag FROM components ORDER BY id")]
    mtags = [r[0] for r in conn.execute("SELECT asset_tag FROM machines ORDER BY id")]
    assert tags == ["C-000001", "C-000002", "C-000003", "C-000004"]
    assert mtags == ["M-001", "M-002"]


def test_tracking(conn):
    tracking = _by_name(conn, "tracking")
    assert tracking["HDMI 2m"] == "quantity"
    assert tracking["RTX 3060"] == "serial"
    assert set(_by_name(conn, "unit").values()) == {"pz"}


def test_locations_from_text(conn):
    locs = dict(conn.execute("SELECT name, id FROM locations"))
    assert set(locs) == {"Scaffale A", "Box cavi"}
    loc_ids = _by_name(conn, "location_id")
    assert loc_ids["RTX 3060"] == loc_ids["Samsung 970"] == locs["Scaffale A"]
    assert loc_ids["HDMI 2m"] == locs["Box cavi"]
    assert loc_ids["Corsair 16GB"] is None
    assert _by_name(conn, "location")["RTX 3060"] == "Scaffale A"
    tags = sorted(r[0] for r in conn.execute("SELECT asset_tag FROM locations"))
    assert tags == ["L-0001", "L-0002"]


def _fields(conn, category):
    return {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            "SELECT f.key, f.type, f.unit FROM category_fields f JOIN categories c ON c.id = f.category_id "
            "WHERE c.name = ?",
            (category,),
        )
    }


def test_category_fields_seeded(conn):
    assert _fields(conn, "RAM")["Capacita (GB)"] == ("number", "GB")
    assert _fields(conn, "Cavo")["Lunghezza (m)"] == ("number", "m")
    assert "VRAM (GB)" in _fields(conn, "GPU")


def test_test_templates_seeded(conn):
    rows = conn.execute("SELECT category, fields FROM test_templates").fetchall()
    assert len(rows) >= 9
    gpu = json.loads(next(f for c, f in rows if c == "GPU"))
    temp = next(f for f in gpu if f["key"] == "temp_max")
    assert isinstance(temp["max"], (int, float))


def test_settings_seeded(conn):
    settings = {k: json.loads(v)["v"] for k, v in conn.execute("SELECT key, value FROM settings")}
    assert settings == {"signature_window_min": 10, "audit_interval_days": 180, "public_base_url": ""}


def test_attributes_untouched(conn):
    attrs = {n: json.loads(a) for n, a in conn.execute("SELECT name, attributes FROM components")}
    assert attrs["Samsung 970"] == {"Capacita (GB)": "1TB"}
    assert attrs["HDMI 2m"] == {"Lunghezza": "2 m"}


def test_fresh_install_has_categories_and_templates(tmp_path):
    run_migrations(tmp_path / "m.db", tmp_path / "b")
    c = sqlite3.connect(tmp_path / "m.db")
    assert c.execute("SELECT count(*) FROM categories").fetchone()[0] == 13
    assert c.execute("SELECT count(*) FROM test_templates").fetchone()[0] >= 9
