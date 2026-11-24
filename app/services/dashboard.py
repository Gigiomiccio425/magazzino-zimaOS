"""Dati della dashboard 'centro di comando' (solo lettura)."""
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (STATUS_FAULTY, STATUS_IN_USE, STATUS_STOCK, STATUS_TO_TEST, AuditLog, Component, Incident,
                      Machine, Maintenance, Movement, Service)
from .settings_store import get_setting

UPCOMING_DAYS = 7
WARRANTY_DAYS = 30


def command_center(db: Session, now: datetime) -> dict:
    live = Component.deleted_at.is_(None)

    def count(*f):
        return db.query(func.count(Component.id)).filter(live, *f).scalar() or 0

    services_by_status = dict(
        db.query(Service.status, func.count(Service.id)).filter(Service.deleted_at.is_(None))
        .group_by(Service.status).all()
    )
    open_incidents = (db.query(Incident).filter(Incident.status != "resolved")
                      .order_by(Incident.severity, Incident.started_at.desc()).all())
    by_sev: dict[str, int] = {}
    for i in open_incidents:
        by_sev[i.severity] = by_sev.get(i.severity, 0) + 1
    upcoming = (db.query(Maintenance)
                .filter(Maintenance.status.in_(["scheduled", "in_progress"]),
                        Maintenance.starts_at <= now + timedelta(days=UPCOMING_DAYS))
                .order_by(Maintenance.starts_at).all())
    low_stock = (db.query(Component).filter(live, Component.tracking == "quantity", Component.min_stock.isnot(None),
                                            Component.quantity < Component.min_stock)
                 .order_by(Component.name).all())
    today = now.date()
    warranty = (db.query(Component).filter(live, Component.warranty_until.isnot(None),
                                           Component.warranty_until >= today,
                                           Component.warranty_until <= today + timedelta(days=WARRANTY_DAYS))
                .order_by(Component.warranty_until).all())
    from ..routers.audits import overdue_locations  # evita import circolare a livello di modulo

    by_category = (db.query(Component.category, func.count(Component.id)).filter(live)
                   .group_by(Component.category).order_by(func.count(Component.id).desc()).all())
    return {
        "services_by_status": services_by_status,
        "open_incidents": open_incidents,
        "open_incidents_by_severity": by_sev,
        "upcoming_maintenance": upcoming,
        "low_stock": low_stock,
        "to_test_count": count(Component.status == STATUS_TO_TEST),
        "warranty_expiring": warranty,
        "overdue_locations": overdue_locations(db),
        "audit_interval_days": get_setting(db, "audit_interval_days"),
        "inventory_value_cents": db.query(func.coalesce(func.sum(Component.purchase_price), 0)).filter(live).scalar() or 0,
        "recent_activity": db.query(AuditLog).order_by(AuditLog.id.desc()).limit(10).all(),
        "recent_movements": (db.query(Movement).join(Component, Movement.component_id == Component.id).filter(live)
                             .order_by(Movement.timestamp.desc()).limit(8).all()),
        "by_category": by_category,
        "cat_max": max([c for _, c in by_category], default=1),
        "stats": {
            "total": count(),
            "units": db.query(func.coalesce(func.sum(Component.quantity), 0)).filter(live).scalar() or 0,
            "stock": count(Component.status == STATUS_STOCK),
            "in_use": count(Component.status == STATUS_IN_USE),
            "faulty": count(Component.status == STATUS_FAULTY),
            "machines": db.query(func.count(Machine.id)).filter(Machine.deleted_at.is_(None)).scalar() or 0,
        },
    }
