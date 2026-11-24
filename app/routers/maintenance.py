"""Manutenzioni programmate (avvio/chiusura sempre manuali) e pagina di stato in sola lettura."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import (INCIDENT_STATUSES, MAINTENANCE_STATUSES, SERVICE_STATUSES, SEVERITIES, Incident, Maintenance,
                      Service)
from ..services import audit, events
from ..services.inventory import alive
from ..services.settings_store import base_url
from ..services.signing import SignerInfo, require_signer
from ..timeutil import parse_local_input, utcnow

router = APIRouter()
TRANSITIONS = {
    "start": ("scheduled", "in_progress", "maintenance.started", "maintenance"),
    "complete": ("in_progress", "completed", "maintenance.completed", "operational"),
    "cancel": ("scheduled", "cancelled", "maintenance.cancelled", None),
}


def _refuse(request: Request, status: int, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _data(m: Maintenance, operator: str) -> dict:
    return {"title": m.title, "description": m.description_md[:1500] or None, "url_path": "/maintenance",
            "fields": [["Servizi", ", ".join(s.name for s in m.services) or "—"],
                       ["Inizio", m.starts_at.strftime("%d/%m/%Y %H:%M")], ["Fine", m.ends_at.strftime("%d/%m/%Y %H:%M")]],
            "status_label": MAINTENANCE_STATUSES.get(m.status), "operator": operator,
            "resolved": m.status == "completed"}


@router.get("/maintenance")
def maintenance_list(request: Request, db: Session = Depends(get_db)):
    items = db.query(Maintenance).order_by(Maintenance.starts_at.desc()).limit(100).all()
    services = alive(db.query(Service), Service).order_by(Service.name).all()
    return render(request, "maintenance_list.html", {
        "items": items, "services": services, "now": utcnow(), "STATUSES": MAINTENANCE_STATUSES,
        "notify_default": events.default_notify(db, "maintenance.scheduled"),
    })


@router.post("/maintenance/new")
async def maintenance_create(request: Request, db: Session = Depends(get_db),
                             signer: SignerInfo = Depends(require_signer())):
    form = await request.form()
    title = " ".join((form.get("title") or "").split())[:200]
    try:
        start = parse_local_input(form.get("starts_at") or "")
        end = parse_local_input(form.get("ends_at") or "")
    except ValueError:
        start = end = None
    if not title or not start or not end:
        return _refuse(request, 422, "Titolo, inizio e fine sono obbligatori.", "/maintenance")
    if end <= start:
        return _refuse(request, 422, "La fine deve essere dopo l'inizio.", "/maintenance")
    ids = [int(i) for i in form.getlist("service_ids") if str(i).isdigit()]
    m = Maintenance(title=title, description_md=(form.get("description_md") or "").strip(), starts_at=start,
                    ends_at=end, status="scheduled")
    m.services = alive(db.query(Service), Service).filter(Service.id.in_(ids)).all() if ids else []
    db.add(m)
    db.flush()
    audit.record(db, entity_type="maintenance", entity_id=m.id, action="create",
                 after={"title": title, "starts_at": start, "ends_at": end, "services": ids}, signer=signer)
    events.emit(db, "maintenance.scheduled", _data(m, signer.operator_name), base_url=base_url(request, db),
                service_ids=ids, notify=form.get("notify") == "1", app_name=request.app.state.settings.app_name)
    db.commit()
    flash(request, "Manutenzione programmata.")
    return redirect(request, "/maintenance")


@router.post("/maintenance/{mid}/{action}")
def maintenance_transition(mid: int, action: str, request: Request, set_service_status: str = Form(""),
                           notify: str = Form(""), db: Session = Depends(get_db),
                           signer: SignerInfo = Depends(require_signer())):
    m = db.get(Maintenance, mid)
    if not m or action not in TRANSITIONS:
        return _refuse(request, 404, "Manutenzione non trovata.", "/maintenance")
    allowed_from, to, event, svc_status = TRANSITIONS[action]
    if m.status != allowed_from and not (action == "cancel" and m.status == "in_progress"):
        return _refuse(request, 422, "Passaggio di stato non consentito.", "/maintenance")
    old = m.status
    m.status = to
    changed = []
    if svc_status and set_service_status == "1":
        for s in m.services:
            if s.status != svc_status:
                audit.record(db, entity_type="service", entity_id=s.id, action="status",
                             before={"status": s.status}, after={"status": svc_status}, signer=signer)
                s.status = svc_status
                changed.append(s.name)
    audit.record(db, entity_type="maintenance", entity_id=m.id, action=action, before={"status": old},
                 after={"status": to, "services_updated": changed}, signer=signer)
    events.emit(db, event, _data(m, signer.operator_name), base_url=base_url(request, db),
                service_ids=[s.id for s in m.services], notify=notify == "1",
                app_name=request.app.state.settings.app_name)
    db.commit()
    flash(request, f"Manutenzione: {MAINTENANCE_STATUSES[to]}.")
    return redirect(request, "/maintenance")


@router.get("/status")
def status_page(request: Request, db: Session = Depends(get_db)):
    now = utcnow()
    services = alive(db.query(Service), Service).order_by(Service.name).all()
    active = db.query(Incident).filter(Incident.status != "resolved").order_by(Incident.started_at.desc()).all()
    history = (db.query(Incident).filter(Incident.status == "resolved", Incident.resolved_at >= now - timedelta(days=30))
               .order_by(Incident.resolved_at.desc()).all())
    maint = (db.query(Maintenance).filter(Maintenance.status.in_(["scheduled", "in_progress"]))
             .order_by(Maintenance.starts_at).all())
    worst = "operational"
    order = list(SERVICE_STATUSES)
    for s in services:
        if order.index(s.status) > order.index(worst) and s.status != "maintenance":
            worst = s.status
    return render(request, "status.html", {
        "services": services, "active": active, "history": history, "maint": maint, "worst": worst,
        "SERVICE_STATUSES": SERVICE_STATUSES, "INCIDENT_STATUSES": INCIDENT_STATUSES, "SEVERITIES": SEVERITIES,
        "MAINTENANCE_STATUSES": MAINTENANCE_STATUSES,
    })
