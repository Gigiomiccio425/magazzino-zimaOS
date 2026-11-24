"""Pagine audit log e verifica integrita' della catena."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import render
from ..models import AuditLog, Operator
from ..services import audit

router = APIRouter()
PAGE = 100


@router.get("/audit")
def audit_page(request: Request, entity: str = "", operator: str = "", page: int = 1, db: Session = Depends(get_db)):
    q = db.query(AuditLog).options(joinedload(AuditLog.operator))
    if entity:
        q = q.filter(AuditLog.entity_type == entity)
    if operator.isdigit():
        q = q.filter(AuditLog.operator_id == int(operator))
    page = max(page, 1)
    rows = q.order_by(AuditLog.id.desc()).offset((page - 1) * PAGE).limit(PAGE + 1).all()
    entities = [e for (e,) in db.query(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)]
    operators = db.query(Operator).order_by(Operator.name).all()
    return render(request, "audit_log.html", {
        "rows": rows[:PAGE], "has_next": len(rows) > PAGE, "page": page,
        "entities": entities, "operators": operators,
        "filters": {"entity": entity, "operator": operator},
    })


@router.get("/audit/verify")
def audit_verify(request: Request, db: Session = Depends(get_db)):
    return render(request, "audit_verify.html", {"report": audit.verify_chain(db)})
