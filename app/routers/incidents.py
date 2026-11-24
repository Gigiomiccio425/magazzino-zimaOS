"""Incidenti (con cronologia di aggiornamenti) e problemi noti. Tutto manuale, firmato, avvisi opzionali."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import (INCIDENT_STATUSES, PROBLEM_STATUSES, SERVICE_STATUSES, SEVERITIES, Attachment, Incident,
                      IncidentUpdate, Problem, Service)
from ..services import audit, events
from ..services.inventory import alive
from ..services.links import KIND_LABELS, links_for, links_from_form, save_links
from ..services.settings_store import base_url
from ..services.signing import SignerInfo, require_signer
from ..timeutil import parse_local_input, utcnow

router = APIRouter()


def _refuse(request: Request, status: int, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _services(db: Session, ids) -> list[Service]:
    ids = [int(i) for i in ids if str(i).isdigit()]
    return alive(db.query(Service), Service).filter(Service.id.in_(ids)).all() if ids else []


def _apply_service_statuses(request: Request, db: Session, form, services: list[Service], signer) -> list[str]:
    """Aggiorna lo stato dei servizi solo dove l'operatore ha scelto un valore."""
    changed = []
    for s in services:
        new = form.get(f"svc_status_{s.id}")
        if new in SERVICE_STATUSES and new != s.status:
            audit.record(db, entity_type="service", entity_id=s.id, action="status",
                         before={"status": s.status}, after={"status": new}, signer=signer)
            s.status = new
            changed.append(f"{s.name}: {SERVICE_STATUSES[new]}")
    return changed


def _event_data(inc: Incident, message: str | None, operator: str, extra=None) -> dict:
    fields = [["Servizi", ", ".join(s.name for s in inc.services) or "—"], ["Inizio", inc.started_at.strftime("%d/%m/%Y %H:%M")]]
    fields += extra or []
    return {"title": inc.title, "description": message or None, "url_path": f"/incidents/{inc.id}",
            "fields": fields, "severity": inc.severity, "status_label": INCIDENT_STATUSES.get(inc.status),
            "operator": operator, "resolved": inc.status == "resolved"}


@router.get("/incidents")
def incidents_list(request: Request, status: str = "", db: Session = Depends(get_db)):
    q = db.query(Incident)
    if status == "open":
        q = q.filter(Incident.status != "resolved")
    elif status in INCIDENT_STATUSES:
        q = q.filter(Incident.status == status)
    incidents = q.order_by(Incident.started_at.desc()).limit(200).all()
    return render(request, "incidents_list.html", {"incidents": incidents, "INCIDENT_STATUSES": INCIDENT_STATUSES,
                                                   "SEVERITIES": SEVERITIES, "status": status})


@router.get("/incidents/new")
def incident_new(request: Request, service: str = "", db: Session = Depends(get_db)):
    services = alive(db.query(Service), Service).order_by(Service.name).all()
    return render(request, "incident_form.html", {
        "services": services, "preselected": int(service) if service.isdigit() else None,
        "SEVERITIES": SEVERITIES, "SERVICE_STATUSES": SERVICE_STATUSES,
        "notify_default": events.default_notify(db, "incident.opened", "SEV3"),
    })


