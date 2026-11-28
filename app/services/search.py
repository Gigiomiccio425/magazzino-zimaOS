"""Ricerca globale (Ctrl+K): componenti, posizioni, macchine, servizi, incidenti, changelog, operatori."""
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import Change, Component, Incident, Location, Machine, Operator, Service

MIN_LEN = 2


@dataclass
class SearchHit:
    title: str
    subtitle: str
    url: str


@dataclass
class SearchGroup:
    label: str
    items: list[SearchHit]


def global_search(db: Session, q: str, limit: int = 6) -> list[SearchGroup]:
    q = (q or "").strip()
    if len(q) < MIN_LEN:
        return []
    like = f"%{q}%"
    groups: list[SearchGroup] = []

    def add(label, rows, fn):
        hits = [fn(r) for r in rows]
        if hits:
            groups.append(SearchGroup(label, hits))

    add("Componenti", db.query(Component).filter(
        Component.deleted_at.is_(None),
        or_(Component.name.ilike(like), Component.asset_tag.ilike(like), Component.serial_number.ilike(like),
            Component.stock_serial.ilike(like), Component.ref_code.ilike(like),
            Component.object_code.ilike(like), Component.model.ilike(like)),
    ).order_by(Component.name).limit(limit),
        lambda c: SearchHit(c.name, " · ".join(x for x in [c.asset_tag, c.stock_serial, c.category, c.serial_number] if x),
                            f"/components/{c.id}"))
    add("Posizioni", db.query(Location).filter(
        Location.deleted_at.is_(None), or_(Location.name.ilike(like), Location.asset_tag.ilike(like)),
    ).order_by(Location.name).limit(limit), lambda l: SearchHit(l.name, l.asset_tag or "", f"/locations/{l.id}"))
    add("Macchine", db.query(Machine).filter(
        Machine.deleted_at.is_(None),
        or_(Machine.name.ilike(like), Machine.asset_tag.ilike(like), Machine.hostname.ilike(like),
            Machine.ip_address.ilike(like)),
    ).order_by(Machine.name).limit(limit), lambda m: SearchHit(m.name, m.asset_tag or "", f"/machines/{m.id}"))
    add("Servizi", db.query(Service).filter(Service.deleted_at.is_(None), Service.name.ilike(like))
        .order_by(Service.name).limit(limit), lambda s: SearchHit(s.name, s.status, f"/services/{s.id}"))
    add("Incidenti", db.query(Incident).filter(Incident.title.ilike(like)).order_by(Incident.started_at.desc())
        .limit(limit), lambda i: SearchHit(i.title, f"{i.severity} · {i.status}", f"/incidents/{i.id}"))
    add("Changelog", db.query(Change).filter(or_(Change.title.ilike(like), Change.version.ilike(like)))
        .order_by(Change.occurred_at.desc()).limit(limit),
        lambda c: SearchHit(c.title, f"{c.service.name}{' · v' + c.version if c.version else ''}",
                            f"/services/{c.service_id}"))
    add("Operatori", db.query(Operator).filter(Operator.name.ilike(like)).order_by(Operator.name).limit(limit),
        lambda o: SearchHit(o.name, "operatore", f"/audit?operator={o.id}"))
    return groups
