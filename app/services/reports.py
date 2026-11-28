"""Report: valore per categoria (acquisto e attuale), consumi, guasti per marca e modello, pezzi fermi."""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Component, Movement, TestRun
from ..timeutil import utcnow
from . import valuation

BAD_STATUSES = ("faulty", "rma", "repair")


def value_by_category(db: Session) -> list[dict]:
    lives = valuation.life_by_category(db)
    rows: dict[str, dict] = defaultdict(lambda: {"bought": 0, "current": 0, "count": 0, "priced": 0})
    for c in db.query(Component).filter(Component.deleted_at.is_(None), Component.status.notin_(("sold",))):
        r = rows[c.category or "Senza categoria"]
        r["count"] += max(1, c.quantity or 1) if c.tracking == "quantity" else 1
        if c.purchase_price is not None:
            qty = max(1, c.quantity or 1) if c.tracking == "quantity" else 1
            r["bought"] += c.purchase_price * qty
            r["current"] += valuation.current_value(c, lives.get(c.category)) or 0
            r["priced"] += 1
    out = [{"category": k, **v} for k, v in rows.items()]
    return sorted(out, key=lambda r: (-r["bought"], r["category"]))


def consumption(db: Session, days: int = 90) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    q = (db.query(Component.category, Component.name, Component.unit, func.sum(Movement.qty_delta))
         .join(Movement, Movement.component_id == Component.id)
         .filter(Movement.timestamp >= since, Movement.qty_delta < 0)
         .group_by(Component.id).order_by(func.sum(Movement.qty_delta)))
    return [{"category": cat or "—", "name": name, "unit": unit or "pz", "used": -int(total)} for cat, name, unit, total in q.limit(20)]


def faults(db: Session) -> list[dict]:
    rows: dict[tuple, dict] = defaultdict(lambda: {"total": 0, "bad": 0, "failed_tests": 0})
    for c in db.query(Component).filter(Component.deleted_at.is_(None)):
        key = ((c.manufacturer or "—").strip(), (c.model or c.name or "—").strip())
        rows[key]["total"] += 1
        if c.status in BAD_STATUSES:
            rows[key]["bad"] += 1
    failed = (db.query(Component.manufacturer, Component.model, Component.name, func.count(TestRun.id))
              .join(TestRun, TestRun.component_id == Component.id).filter(TestRun.result == "fail")
              .group_by(Component.id))
    for maker, model, name, n in failed:
        rows[((maker or "—").strip(), (model or name or "—").strip())]["failed_tests"] += n
    out = [{"manufacturer": k[0], "model": k[1], **v, "rate": round(100 * v["bad"] / v["total"]) if v["total"] else 0}
           for k, v in rows.items() if v["bad"] or v["failed_tests"]]
    return sorted(out, key=lambda r: (-r["bad"], -r["failed_tests"], r["manufacturer"]))[:20]


def idle(db: Session, days: int = 180) -> list[dict]:
    limit = utcnow() - timedelta(days=days)
    last = dict(db.query(Movement.component_id, func.max(Movement.timestamp)).group_by(Movement.component_id))
    out = []
    for c in db.query(Component).filter(Component.deleted_at.is_(None), Component.status == "stock"):
        when = last.get(c.id) or c.created_at
        if when and when < limit:
            out.append({"component": c, "since": when, "days": (utcnow() - when).days})
    return sorted(out, key=lambda r: -r["days"])[:30]