@router.post("/incidents/new")
async def incident_create(request: Request, db: Session = Depends(get_db),
                          signer: SignerInfo = Depends(require_signer())):
    form = await request.form()
    title = " ".join((form.get("title") or "").split())[:200]
    severity = form.get("severity") if form.get("severity") in SEVERITIES else "SEV3"
    if not title:
        return _refuse(request, 422, "Scrivi un titolo per l'incidente.", "/incidents/new")
    services = _services(db, form.getlist("service_ids"))
    inc = Incident(title=title, severity=severity, status="open", summary=(form.get("summary") or "").strip(),
                   started_at=parse_local_input(form.get("started_at") or "") or utcnow(),
                   operator_id=signer.operator_id)
    inc.services = services
    db.add(inc)
    db.flush()
    changed = _apply_service_statuses(request, db, form, services, signer)
    notify = form.get("notify") == "1"
    db.add(IncidentUpdate(incident_id=inc.id, status="open", message=inc.summary or "Incidente aperto",
                          operator_id=signer.operator_id, signature_id=signer.signature_id, notified=notify))
    audit.record(db, entity_type="incident", entity_id=inc.id, action="create",
                 after={"title": title, "severity": severity, "services": [s.id for s in services],
                        "service_status": changed}, signer=signer)
    events.emit(db, "incident.opened", _event_data(inc, inc.summary, signer.operator_name),
                base_url=base_url(request, db), severity=severity, service_ids=[s.id for s in services],
                notify=notify, app_name=request.app.state.settings.app_name)
    db.commit()
    flash(request, f"Incidente {severity} aperto.")
    return redirect(request, f"/incidents/{inc.id}")


@router.get("/incidents/{iid}")
def incident_detail(iid: int, request: Request, db: Session = Depends(get_db)):
    inc = db.get(Incident, iid)
    if not inc:
        flash(request, "Incidente non trovato.", "error")
        return redirect(request, "/incidents")
    problems = db.query(Problem).filter(Problem.incidents.any(Incident.id == inc.id)).all()
    return render(request, "incident_detail.html", {
        "inc": inc, "problems": problems, "INCIDENT_STATUSES": INCIDENT_STATUSES, "SEVERITIES": SEVERITIES,
        "SERVICE_STATUSES": SERVICE_STATUSES, "KIND_LABELS": KIND_LABELS, "links": links_for(db, "incident", [inc.id])[inc.id],
        "attachments": db.query(Attachment).filter_by(entity_type="incident", entity_id=inc.id, deleted_at=None).all(),
        "notify_default": events.default_notify(db, "incident.updated", inc.severity, [s.id for s in inc.services]),
    })


@router.post("/incidents/{iid}/updates")
async def incident_update(iid: int, request: Request, db: Session = Depends(get_db),
                          signer: SignerInfo = Depends(require_signer())):
    inc = db.get(Incident, iid)
    back = f"/incidents/{iid}"
    if not inc:
        return _refuse(request, 404, "Incidente non trovato.", "/incidents")
    form = await request.form()
    status = form.get("status") if form.get("status") in INCIDENT_STATUSES else inc.status
    message = (form.get("message") or "").strip()
    if not message and status == inc.status:
        return _refuse(request, 422, "Scrivi un aggiornamento o cambia lo stato.", back)
    pairs, error = links_from_form(form)
    if error:
        return _refuse(request, 422, error, back)
    old = inc.status
    inc.status = status
    if status == "resolved" and not inc.resolved_at:
        inc.resolved_at = utcnow()
    elif status != "resolved":
        inc.resolved_at = None
    if form.get("severity") in SEVERITIES:
        inc.severity = form.get("severity")
    changed = _apply_service_statuses(request, db, form, inc.services, signer)
    notify = form.get("notify") == "1"
    db.add(IncidentUpdate(incident_id=inc.id, status=status, message=message, operator_id=signer.operator_id,
                          signature_id=signer.signature_id, notified=notify))
    save_links(db, "incident", inc.id, pairs)
    audit.record(db, entity_type="incident", entity_id=inc.id, action="update",
                 before={"status": old}, after={"status": status, "message": message, "service_status": changed},
                 signer=signer)
    event = "incident.resolved" if status == "resolved" and old != "resolved" else "incident.updated"
    events.emit(db, event, _event_data(inc, message, signer.operator_name), base_url=base_url(request, db),
                severity=inc.severity, service_ids=[s.id for s in inc.services], notify=notify,
                app_name=request.app.state.settings.app_name)
    db.commit()
    flash(request, f"Incidente aggiornato: {INCIDENT_STATUSES[status]}.")
    return redirect(request, back)


