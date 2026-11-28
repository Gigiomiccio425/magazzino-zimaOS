"""Migrazione 5: seriale di magazzino e codice di riferimento dei componenti; tipi RAM da DDR a DDR5.

Solo aggiunte: due colonne nuove (vuote, riempite all'avvio dall'app) con indice unico, e i valori
mancanti nella lista "Tipo" della categoria RAM. Nessun valore esistente viene cambiato o tolto.
"""
import json
import sqlite3

from .util import add_column

RAM_TYPES = ["DDR", "DDR2", "DDR3", "DDR4", "DDR5", "SO-DIMM DDR", "SO-DIMM DDR2", "SO-DIMM DDR3",
             "SO-DIMM DDR4", "SO-DIMM DDR5"]


def apply(conn: sqlite3.Connection) -> None:
    add_column(conn, "components", "stock_serial VARCHAR(40)")
    add_column(conn, "components", "ref_code VARCHAR(20)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_components_stock_serial ON components (stock_serial)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_components_ref_code ON components (ref_code)")
    row = conn.execute(
        "SELECT f.id, f.choices FROM category_fields f JOIN categories c ON c.id = f.category_id "
        "WHERE c.name = 'RAM' AND f.key = 'Tipo' AND f.type = 'choice'").fetchone()
    if row:
        try:
            current = json.loads(row[1] or "[]")
        except ValueError:
            current = []
        if isinstance(current, list):
            merged = current + [t for t in RAM_TYPES if t not in current]
            ordered = [t for t in RAM_TYPES if t in merged] + [t for t in merged if t not in RAM_TYPES]
            if ordered != current:
                conn.execute("UPDATE category_fields SET choices = ? WHERE id = ?", (json.dumps(ordered), row[0]))
