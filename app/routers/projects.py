"""Progetti / build PC: prenotazione componenti, completamento (montaggio + consumo scorte), annullamento."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import (PROJECT_STATUSES, STATUS_IN_USE, STATUS_RESERVED, STATUSES, Component, Machine, Project,
                      ProjectItem)
from ..services import audit
from ..services.inventory import (ACTIVE_PROJECT_STATUSES, add_movement, adjust_quantity, alive, available_quantity,
                                  machine_name)
from ..services.settings_store import base_url
from ..services.signing import SignerInfo, require_signer

router = APIRouter()


def _refuse(request: Request, status: int, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _get(db: Session, pid: int) -> Project | None:
    p = db.get(Project, pid)
    return p if p and p.deleted_at is None else None


def _mid(value: str) -> int | None:
    return int(value) if str(value).isdigit() else None


@router.get("/projects")
def projects_list(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).filter(Project.deleted_at.is_(None)).order_by(Project.id.desc()).all()
    machines = alive(db.query(Machine), Machine).order_by(Machine.name).all()
    return render(request, "projects_list.html", {"projects": projects, "machines": machines,
                                                  "STATUSES": PROJECT_STATUSES})


@router.post("/projects/new")
def project_create(request: Request, name: str = Form(""), description: str = Form(""),
                   target_machine_id: str = Form(""), db: Session = Depends(get_db),
                   signer: SignerInfo = Depends(require_signer())):
    name = " ".join(name.split())[:160]
    if not name:
        return _refuse(request, 422, "Dai un nome al progetto.", "/projects")
    p = Project(name=name, description=description.strip(), status="draft", target_machine_id=_mid(target_machine_id))
    db.add(p)
    db.flush()
    audit.record(db, entity_type="project", entity_id=p.id, action="create",
                 after={"name": p.name, "target_machine_id": p.target_machine_id}, signer=signer)
    db.commit()
    return redirect(request, f"/projects/{p.id}")


@router.get("/projects/{pid}")
def project_detail(pid: int, request: Request, db: Session = Depends(get_db)):
    p = _get(db, pid)
    if not p:
        flash(request, "Progetto non trovato.", "error")
        return redirect(request, "/projects")
    in_project = {i.component_id for i in p.items}
    candidates = [
        c for c in alive(db.query(Component), Component).order_by(Component.name)
        if c.id not in in_project and (
            (c.tracking == "quantity" and available_quantity(db, c) > 0)
            or (c.tracking != "quantity" and c.status != STATUS_RESERVED and not c.machine_id)
        )
    ]
    machines = alive(db.query(Machine), Machine).order_by(Machine.name).all()
    return render(request, "project_detail.html", {"p": p, "candidates": candidates, "machines": machines,
                                                   "STATUSES": PROJECT_STATUSES, "CSTATUS": STATUSES})


@router.post("/projects/{pid}/items")
def project_add_item(pid: int, request: Request, component_id: str = Form(""), qty: str = Form("1"),
                     note: str = Form(""), db: Session = Depends(get_db),
                     signer: SignerInfo = Depends(require_signer())):
    p = _get(db, pid)
    back = f"/projects/{pid}"
    if not p or p.status not in ACTIVE_PROJECT_STATUSES:
        return _refuse(request, 422, "Progetto non modificabile.", back)
    comp = db.get(Component, int(component_id)) if component_id.isdigit() else None
    if not comp or comp.deleted_at:
        return _refuse(request, 422, "Componente non trovato.", back)
    if any(i.component_id == comp.id for i in p.items):
        return _refuse(request, 409, "Componente già nel progetto.", back)
    if comp.tracking == "quantity":
        n = int(qty) if qty.isdigit() and int(qty) > 0 else 0
        if not n or n > available_quantity(db, comp):
            return _refuse(request, 422, f"Disponibili solo {available_quantity(db, comp)} {comp.unit or 'pz'}.", back)
        item = ProjectItem(project_id=p.id, component_id=comp.id, qty=n, note=note.strip())
    else:
        if comp.status == STATUS_RESERVED or comp.machine_id:
            return _refuse(request, 422, "Componente già riservato o montato.", back)
        item = ProjectItem(project_id=p.id, component_id=comp.id, qty=1, note=note.strip(), prev_status=comp.status)
        add_movement(db, comp, signer, "status", note=f"Riservato per: {p.name}")
        comp.status = STATUS_RESERVED
    db.add(item)
    audit.record(db, entity_type="project", entity_id=p.id, action="reserve",
                 after={"component": comp.id, "qty": item.qty}, signer=signer)
    db.commit()
    flash(request, f"\"{comp.name}\" prenotato.")
    return redirect(request, back)


def _release(db: Session, item: ProjectItem, signer, project: Project) -> None:
    comp = item.component
    if comp.tracking != "quantity" and comp.status == STATUS_RESERVED:
        comp.status = item.prev_status or "stock"
        add_movement(db, comp, signer, "status", note=f"Prenotazione annullata: {project.name}")


@router.post("/projects/{pid}/items/{item_id}/remove")
def project_remove_item(pid: int, item_id: int, request: Request, db: Session = Depends(get_db),
                        signer: SignerInfo = Depends(require_signer())):
    p = _get(db, pid)
    item = db.get(ProjectItem, item_id)
    if not p or not item or item.project_id != p.id or p.status not in ACTIVE_PROJECT_STATUSES:
        return _refuse(request, 422, "Elemento non valido.", f"/projects/{pid}")
    _release(db, item, signer, p)
    audit.record(db, entity_type="project", entity_id=p.id, action="unreserve",
                 after={"component": item.component_id}, signer=signer)
    db.delete(item)
    db.commit()
    return redirect(request, f"/projects/{pid}")


@router.post("/projects/{pid}/cancel")
def project_cancel(pid: int, request: Request, db: Session = Depends(get_db),
                   signer: SignerInfo = Depends(require_signer())):
    p = _get(db, pid)
    if not p or p.status not in ACTIVE_PROJECT_STATUSES:
        return _refuse(request, 422, "Progetto non annullabile.", f"/projects/{pid}")
    for item in p.items:
        _release(db, item, signer, p)
    p.status = "cancelled"
    audit.record(db, entity_type="project", entity_id=p.id, action="cancel", after={"status": "cancelled"},
                 signer=signer)
    db.commit()
    flash(request, "Progetto annullato, prenotazioni rilasciate.")
    return redirect(request, f"/projects/{pid}")


@router.post("/projects/{pid}/complete")
def project_complete(pid: int, request: Request, db: Session = Depends(get_db),
                     signer: SignerInfo = Depends(require_signer())):
    p = _get(db, pid)
    back = f"/projects/{pid}"
    if not p or p.status not in ACTIVE_PROJECT_STATUSES:
        return _refuse(request, 422, "Progetto non completabile.", back)
    url = base_url(request, db)
    p.status = "done"  # esce dai progetti attivi: le sue prenotazioni non riducono piu' il disponibile
    db.flush()
    try:
        for item in p.items:
            comp = item.component
            if comp.tracking == "quantity":
                adjust_quantity(db, comp, -item.qty, f"Build {p.name}", signer, url, notify=False,
                                app_name=request.app.state.settings.app_name)
            else:
                old = comp.machine_id
                comp.machine_id = p.target_machine_id
                comp.status = STATUS_IN_USE if p.target_machine_id else (item.prev_status or "stock")
                add_movement(db, comp, signer, "moved", note=f"Build {p.name}",
                             from_machine=machine_name(db, old), to_machine=machine_name(db, comp.machine_id))
    except ValueError as exc:
        db.rollback()
        return _refuse(request, 422, str(exc), back)
    audit.record(db, entity_type="project", entity_id=p.id, action="complete", after={"status": "done"},
                 signer=signer)
    db.commit()
    flash(request, "Build completata: componenti montati e scorte aggiornate.")
    return redirect(request, back)
