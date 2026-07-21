"""Dashboard: statistiche + movimenti recenti."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import render
from ..models import (
    STATUS_FAULTY,
    STATUS_IN_USE,
    STATUS_STOCK,
    Component,
    Machine,
    Movement,
)

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    total = db.query(func.count(Component.id)).scalar() or 0
    in_stock = db.query(func.count(Component.id)).filter(Component.status == STATUS_STOCK).scalar() or 0
    in_use = db.query(func.count(Component.id)).filter(Component.status == STATUS_IN_USE).scalar() or 0
    faulty = db.query(func.count(Component.id)).filter(Component.status == STATUS_FAULTY).scalar() or 0
    machines_count = db.query(func.count(Machine.id)).scalar() or 0
    # Quantita totale pezzi (somma quantity)
    total_units = db.query(func.coalesce(func.sum(Component.quantity), 0)).scalar() or 0

    recent = db.query(Movement).order_by(Movement.timestamp.desc()).limit(8).all()

    # Conteggio per categoria (per barre)
    by_category = (
        db.query(Component.category, func.count(Component.id))
        .group_by(Component.category)
        .order_by(func.count(Component.id).desc())
        .all()
    )
    cat_max = max([c for _, c in by_category], default=1)

    return render(request, "dashboard.html", {
        "stats": {
            "total": total,
            "units": total_units,
            "stock": in_stock,
            "in_use": in_use,
            "faulty": faulty,
            "machines": machines_count,
        },
        "recent": recent,
        "by_category": by_category,
        "cat_max": cat_max,
    })
