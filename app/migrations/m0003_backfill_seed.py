"""Migrazione 3: backfill dati v1.1.1 (solo colonne nuove) + seed predefiniti.

Non modifica nessun valore gia' salvato: scrive solo colonne aggiunte in v2 e righe nuove.
"""
import json
import sqlite3

CATEGORIES = [
    "RAM", "SSD", "HDD", "CPU", "GPU", "Scheda madre", "Alimentatore",
    "Case", "Ventola", "Cavo", "Scheda di rete", "Periferica", "Altro",
]

# (key, type, unit, choices). key = etichetta storica (static/js/app.js v1.1.1) dove esiste.
N, T, C = "number", "text", "choice"
CATEGORY_FIELDS = {
    "RAM": [("Capacita (GB)", N, "GB", None), ("Tipo", C, "", ["DDR3", "DDR4", "DDR5", "SO-DIMM DDR4", "SO-DIMM DDR5"]),
            ("Velocita (MHz)", N, "MHz", None), ("Form factor", T, "", None)],
    "SSD": [("Capacita (GB)", N, "GB", None), ("Interfaccia", C, "", ["SATA", "NVMe PCIe 3.0", "NVMe PCIe 4.0", "NVMe PCIe 5.0"]),
            ("Form factor", T, "", None), ("TBW", N, "TB", None)],
    "HDD": [("Capacita (GB)", N, "GB", None), ("Interfaccia", T, "", None), ("RPM", N, "rpm", None),
            ("Form factor", T, "", None)],
    "CPU": [("Socket", T, "", None), ("Core", N, "", None), ("Thread", N, "", None),
            ("Frequenza (GHz)", N, "GHz", None), ("TDP", N, "W", None)],
    "GPU": [("VRAM (GB)", N, "GB", None), ("Chipset", T, "", None), ("Tipo memoria", T, "", None),
            ("Interfaccia", T, "", None), ("TDP", N, "W", None), ("Connettori alimentazione", T, "", None),
            ("Uscite video", T, "", None), ("Lunghezza (mm)", N, "mm", None)],
    "Scheda madre": [("Socket", T, "", None), ("Chipset", T, "", None), ("Form factor", T, "", None),
                     ("Slot RAM", N, "", None)],
    "Alimentatore": [("Potenza (W)", N, "W", None), ("Certificazione", T, "", None), ("Modulare", T, "", None)],
    "Scheda di rete": [("Velocita", T, "", None), ("Interfaccia", T, "", None), ("Porte", N, "", None)],
    "Ventola": [("Dimensione (mm)", N, "mm", None), ("Connettore", T, "", None), ("RPM", N, "rpm", None)],
    "Cavo": [("Tipo", C, "", ["HDMI", "DisplayPort", "USB-C", "USB-A", "Ethernet", "SATA", "Alimentazione",
                              "PCIe power", "Audio", "Altro"]),
             ("Connettore A", T, "", None), ("Connettore B", T, "", None), ("Lunghezza (m)", N, "m", None),
             ("Standard/versione", T, "", None), ("Colore", T, "", None)],
}


def _num(key, label, unit="", mn=None, mx=None):
    return {"key": key, "label": label, "type": "number", "unit": unit, "min": mn, "max": mx}


def _bool(key, label, pass_value=False):
    return {"key": key, "label": label, "type": "bool", "pass_value": pass_value}


