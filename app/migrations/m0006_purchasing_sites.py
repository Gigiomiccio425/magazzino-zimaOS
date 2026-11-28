"""Migrazione 6: fornitori e ordini, sedi, vita utile per l'ammortamento, avvisi garanzia.

Solo aggiunte (tabelle e colonne nuove, vuote). Nessun dato esistente viene cambiato.
"""
import sqlite3

from .util import add_column

TABLES = [
    """CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER NOT NULL,
        name VARCHAR(160) NOT NULL UNIQUE,
        website VARCHAR(500),
        email VARCHAR(200),
        phone VARCHAR(60),
        notes TEXT,
        created_at DATETIME,
        deleted_at DATETIME,
        PRIMARY KEY (id)
    )""",
    """CREATE TABLE IF NOT EXISTS supplier_parts (
        id INTEGER NOT NULL,
        supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
        component_id INTEGER NOT NULL REFERENCES components(id),
        sku VARCHAR(120),
        price INTEGER,
        url VARCHAR(500),
        preferred BOOLEAN DEFAULT 0,
        PRIMARY KEY (id),
        UNIQUE (supplier_id, component_id)
    )""",
    """CREATE TABLE IF NOT EXISTS purchase_orders (
        id INTEGER NOT NULL,
        number VARCHAR(20) NOT NULL UNIQUE,
        supplier_id INTEGER REFERENCES suppliers(id),
        status VARCHAR(20) NOT NULL DEFAULT 'draft',
        notes TEXT,
        ordered_at DATETIME,
        expected_at DATE,
        received_at DATETIME,
        created_by INTEGER REFERENCES operators(id),
        created_at DATETIME,
        PRIMARY KEY (id)
    )""",
    """CREATE TABLE IF NOT EXISTS purchase_order_lines (
        id INTEGER NOT NULL,
        order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
        component_id INTEGER REFERENCES components(id),
        description VARCHAR(200) NOT NULL,
        qty INTEGER NOT NULL DEFAULT 1,
        qty_received INTEGER NOT NULL DEFAULT 0,
        unit_price INTEGER,
        PRIMARY KEY (id)
    )""",
    """CREATE TABLE IF NOT EXISTS sites (
        id INTEGER NOT NULL,
        name VARCHAR(120) NOT NULL UNIQUE,
        address VARCHAR(300),
        notes TEXT,
        created_at DATETIME,
        deleted_at DATETIME,
        PRIMARY KEY (id)
    )""",
]

COLUMNS = [
    ("locations", "site_id INTEGER REFERENCES sites(id)"),
    ("machines", "site_id INTEGER REFERENCES sites(id)"),
    ("categories", "useful_life_months INTEGER"),
    ("components", "warranty_notified_at DATETIME"),
    ("maintenances", "reminded_at DATETIME"),
]

# vita utile predefinita (mesi) per l'ammortamento lineare, solo se la categoria non ce l'ha già
DEFAULT_LIFE = {"GPU": 36, "CPU": 60, "RAM": 60, "SSD": 48, "HDD": 48, "Scheda madre": 60, "Alimentatore": 60,
                "Case": 84, "Ventola": 36, "Cavo": 60, "Scheda di rete": 60, "Periferica": 36}


def apply(conn: sqlite3.Connection) -> None:
    for ddl in TABLES:
        conn.execute(ddl)
    for table, ddl in COLUMNS:
        add_column(conn, table, ddl)
    for name, months in DEFAULT_LIFE.items():
        conn.execute("UPDATE categories SET useful_life_months = ? WHERE name = ? AND useful_life_months IS NULL",
                     (months, name))
