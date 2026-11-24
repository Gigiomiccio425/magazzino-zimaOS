"""Inventario fisico: elenco atteso di una posizione, scansioni, mancanti e fuori posto, chiusura firmata."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import AUDIT_ITEM_STATES, Component, InventoryAudit, InventoryAuditItem, Location
from ..services import audit as audit_log
from ..services import events
from ..services.inventory import add_movement
from ..services.locations import descendant_ids, location_options, location_path
from ..services.qr import resolve_scan
from ..services.settings_store import base_url, get_setting
from ..services.signing import SignerInfo, require_signer
from ..timeutil import utcnow

router = APIRouter()


class ScanBody(BaseModel):
    value: str


def _refuse(request: Request, status: int, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def overdue_locations(db: Session) -> list[Location]:
    days = int(get_setting(db, "audit_interval_days") or 180)
    limit = utcnow() - timedelta(days=days)
    q = db.query(Location).filter(Location.deleted_at.is_(None))
    return [loc for loc in q.order_by(Location.name) if loc.last_audit_at is None or loc.last_audit_at < limit]


@router.get("/audits")
def audits_list(request: Request, db: Session = Depends(get_db)):
    audits = db.query(InventoryAudit).order_by(InventoryAudit.id.desc()).limit(50).all()
    paths = dict(location_options(db))
    return render(request, "audits_list.html", {
        "audits": audits, "overdue": overdue_locations(db), "paths": paths, "locations": location_options(db),
        "interval": get_setting(db, "audit_interval_days"),
    })


@router.post("/audits/new")
def audit_start(request: Request, location_id: str = Form(""), include_children: str = Form(""),
                db: Session = Depends(get_db), signer: SignerInfo = Depends(require_signer())):
    loc = db.get(Location, int(location_id)) if location_id.isdigit() else None
    if not loc or loc.deleted_at:
        return _refuse(request, 422, "Scegli una posizione.", "/audits")
    children = include_children == "1"
    ids = descendant_ids(db, loc.id) if children else [loc.id]
    a = InventoryAudit(location_id=loc.id, include_children=children, status="open",
                       operator_id=signer.operator_id, signature_id=signer.signature_id, summary={})
    db.add(a)
    db.flush()
    comps = db.query(Component).filter(Component.deleted_at.is_(None), Component.location_id.in_(ids)).all()
    db.add_all(InventoryAuditItem(audit_id=a.id, component_id=c.id, state="expected") for c in comps)
    audit_log.record(db, entity_type="inventory_audit", entity_id=a.id, action="start",
                     after={"location": location_path(loc), "expected": len(comps)}, signer=signer)
    db.commit()
    return redirect(request, f"/audits/{a.id}")


@router.get("/audits/{audit_id}")
def audit_run(audit_id: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(InventoryAudit, audit_id)
    if not a:
        flash(request, "Inventario non trovato.", "error")
        return redirect(request, "/audits")
    groups = {s: [i for i in a.items if i.state == s] for s in AUDIT_ITEM_STATES}
    return render(request, "audit_run.html", {"a": a, "groups": groups, "STATES": AUDIT_ITEM_STATES,
                                              "path": location_path(a.location),
                                              "notify_default": events.default_notify(db, "audit.completed")})


@router.post("/audits/{audit_id}/scan")
def audit_scan(audit_id: int, body: ScanBody, db: Session = Depends(get_db),
               signer: SignerInfo = Depends(require_signer())):
    a = db.get(InventoryAudit, audit_id)
    if not a:
        return JSONResponse({"state": "unknown", "component": None}, status_code=404)
    if a.status != "open":
        return {"state": "closed", "component": None}
    target = resolve_scan(db, body.value).get("url", "")
    if not target.startswith("/components/"):
        return {"state": "unknown", "component": None}
    comp = db.get(Component, int(target.rsplit("/", 1)[1]))
    item = next((i for i in a.items if i.component_id == comp.id), None)
    now = utcnow()
    if item is None:
        item = InventoryAuditItem(audit_id=a.id, component_id=comp.id, state="unexpected", scanned_at=now)
        db.add(item)
    elif item.state == "expected":
        item.state, item.scanned_at = "found", now
    db.commit()
    return {"state": item.state, "component": comp.name, "tag": comp.asset_tag}


@router.post("/audits/{audit_id}/items/{item_id}/move-here")
def audit_move_here(audit_id: int, item_id: int, request: Request, db: Session = Depends(get_db),
                    signer: SignerInfo = Depends(require_signer())):
    a = db.get(InventoryAudit, audit_id)
    item = db.get(InventoryAuditItem, item_id)
    if not a or not item or item.audit_id != a.id or item.state != "unexpected":
        return _refuse(request, 422, "Elemento non valido.", f"/audits/{audit_id}")
    comp = item.component
    old = comp.location_id
    comp.location_id = a.location_id
    item.state = "found"
    add_movement(db, comp, signer, "moved", note=f"Inventario: spostato in {location_path(a.location)}")
    audit_log.record(db, entity_type="component", entity_id=comp.id, action="update",
                     before={"location_id": old}, after={"location_id": a.location_id}, signer=signer)
    db.commit()
    flash(request, f"\"{comp.name}\" spostato qui.")
    return redirect(request, f"/audits/{a.id}")


@router.post("/audits/{audit_id}/finish")
def audit_finish(audit_id: int, request: Request, notify: str = Form(""), db: Session = Depends(get_db),
                 signer: SignerInfo = Depends(require_signer())):
    a = db.get(InventoryAudit, audit_id)
    if not a or a.status != "open":
        return _refuse(request, 422, "Inventario già chiuso.", "/audits")
    now = utcnow()
    for item in a.items:
        if item.state == "expected":
            item.state = "missing"
        elif item.state == "found":
            item.component.last_audit_at = now
    ids = descendant_ids(db, a.location_id) if a.include_children else [a.location_id]
    for loc in db.query(Location).filter(Location.id.in_(ids)):
        loc.last_audit_at = now
    summary = {s: sum(1 for i in a.items if i.state == s) for s in ("found", "missing", "unexpected")}
    a.status, a.finished_at, a.summary = "done", now, summary
    audit_log.record(db, entity_type="inventory_audit", entity_id=a.id, action="finish", after=summary, signer=signer)
    events.emit(db, "audit.completed", {
        "title": location_path(a.location), "url_path": f"/audits/{a.id}",
        "description": f"Trovati {summary['found']}, mancanti {summary['missing']}, fuori posto {summary['unexpected']}.",
        "fields": [], "operator": signer.operator_name,
    }, base_url=base_url(request, db), notify=notify == "1", app_name=request.app.state.settings.app_name)
    db.commit()
    flash(request, f"Inventario chiuso: {summary['found']} trovati, {summary['missing']} mancanti.")
    return redirect(request, f"/audits/{a.id}")