TEST_TEMPLATES = [
    ("Stress test GPU", "GPU", [
        {"key": "tool", "label": "Strumento", "type": "text"},
        _num("durata_min", "Durata", "min", 15), _num("temp_max", "Temperatura massima", "°C", None, 85),
        _bool("artefatti", "Artefatti grafici"), _bool("crash", "Crash / driver reset")]),
    ("MemTest RAM", "RAM", [_num("passate", "Passate completate", "", 1), _num("errori", "Errori", "", None, 0)]),
    ("SMART SSD", "SSD", [_num("ore", "Ore di accensione", "h"), _num("salute", "Salute", "%", 80),
                          _num("riallocati", "Settori riallocati", "", None, 0),
                          _num("lettura", "Lettura", "MB/s"), _num("scrittura", "Scrittura", "MB/s")]),
    ("SMART HDD", "HDD", [_num("ore", "Ore di accensione", "h"), _num("salute", "Salute", "%", 80),
                          _num("riallocati", "Settori riallocati", "", None, 0),
                          _num("lettura", "Lettura", "MB/s"), _num("scrittura", "Scrittura", "MB/s")]),
    ("Benchmark CPU", "CPU", [_num("punteggio", "Punteggio benchmark"), _num("temp_max", "Temperatura massima", "°C", None, 95)]),
    ("Tester alimentatore", "Alimentatore", [_num("v12", "Linea 12 V", "V", 11.4, 12.6), _num("v5", "Linea 5 V", "V", 4.75, 5.25),
                                             _num("v33", "Linea 3,3 V", "V", 3.14, 3.47)]),
    ("Test cavo", "Cavo", [_bool("continuita", "Continuità OK", True), {"key": "segnale", "label": "Segnale (risoluzione/frequenza o velocità)", "type": "text"}]),
    ("iperf scheda di rete", "Scheda di rete", [_num("mbps", "Throughput", "Mbps")]),
    ("Test ventola", "Ventola", [_num("rpm", "RPM a pieno carico", "rpm", 1), _bool("rumore", "Rumori anomali")]),
]

SETTINGS = {"signature_window_min": 10, "audit_interval_days": 180, "public_base_url": ""}


def apply(conn: sqlite3.Connection) -> None:
    # Asset tag e campi nuovi per righe esistenti
    conn.execute("UPDATE components SET asset_tag = printf('C-%06d', id) WHERE asset_tag IS NULL")
    conn.execute("UPDATE machines SET asset_tag = printf('M-%03d', id) WHERE asset_tag IS NULL")
    conn.execute(
        "UPDATE components SET tracking = CASE WHEN COALESCE(quantity, 1) > 1 THEN 'quantity' ELSE 'serial' END "
        "WHERE tracking IS NULL"
    )
    conn.execute("UPDATE components SET unit = 'pz' WHERE unit IS NULL")
    conn.execute("UPDATE components SET currency = 'EUR' WHERE currency IS NULL")

    # Posizioni dai testi liberi (testo originale intatto)
    names = [r[0] for r in conn.execute(
        "SELECT DISTINCT trim(location) FROM components "
        "WHERE location IS NOT NULL AND trim(location) <> '' AND location_id IS NULL ORDER BY 1"
    )]
    for name in names:
        row = conn.execute("SELECT id FROM locations WHERE name = ? AND parent_id IS NULL", (name,)).fetchone()
        if row:
            loc_id = row[0]
        else:
            loc_id = conn.execute(
                "INSERT INTO locations (name, kind, notes, created_at) VALUES (?, 'altro', '', datetime('now'))",
                (name,),
            ).lastrowid
            conn.execute("UPDATE locations SET asset_tag = printf('L-%04d', id) WHERE id = ?", (loc_id,))
        conn.execute(
            "UPDATE components SET location_id = ? WHERE trim(location) = ? AND location_id IS NULL",
            (loc_id, name),
        )

    # Categorie e campi tipizzati
    for name in CATEGORIES:
        conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
    for cat, fields in CATEGORY_FIELDS.items():
        cat_id = conn.execute("SELECT id FROM categories WHERE name = ?", (cat,)).fetchone()[0]
        if conn.execute("SELECT count(*) FROM category_fields WHERE category_id = ?", (cat_id,)).fetchone()[0]:
            continue
        for order, (key, ftype, unit, choices) in enumerate(fields):
            conn.execute(
                "INSERT INTO category_fields (category_id, key, label, type, unit, choices, required, sort_order, "
                "filterable, active) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 1, 1)",
                (cat_id, key, key, ftype, unit, json.dumps(choices or []), order),
            )
    conn.execute("UPDATE categories SET default_tracking = 'quantity' WHERE name = 'Cavo' AND default_tracking IS NULL")
    conn.execute("UPDATE categories SET default_tracking = 'serial' WHERE default_tracking IS NULL")
    conn.execute("UPDATE categories SET default_unit = 'pz' WHERE default_unit IS NULL")

    # Modelli di test
    if not conn.execute("SELECT count(*) FROM test_templates").fetchone()[0]:
        for name, cat, fields in TEST_TEMPLATES:
            conn.execute(
                "INSERT INTO test_templates (name, category, description, fields, checklist, active) "
                "VALUES (?, ?, '', ?, '[]', 1)",
                (name, cat, json.dumps(fields, ensure_ascii=False)),
            )

    for key, value in SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps({"v": value})))
