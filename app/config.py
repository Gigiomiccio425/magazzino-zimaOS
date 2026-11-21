"""Configurazione: variabili ambiente + chiave segreta persistente."""
import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    app_name: str
    secret_key: str
    public_base_url: str
    webauthn_rp_id: str | None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "magazzino.db"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"


def _secret_key(data_dir: Path) -> str:
    """Priorita: env SECRET_KEY -> file persistente .secret_key -> nuova chiave salvata."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = data_dir / ".secret_key"
    if path.exists():
        saved = path.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    key = secrets.token_hex(32)
    path.write_text(key, encoding="utf-8")
    return key


def load_settings(data_dir: str | Path | None = None) -> Settings:
    base = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    base.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=base,
        app_name=os.environ.get("APP_NAME", "MAGAZZINO"),
        secret_key=_secret_key(base),
        public_base_url=os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/"),
        webauthn_rp_id=os.environ.get("WEBAUTHN_RP_ID") or None,
    )
