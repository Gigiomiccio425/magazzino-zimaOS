"""Gestione date: salvataggio in UTC naive, visualizzazione in ora locale (TZ)."""
import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def local_zone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TZ") or "Europe/Rome")


def utcnow() -> datetime:
    """Ora attuale UTC senza tzinfo (formato storico del DB)."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_local(value: datetime) -> datetime:
    """UTC naive -> datetime aware nel fuso locale."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(local_zone())


def parse_local_input(text: str) -> datetime | None:
    """Valore di <input type=datetime-local> (ora locale) -> UTC naive."""
    text = (text or "").strip()
    if not text:
        return None
    local = datetime.fromisoformat(text).replace(tzinfo=local_zone())
    return local.astimezone(UTC).replace(tzinfo=None)


def format_local_input(value: datetime | None) -> str:
    """UTC naive -> stringa per <input type=datetime-local>."""
    if not value:
        return ""
    return to_local(value).strftime("%Y-%m-%dT%H:%M")
