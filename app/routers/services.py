"""Centro di comando: servizi, moduli, changelog (tutto inserito a mano e firmato)."""
import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import (CHANGE_TYPES, INCIDENT_STATUSES, MODULE_KINDS, SERVICE_STATUSES, SEVERITIES, Attachment, Change,
                      Incident, Machine, Service, ServiceModule)
from ..services import audit, events, service_import
from ..services.inventory import alive, soft_delete
from ..services.links import KIND_LABELS, is_safe_url, links_for, links_from_form, save_links
from ..services.settings_store import base_url
from ..services.signing import SignerInfo, require_signer
from ..timeutil import parse_local_input, utcnow

router = APIRouter()
SERVICE_FIELDS = ["name", "slug", "machine_id", "description", "url", "status", "runbook_md"]


def _refuse(request: Request, status: int, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _get(db: Session, sid: int) -> Service | None:
    s = db.get(Service, sid)
    return s if s and s.deleted_at is None else None


def _slug(db: Session, name: str, exclude: int | None = None) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:100] or "servizio"
    slug, n = base, 1
    while True:
        q = db.query(Service).filter(Service.slug == slug)
        if exclude:
            q = q.filter(Service.id != exclude)
        if not q.first():
            return slug
        n += 1
        slug = f"{base}-{n}"


def _int(v) -> int | None:
    return int(v) if str(v or "").isdigit() else None


def _app_name(request: Request) -> str:
    return request.app.state.settings.app_name


def emit_status(request: Request, db: Session, service: Service, old: str, signer, note: str, notify: bool):
    events.emit(db, "service.status_changed", {
        "title": service.name, "description": note or None, "url_path": f"/services/{service.id}",
        "fields": [["Prima", SERVICE_STATUSES.get(old, old)], ["Ora", SERVICE_STATUSES.get(service.status)]],
        "status_label": SERVICE_STATUSES.get(service.status), "operator": signer.operator_name,
        "resolved": service.status == "operational",
    }, base_url=base_url(request, db), service_ids=[service.id], notify=notify, app_name=_app_name(request))


@router.get("/services")
def services_list(request: Request, db: Session = Depends(get_db)):
    services = alive(db.query(Service), Service).order_by(Service.name).all()
    return render(request, "services_list.html", {"services": services, "SERVICE_STATUSES": SERVICE_STATUSES,
                                                  "MODULE_KINDS": MODULE_KINDS})


def _form_ctx(db: Session, s: Service | None) -> dict:
    return {"s": s, "machines": alive(db.query(Machine), Machine).order_by(Machine.name).all(),
            "SERVICE_STATUSES": SERVICE_STATUSES}


@router.get("/services/new")
def service_new(request: Request, db: Session = Depends(get_db)):
    return render(request, "service_form.html", _form_ctx(db, None))


@router.get("/services/import")
def services_import_page(request: Request):
    return render(request, "services_import.html", {"MODULE_KINDS": MODULE_KINDS,
                                                    "SERVICE_STATUSES": SERVICE_STATUSES})


@router.post("/services/import")
async def services_import(request: Request, db: Session = Depends(get_db),
                          signer: SignerInfo = Depends(require_signer(critical=True))):
    form = await request.form()
    upload = form.get("file")
    raw = await upload.read() if getattr(upload, "filename", "") else (form.get("json") or "")
    try:
        data = service_import.parse(raw)
        report = service_import.apply(db, data, signer, _slug)
    except service_import.ServiceImportError as exc:
        db.rollback()
        return _refuse(request, 422, str(exc), "/services/import")
    db.commit()
    parts = [f"{len(report.created)} servizi creati"]
    if report.linked:
        parts.append(f"{len(report.linked)} già presenti collegati a {report.machine.name}")
    if report.skipped:
        parts.append(f"{len(report.skipped)} già presenti lasciati com'erano")
    if report.machine_created:
        parts.append(f"macchina \"{report.machine.name}\" creata ({report.machine.asset_tag})")
    message = "Import completato: " + ", ".join(parts) + "."
    if is_fetch(request):
        return JSONResponse({"ok": True, "message": message, "created": report.created, "linked": report.linked,
                             "skipped": report.skipped, "warnings": report.warnings})
    flash(request, message)
    for w in report.warnings[:5]:  # il cookie di sessione ha spazio limitato
        flash(request, w[:200], "error")
    return redirect(request, "/services")


@router.get("/services/{sid}/edit")
def service_edit(sid: int, request: Request, db: Session = Depends(get_db)):
    s = _get(db, sid)
    if not s:
        flash(request, "Servizio non trovato.", "error")
        return redirect(request, "/services")
    return render(request, "service_form.html", _form_ctx(db, s))


