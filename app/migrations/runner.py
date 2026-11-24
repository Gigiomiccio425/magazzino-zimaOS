"""Runner migrazioni: versione in PRAGMA user_version, backup prima, tutto in una transazione.

Regole (spec 7): mai DROP o RENAME di colonne esistenti; SQL grezzo indipendente dai modelli
ORM; se qualcosa fallisce si fa ROLLBACK e il file resta com'era.
"""
import hashlib
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import m0001_baseline, m0002_schema_v2
from .util import add_column  # noqa: F401  (riesportato)

log = logging.getLogger("magazzino.migrations")

PRE_MIGRATION_DIR = "pre-migrazione"
KEEP_PRE_MIGRATION = 10


class MigrationError(Exception):
    """Migrazione non applicabile: il DB e' rimasto invariato."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class MigrationReport:
    from_version: int
    to_version: int
    backup_path: Path | None


MIGRATIONS: list[Migration] = [
    Migration(1, "baseline v1.1.1", m0001_baseline.apply),
    Migration(2, "schema v2", m0002_schema_v2.apply),
]
LATEST_VERSION = max(m.version for m in MIGRATIONS)


def snapshot_db(src: Path, dest: Path) -> Path:
    """Copia consistente del DB con l'API di backup SQLite (funziona anche in WAL)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(src) as source, sqlite3.connect(dest) as target:
        source.backup(target)
    return dest


def rotate(directory: Path, keep: int, pattern: str = "*.db") -> list[Path]:
    """Tiene i `keep` file piu' recenti (per mtime); ritorna quelli rimossi."""
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = files[keep:]
    for f in removed:
        f.unlink()
    return removed


def _file_sha8(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def _pre_migration_backup(db_path: Path, backups_dir: Path, from_v: int, to_v: int) -> Path:
    folder = backups_dir / PRE_MIGRATION_DIR
    prefix = f"v{from_v}-a-v{to_v}-{_file_sha8(db_path)}-"
    existing = sorted(folder.glob(prefix + "*.db")) if folder.exists() else []
    if existing:
        return existing[-1]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = snapshot_db(db_path, folder / f"{prefix}{stamp}.db")
    rotate(folder, KEEP_PRE_MIGRATION)
    return dest


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


def run_migrations(db_path: Path, backups_dir: Path) -> MigrationReport:
    latest = max(m.version for m in MIGRATIONS)
    is_new = not db_path.exists() or db_path.stat().st_size == 0
    backup: Path | None = None
    try:
        conn = _open(db_path)
        try:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            if current >= latest:
                return MigrationReport(current, current, None)
            if not is_new:
                check = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if check != "ok":
                    raise MigrationError(f"integrity_check fallito: {check}")
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise MigrationError(f"DB illeggibile: {exc}") from exc

    if not is_new:
        backup = _pre_migration_backup(db_path, backups_dir, current, latest)
        log.info("Backup pre-migrazione: %s", backup)

    conn = _open(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for m in sorted(MIGRATIONS, key=lambda m: m.version):
            if m.version > current:
                log.info("Migrazione %s: %s", m.version, m.name)
                m.apply(conn)
        conn.execute(f"PRAGMA user_version = {latest}")
        conn.execute("COMMIT")
    except Exception as exc:
        conn.execute("ROLLBACK")
        raise MigrationError(f"Migrazione fallita (DB invariato): {exc}") from exc
    finally:
        conn.close()
    return MigrationReport(current, latest, backup)
