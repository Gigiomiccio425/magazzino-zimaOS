"""CRUD macchine/postazioni."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, render
from ..models import Component, Machine

router = APIRouter()


@router.get("/machines")
def list_machines(request: Request, db: Session = Depends(get_db)):
    machines = db.query(Machine).order_by(Machine.name).all()
    # Conteggio componenti per macchina
    counts = {
        m.id: db.query(Component).filter(Component.machine_id == m.id).count()
        for m in machines
    }
    return render(request, "machines_list.html", {"machines": machines, "counts": counts})


@router.get("/machines/new")
def new_machine(request: Request):
    return render(request, "machine_form.html", {"machine": None})


@router.post("/machines/new")
def create_machine(
    request: Request,
    name: str = Form(""),
    kind: str = Form(""),
    location: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        flash(request, "Il nome della macchina e obbligatorio.", "error")
        return RedirectResponse(url="/machines/new", status_code=303)
    if db.query(Machine).filter(Machine.name == name).first():
        flash(request, "Esiste gia una macchina con questo nome.", "error")
        return RedirectResponse(url="/machines/new", status_code=303)

    m = Machine(name=name, kind=kind.strip(), location=location.strip(), description=description.strip())
    db.add(m)
    db.commit()
    flash(request, f"Macchina \"{m.name}\" creata.")
    return RedirectResponse(url=f"/machines/{m.id}", status_code=303)


@router.get("/machines/{machine_id}")
def machine_detail(machine_id: int, request: Request, db: Session = Depends(get_db)):
    m = db.query(Machine).get(machine_id)
    if not m:
        flash(request, "Macchina non trovata.", "error")
        return RedirectResponse(url="/machines", status_code=303)
    components = db.query(Component).filter(Component.machine_id == m.id).order_by(Component.category).all()
    return render(request, "machine_detail.html", {"machine": m, "components": components})


@router.get("/machines/{machine_id}/edit")
def edit_machine(machine_id: int, request: Request, db: Session = Depends(get_db)):
    m = db.query(Machine).get(machine_id)
    if not m:
        flash(request, "Macchina non trovata.", "error")
        return RedirectResponse(url="/machines", status_code=303)
    return render(request, "machine_form.html", {"machine": m})


@router.post("/machines/{machine_id}/edit")
def update_machine(
    machine_id: int,
    request: Request,
    name: str = Form(""),
    kind: str = Form(""),
    location: str = Form(""),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    m = db.query(Machine).get(machine_id)
    if not m:
        flash(request, "Macchina non trovata.", "error")
        return RedirectResponse(url="/machines", status_code=303)
    m.name = name.strip() or m.name
    m.kind = kind.strip()
    m.location = location.strip()
    m.description = description.strip()
    db.commit()
    flash(request, "Macchina aggiornata.")
    return RedirectResponse(url=f"/machines/{m.id}", status_code=303)


@router.post("/machines/{machine_id}/delete")
def delete_machine(machine_id: int, request: Request, db: Session = Depends(get_db)):
    m = db.query(Machine).get(machine_id)
    if m:
        # I componenti tornano a magazzino (machine_id = NULL)
        for comp in db.query(Component).filter(Component.machine_id == m.id).all():
            comp.machine_id = None
        name = m.name
        db.delete(m)
        db.commit()
        flash(request, f"Macchina \"{name}\" eliminata. Componenti riportati a magazzino.")
    return RedirectResponse(url="/machines", status_code=303)