async def _save_service(request: Request, db: Session, s: Service | None, signer):
    form = await request.form()
    back = f"/services/{s.id}/edit" if s else "/services/new"
    name = " ".join((form.get("name") or "").split())[:160]
    url = (form.get("url") or "").strip()
    status = form.get("status") if form.get("status") in SERVICE_STATUSES else "operational"
    if not name:
        return _refuse(request, 422, "Il nome del servizio è obbligatorio.", back)
    if url and not is_safe_url(url):
        return _refuse(request, 422, "L'indirizzo deve iniziare con http:// o https://", back)
    created = s is None
    before = None if created else audit.snapshot(s, SERVICE_FIELDS)
    old_status = s.status if s else status
    if created:
        s = Service(slug=_slug(db, name))
        db.add(s)
    s.name, s.url, s.status = name, url, status
    s.machine_id = _int(form.get("machine_id"))
    s.description = (form.get("description") or "").strip()
    s.runbook_md = (form.get("runbook_md") or "").strip()
    db.flush()
    if created:
        audit.record(db, entity_type="service", entity_id=s.id, action="create",
                     after=audit.snapshot(s, SERVICE_FIELDS), signer=signer)
    else:
        b, a = audit.changed(before, audit.snapshot(s, SERVICE_FIELDS))
        if a or b:
            audit.record(db, entity_type="service", entity_id=s.id, action="update", before=b, after=a, signer=signer)
        if old_status != status:
            emit_status(request, db, s, old_status, signer, "", form.get("notify") == "1")
    db.commit()
    flash(request, f"Servizio \"{s.name}\" salvato.")
    return redirect(request, f"/services/{s.id}")


@router.post("/services/new")
async def service_create(request: Request, db: Session = Depends(get_db),
                         signer: SignerInfo = Depends(require_signer())):
    return await _save_service(request, db, None, signer)


@router.post("/services/{sid}/edit")
async def service_update(sid: int, request: Request, db: Session = Depends(get_db),
                         signer: SignerInfo = Depends(require_signer())):
    s = _get(db, sid)
    if not s:
        return _refuse(request, 404, "Servizio non trovato.", "/services")
    return await _save_service(request, db, s, signer)


@router.post("/services/{sid}/delete")
def service_delete(sid: int, request: Request, db: Session = Depends(get_db),
                   signer: SignerInfo = Depends(require_signer(critical=True))):
    s = _get(db, sid)
    if s:
        soft_delete(db, s, signer)
        db.commit()
        flash(request, f"Servizio \"{s.name}\" nel cestino.")
    return redirect(request, "/services")


@router.get("/services/{sid}")
def service_detail(sid: int, request: Request, db: Session = Depends(get_db)):
    s = _get(db, sid)
    if not s:
        flash(request, "Servizio non trovato.", "error")
        return redirect(request, "/services")
    changes = db.query(Change).filter_by(service_id=s.id).order_by(Change.occurred_at.desc()).limit(50).all()
    incidents = (db.query(Incident).filter(Incident.services.any(Service.id == s.id))
                 .order_by(Incident.started_at.desc()).limit(10).all())
    return render(request, "service_detail.html", {
        "s": s, "changes": changes, "links": links_for(db, "change", [c.id for c in changes]),
        "incidents": incidents, "SERVICE_STATUSES": SERVICE_STATUSES, "MODULE_KINDS": MODULE_KINDS,
        "CHANGE_TYPES": CHANGE_TYPES, "KIND_LABELS": KIND_LABELS, "SEVERITIES": SEVERITIES,
        "INCIDENT_STATUSES": INCIDENT_STATUSES,
        "notify_change": events.default_notify(db, "change.published", service_ids=[s.id]),
        "notify_status": events.default_notify(db, "service.status_changed", service_ids=[s.id]),
        "attachments": db.query(Attachment).filter_by(entity_type="service", entity_id=s.id, deleted_at=None).all(),
    })


@router.post("/services/{sid}/status")
async def service_status(sid: int, request: Request, db: Session = Depends(get_db),
                         signer: SignerInfo = Depends(require_signer())):
    s = _get(db, sid)
    form = await request.form()
    status = form.get("status")
    if not s or status not in SERVICE_STATUSES:
        return _refuse(request, 422, "Stato non valido.", f"/services/{sid}")
    old = s.status
    if old != status:
        s.status = status
        audit.record(db, entity_type="service", entity_id=s.id, action="status",
                     before={"status": old}, after={"status": status, "note": form.get("note") or ""}, signer=signer)
        emit_status(request, db, s, old, signer, (form.get("note") or "").strip(), form.get("notify") == "1")
        db.commit()
        flash(request, f"Stato di \"{s.name}\": {SERVICE_STATUSES[status]}.")
    return redirect(request, f"/services/{sid}")


@router.post("/services/{sid}/modules")
async def module_create(sid: int, request: Request, db: Session = Depends(get_db),
                        signer: SignerInfo = Depends(require_signer())):
    s = _get(db, sid)
    form = await request.form()
    back = f"/services/{sid}"
    name = " ".join((form.get("name") or "").split())[:160]
    repo = (form.get("repo_url") or "").strip()
    if not s or not name:
        return _refuse(request, 422, "Nome del modulo obbligatorio.", back)
    if repo and not is_safe_url(repo):
        return _refuse(request, 422, "URL del repository non valido.", back)
    kind = form.get("kind") if form.get("kind") in MODULE_KINDS else "altro"
    m = ServiceModule(service_id=s.id, name=name, kind=kind, current_version=(form.get("current_version") or "").strip()[:60],
                      repo_url=repo, notes=(form.get("notes") or "").strip())
    db.add(m)
    db.flush()
    audit.record(db, entity_type="service_module", entity_id=m.id, action="create",
                 after={"service": s.id, "name": name, "kind": kind, "version": m.current_version}, signer=signer)
    db.commit()
    flash(request, f"Modulo \"{name}\" aggiunto.")
    return redirect(request, back)


