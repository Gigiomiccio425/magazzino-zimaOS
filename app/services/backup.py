"""Backup: giornaliero automatico, export zip, validazione, ripristino (con backup dello stato attuale)."""
import json
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from ..config import Settings
from ..database import make_engine
from ..migrations.runner import PRE_MIGRATION_DIR, run_migrations, rotate, snapshot_db
from ..version import APP_VERSION

DAILY_DIR = "giornalieri"
PRE_RESTORE_DIR = "pre-ripristino"
KEEP_DAILY = 14
DAILY_HOUR = 3
REQUIRED_TABLES = {"components", "machines", "movements", "categories"}
SQLITE_MAGIC = b"SQLite format 3\x00"


class BackupError(Exception):
    """Backup non valido o ripristino non riuscito (dati attuali invariati)."""


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    kind: str
    size: int
    created_at: datetime


@dataclass(frozen=True)
class BackupCheck:
    ok: bool
    reason: str | None
    schema_version: int | None


@dataclass(frozen=True)
class RestoreReport:
    pre_restore_path: Path
    from_schema: int
    to_schema: int


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def daily_backup(settings: Settings, now_local: datetime) -> Path | None:
    if now_local.hour < DAILY_HOUR or not settings.db_path.exists():
        return None
    folder = settings.backups_dir / DAILY_DIR
    dest = folder / f"{now_local:%Y-%m-%d}.db"
    if dest.exists():
        return None
    snapshot_db(settings.db_path, dest)
    rotate(folder, KEEP_DAILY)
    return dest


def _schema_version(db_file: Path) -> int:
    with closing(sqlite3.connect(db_file)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def export_zip(settings: Settings) -> Path:
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    snap = snapshot_db(settings.db_path, settings.tmp_dir / f"snapshot-{stamp}.db")
    out = settings.tmp_dir / f"magazzino-backup-{stamp}.zip"
    manifest = {"app_version": APP_VERSION, "schema_version": _schema_version(snap),
                "created_at": datetime.now().isoformat(timespec="seconds")}
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(snap, "magazzino.db")
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        if settings.uploads_dir.exists():
            for f in settings.uploads_dir.rglob("*"):
                if f.is_file():
                    z.write(f, "uploads/" + f.relative_to(settings.uploads_dir).as_posix())
    snap.unlink()
    return out


def list_backups(settings: Settings) -> list[BackupInfo]:
    out = []
    for kind in (DAILY_DIR, PRE_MIGRATION_DIR, PRE_RESTORE_DIR):
        folder = settings.backups_dir / kind
        if folder.exists():
            for f in folder.glob("*.db"):
                st = f.stat()
                out.append(BackupInfo(f, kind, st.st_size, datetime.fromtimestamp(st.st_mtime)))
    return sorted(out, key=lambda b: b.created_at, reverse=True)


def _check_db(db_file: Path) -> BackupCheck:
    try:
        with db_file.open("rb") as f:
            if f.read(16) != SQLITE_MAGIC:
                return BackupCheck(False, "Il file non è un database SQLite.", None)
        with closing(sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True)) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return BackupCheck(False, "Database danneggiato (integrity_check).", None)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        return BackupCheck(False, f"Database illeggibile: {exc}", None)
    missing = REQUIRED_TABLES - tables
    if missing:
        return BackupCheck(False, f"Mancano le tabelle: {', '.join(sorted(missing))}.", None)
    return BackupCheck(True, None, version)


def _safe_names(z: zipfile.ZipFile) -> bool:
    for name in z.namelist():
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name:
            return False
    return True


def validate_backup(path: Path) -> BackupCheck:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            if not _safe_names(z):
                return BackupCheck(False, "Archivio con percorsi non sicuri.", None)
            if "magazzino.db" not in z.namelist():
                return BackupCheck(False, "L'archivio non contiene magazzino.db.", None)
            with tempfile.TemporaryDirectory() as tmp:
                z.extract("magazzino.db", tmp)
                return _check_db(Path(tmp) / "magazzino.db")
    return _check_db(path)


def restore_backup(app, source: Path) -> RestoreReport:
    settings: Settings = app.state.settings
    check = validate_backup(source)
    if not check.ok:
        raise BackupError(check.reason)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        uploads_src = None
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as z:
                z.extractall(tmp)
            db_src = tmp / "magazzino.db"
            if (tmp / "uploads").exists():
                uploads_src = tmp / "uploads"
        else:
            db_src = source
        stamp = _stamp()
        pre = snapshot_db(settings.db_path, settings.backups_dir / PRE_RESTORE_DIR / f"{stamp}.db")
        app.state.engine.dispose()
        try:
            snapshot_db(db_src, settings.db_path)
            if uploads_src is not None:
                if settings.uploads_dir.exists():
                    shutil.move(str(settings.uploads_dir), settings.backups_dir / PRE_RESTORE_DIR / f"uploads-{stamp}")
                shutil.copytree(uploads_src, settings.uploads_dir)
            report = run_migrations(settings.db_path, settings.backups_dir)
        except Exception as exc:
            snapshot_db(pre, settings.db_path)  # rimette lo stato precedente
            raise BackupError(f"Ripristino non riuscito, dati precedenti rimessi: {exc}") from exc
        finally:
            app.state.engine = make_engine(settings.db_path)
    return RestoreReport(pre, report.from_version, report.to_version)
