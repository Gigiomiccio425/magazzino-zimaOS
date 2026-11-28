"""Avvisi: garanzie in scadenza e manutenzioni imminenti (dashboard + webhook, una volta sola)."""
from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import Component, Maintenance
from ..timeutil import to_local, utcnow
from . import events
from .settings_store import get_setting

WARRANTY_DAYS = 30
MAINTENANCE_HOURS = 24


def expiring_warranties(db: Session, days: int = 60) -> list[Component]:
    today = utcnow().date()
    return (db.query(Component)
            .filter(Component.deleted_at.is_(None), Component.warranty_until.isnot(None),
                    Component.warranty_until >= today, Component.warranty_until <= today + timedelta(days=days),
                    Component.status.notin_(("sold", "retired")))
            .order_by(Component.warranty_until).all())


def upcoming_maintenances(db: Session, days: int = 7) -> list[Maintenance]:
    now = utcnow()
    return (db.query(Maintenance).filter(Maintenance.status == "scheduled", Maintenance.starts_at >= now,
                                         Maintenance.starts_at <= now + timedelta(days=days))
            .order_by(Maintenance.starts_at).all())


def run(db: Session, app_name: str = "MAGAZZINO") -> int:
    """Invia gli avvisi dovuti e li segna come inviati. Ritorna quanti avvisi ha creato."""
    base = get_setting(db, "public_base_url") or ""
    sent = 0
    due = [c for c in expiring_warranties(db, WARRANTY_DAYS) if c.warranty_notified_at is None]
    if due:
        events.emit(db, "warranty.expiring", {
            "title": f"{len(due)} garanzi{'a' if len(due) == 1 else 'e'} in scadenza entro {WARRANTY_DAYS} giorni",
            "description": "\n".join(f"{c.name} ({c.asset_tag}): {c.warranty_until:%d/%m/%Y}" for c in due[:20]),
            "url_path": "/", "fields": [], "status_label": "Garanzia", "operator": "Sistema", "resolved": False,
        }, base_url=base, app_name=app_name)
        for c in due:
            c.warranty_notified_at = utcnow()
        sent += 1
    soon = utcnow() + timedelta(hours=MAINTENANCE_HOURS)
    for m in upcoming_maintenances(db, 2):
        if m.reminded_at is None and m.starts_at <= soon:
            events.emit(db, "maintenance.reminder", {
                "title": f"Domani: {m.title}", "description": f"Inizio {to_local(m.starts_at):%d/%m/%Y %H:%M}",
                "url_path": "/maintenance", "fields": [], "status_label": "Promemoria", "operator": "Sistema",
                "resolved": False,
            }, base_url=base, app_name=app_name)
            m.reminded_at = utcnow()
            sent += 1
    db.commit()
    return sent