@router.post("/services/modules/{mid}/edit")
async def module_update(mid: int, request: Request, db: Session = Depends(get_db),
                        signer: SignerInfo = Depends(require_signer())):
    m = db.get(ServiceModule, mid)
    if not m:
        return _refuse(request, 404, "Modulo non trovato.", "/services")
    form = await request.form()
    repo = (form.get("repo_url") or "").strip()
    if repo and not is_safe_url(repo):
        return _refuse(request, 422, "URL del repository non valido.", f"/services/{m.service_id}")
    fields = ["name", "kind", "current_version", "repo_url", "notes"]
    before = audit.snapshot(m, fields)
    m.name = " ".join((form.get("name") or "").split())[:160] or m.name
    m.kind = form.get("kind") if form.get("kind") in MODULE_KINDS else m.kind
    m.current_version = (form.get("current_version") or "").strip()[:60]
    m.repo_url, m.notes = repo, (form.get("notes") or "").strip()
    b, a = audit.changed(before, audit.snapshot(m, fields))
    if a or b:
        audit.record(db, entity_type="service_module", entity_id=m.id, action="update", before=b, after=a, signer=signer)
    db.commit()
    flash(request, "Modulo aggiornato.")
    return redirect(request, f"/services/{m.service_id}")


@router.post("/services/{sid}/changes")
async def change_create(sid: int, request: Request, db: Session = Depends(get_db),
                        signer: SignerInfo = Depends(require_signer())):
    s = _get(db, sid)
    back = f"/services/{sid}"
    if not s:
        return _refuse(request, 404, "Servizio non trovato.", "/services")
    form = await request.form()
    title = " ".join((form.get("title") or "").split())[:200]
    if not title:
        return _refuse(request, 422, "Scrivi un titolo per la voce di changelog.", back)
    pairs, error = links_from_form(form)
    if error:
        return _refuse(request, 422, error, back)
    module = db.get(ServiceModule, _int(form.get("module_id"))) if _int(form.get("module_id")) else None
    if module and module.service_id != s.id:
        module = None
    ctype = form.get("type") if form.get("type") in CHANGE_TYPES else "note"
    version = (form.get("version") or "").strip()[:60]
    try:
        when = parse_local_input(form.get("occurred_at") or "") or utcnow()
    except ValueError:
        return _refuse(request, 422, "Data non valida.", back)
    ch = Change(service_id=s.id, module_id=module.id if module else None, type=ctype, version=version, title=title,
                body_md=(form.get("body_md") or "").strip(), occurred_at=when, operator_id=signer.operator_id,
                signature_id=signer.signature_id)
    db.add(ch)
    db.flush()
    save_links(db, "change", ch.id, pairs)
    if module and version and form.get("update_version") == "1" and module.current_version != version:
        audit.record(db, entity_type="service_module", entity_id=module.id, action="update",
                     before={"current_version": module.current_version}, after={"current_version": version},
                     signer=signer)
        module.current_version = version
    audit.record(db, entity_type="change", entity_id=ch.id, action="create",
                 after={"service": s.id, "module": ch.module_id, "type": ctype, "version": version, "title": title,
                        "links": [u for u, _ in pairs]}, signer=signer)
    fields = [["Servizio", s.name], ["Tipo", CHANGE_TYPES[ctype]]]
    if module:
        fields.append(["Modulo", module.name])
    if version:
        fields.append(["Versione", version])
    fields += [[t or "Link", u] for u, t in pairs[:5]]
    events.emit(db, "change.published", {
        "title": title, "description": ch.body_md[:1500] or None, "url_path": f"/services/{s.id}",
        "fields": fields, "operator": signer.operator_name,
    }, base_url=base_url(request, db), service_ids=[s.id], notify=form.get("notify") == "1",
        app_name=_app_name(request))
    db.commit()
    flash(request, f"Changelog \"{title}\" registrato.")
    return redirect(request, back)


@router.get("/changes")
def changes_list(request: Request, service: str = "", type: str = "", db: Session = Depends(get_db)):
    q = db.query(Change).join(Service).filter(Service.deleted_at.is_(None))
    if service.isdigit():
        q = q.filter(Change.service_id == int(service))
    if type in CHANGE_TYPES:
        q = q.filter(Change.type == type)
    changes = q.order_by(Change.occurred_at.desc()).limit(200).all()
    services = alive(db.query(Service), Service).order_by(Service.name).all()
    return render(request, "changes_list.html", {
        "changes": changes, "links": links_for(db, "change", [c.id for c in changes]), "services": services,
        "CHANGE_TYPES": CHANGE_TYPES, "KIND_LABELS": KIND_LABELS, "filters": {"service": service, "type": type},
    })
