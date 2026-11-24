"""Impostazioni chiave/valore. Valore salvato come {"v": valore} (vedi models/system.py)."""
from fastapi import Request
from sqlalchemy.orm import Session

from ..models import Setting

DEFAULTS = {"signature_window_min": 10, "audit_interval_days": 180, "public_base_url": ""}


def get_setting(db: Session, key: str):
    row = db.get(Setting, key)
    if row is not None and isinstance(row.value, dict) and "v" in row.value:
        return row.value["v"]
    return DEFAULTS.get(key)


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value={"v": value}))
    else:
        row.value = {"v": value}
    db.flush()


def base_url(request: Request, db: Session) -> str:
    """URL pubblico per QR e link nei webhook: impostazione -> env PUBLIC_BASE_URL -> richiesta."""
    url = get_setting(db, "public_base_url") or request.app.state.settings.public_base_url or str(request.base_url)
    return url.rstrip("/")
