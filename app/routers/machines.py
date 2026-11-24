"""CRUD macchine/postazioni: scritture firmate, audit log, cestino."""
from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, redirect, render
from ..models import STATUS_IN_USE, STATUS_STOCK, Component, Machine
from ..services import audit
from ..services.inventory import MACHINE_FIELDS, add_movement, alive, make_tag, soft_delete
from ..services.signing import SignerInfo, require_signer

router = APIRouter()


def _get_alive(db: Session, machine_id: int) -> Machine | None:
    m = db.get(Machine, machine_id)
    return m if m and m.deleted_at is None else None


def _name_taken(db: Session, name: str, exclude_id: int | None = None) -> bool:
    q = db.query(Machine).filter(Machine.name == name)
    if exclude_id:
        q = q.filter(Machine.id != exclude_id)
    return q.first() is not None


@router.get("/machines")
def list_machines(request: Request, db: Session = Depends(get_db)):
    machines = alive(db.query(Machine), Machine).order_by(Machine.name).all()
    counts = dict(
        alive(db.query(Component.machine_id, func.count(Component.id)), Component)
        .group_by(Component.machine_id).all()
    )
    return render(request, "machines_list.html", {"machines": machines, "counts": counts})


@router.get("/machines/new")
def new_machine(request: Request):
    return render(request, "machine_form.html", {"machine": None})


@router.post("/machines/new")
def create_machine(request: Request, name: str = Form(""), kind: str = Form(""), location: str = Form(""),
                   description: str = Form(""), db: Session = Depends(get_db),
                   signer: SignerInfo = Depends(require_signer())):
    name = name.strip()
    if not name:
        flash(request, "Il nome della macchina è obbligatorio.", "error")
        return redirect(request, "/machines/new")
    if _name_taken(db, name):
        flash(request, "Esiste già una macchina con questo nome (controlla anche il cestino).", "error")
        return redirect(request, "/machines/new")
    m = Machine(name=name, kind=kind.strip(), location=location.strip(), description=description.strip())
    db.add(m)
    db.flush()
    m.asset_tag = make_tag("M", m.id)
    audit.record(db, entity_type="machine", entity_id=m.id, action="create",
                 after=audit.snapshot(m, MACHINE_FIELDS + ["asset_tag"]), signer=signer)
    db.commit()
    flash(request, f"Macchina \"{m.name}\" creata ({m.asset_tag}).")
    return redirect(request, f"/machines/{m.id}")


@router.get("/machines/{machine_id}")
def machine_detail(machine_id: int, request: Request, db: Session = Depends(get_db)):
    m = _get_alive(db, machine_id)
    if not m:
        flash(request, "Macchina non trovata.", "error")
        return redirect(request, "/machines")
    components = (
        alive(db.query(Component), Component).filter(Component.machine_id == m.id).order_by(Component.category).all()
    )
    return render(request, "machine_detail.html", {"machine": m, "components": components})


@router.get("/machines/{machine_id}/edit")
def edit_machine(machine_id: int, request: Request, db: Session = Depends(get_db)):
    m = _get_alive(db, machine_id)
    if not m:
        flash(request, "Macchina non trovata.", "error")
        return redirect(request, "/machines")
    return render(request, "machine_form.html", {"machine": m})


@router.post("/machines/{machine_id}/edit")
def update_machine(machine_id: int, request: Request, name: str = Form(""), kind: str = Form(""),
                   location: str = Form(""), description: str = Form(""), db: Session = Depends(get_db),
                   signer: SignerInfo = Depends(require_signer())):
    m = _get_alive(db, machine_id)
    if not m:
        flash(request, "Macchina non trovata.", "error")
        return redirect(request, "/machines")
    name = name.strip()
    if name and _name_taken(db, name, exclude_id=m.id):
        flash(request, "Esiste già una macchina con questo nome.", "error")
        return redirect(request, f"/machines/{m.id}/edit")
    before = audit.snapshot(m, MACHINE_FIELDS)
    m.name = name or m.name
    m.kind = kind.strip()
    m.location = location.strip()
    m.description = description.strip()
    b, a = audit.changed(before, audit.snapshot(m, MACHINE_FIELDS))
    if a or b:
        audit.record(db, entity_type="machine", entity_id=m.id, action="update", before=b, after=a, signer=signer)
    db.commit()
    flash(request, "Macchina aggiornata.")
    return redirect(request, f"/machines/{m.id}")


@router.post("/machines/{machine_id}/delete")
def delete_machine(machine_id: int, request: Request, db: Session = Depends(get_db),
                   signer: SignerInfo = Depends(require_signer(critical=True))):
    m = _get_alive(db, machine_id)
    if m:
        for comp in alive(db.query(Component), Component).filter(Component.machine_id == m.id).all():
            comp.machine_id = None
            if comp.status == STATUS_IN_USE:
                comp.status = STATUS_STOCK
            add_movement(db, comp, signer, "moved", note="Macchina eliminata", from_machine=m.name)
        soft_delete(db, m, signer)
        db.commit()
        flash(request, f"Macchina \"{m.name}\" nel cestino. Componenti riportati a magazzino.")
    return redirect(request, "/machines")