@router.post("/incidents/{iid}/postmortem")
async def incident_postmortem(iid: int, request: Request, db: Session = Depends(get_db),
                              signer: SignerInfo = Depends(require_signer())):
    inc = db.get(Incident, iid)
    if not inc:
        return _refuse(request, 404, "Incidente non trovato.", "/incidents")
    form = await request.form()
    before = {"root_cause": inc.root_cause, "postmortem_md": inc.postmortem_md}
    inc.root_cause = (form.get("root_cause") or "").strip()
    inc.postmortem_md = (form.get("postmortem_md") or "").strip()
    b, a = audit.changed(before, {"root_cause": inc.root_cause, "postmortem_md": inc.postmortem_md})
    if a or b:
        audit.record(db, entity_type="incident", entity_id=inc.id, action="postmortem", before=b, after=a,
                     signer=signer)
    db.commit()
    flash(request, "Analisi salvata.")
    return redirect(request, f"/incidents/{iid}")


# ---- Problemi noti ----

@router.get("/problems")
def problems_list(request: Request, db: Session = Depends(get_db)):
    problems = db.query(Problem).order_by(Problem.status, Problem.id.desc()).all()
    return render(request, "problems_list.html", {"problems": problems, "PROBLEM_STATUSES": PROBLEM_STATUSES})


def _problem_ctx(db: Session, p: Problem | None) -> dict:
    return {"p": p, "services": alive(db.query(Service), Service).order_by(Service.name).all(),
            "incidents": db.query(Incident).order_by(Incident.started_at.desc()).limit(100).all(),
            "PROBLEM_STATUSES": PROBLEM_STATUSES}


@router.get("/problems/new")
def problem_new(request: Request, db: Session = Depends(get_db)):
    return render(request, "problem_form.html", _problem_ctx(db, None))


@router.get("/problems/{pid}")
def problem_edit(pid: int, request: Request, db: Session = Depends(get_db)):
    p = db.get(Problem, pid)
    if not p:
        flash(request, "Problema non trovato.", "error")
        return redirect(request, "/problems")
    return render(request, "problem_form.html", _problem_ctx(db, p))


async def _save_problem(request: Request, db: Session, p: Problem | None, signer):
    form = await request.form()
    title = " ".join((form.get("title") or "").split())[:200]
    if not title:
        return _refuse(request, 422, "Scrivi un titolo.", "/problems/new" if p is None else f"/problems/{p.id}")
    created = p is None
    if created:
        p = Problem()
        db.add(p)
    p.title = title
    p.description_md = (form.get("description_md") or "").strip()
    p.workaround_md = (form.get("workaround_md") or "").strip()
    p.status = form.get("status") if form.get("status") in PROBLEM_STATUSES else "open"
    p.services = _services(db, form.getlist("service_ids"))
    ids = [int(i) for i in form.getlist("incident_ids") if str(i).isdigit()]
    p.incidents = db.query(Incident).filter(Incident.id.in_(ids)).all() if ids else []
    db.flush()
    audit.record(db, entity_type="problem", entity_id=p.id, action="create" if created else "update",
                 after={"title": p.title, "status": p.status, "services": [s.id for s in p.services],
                        "incidents": ids}, signer=signer)
    db.commit()
    flash(request, "Problema noto salvato.")
    return redirect(request, "/problems")


@router.post("/problems/new")
async def problem_create(request: Request, db: Session = Depends(get_db),
                         signer: SignerInfo = Depends(require_signer())):
    return await _save_problem(request, db, None, signer)


@router.post("/problems/{pid}")
async def problem_update(pid: int, request: Request, db: Session = Depends(get_db),
                         signer: SignerInfo = Depends(require_signer())):
    p = db.get(Problem, pid)
    if not p:
        return _refuse(request, 404, "Problema non trovato.", "/problems")
    return await _save_problem(request, db, p, signer)
