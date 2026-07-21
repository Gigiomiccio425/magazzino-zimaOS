"""CRUD componenti + logica spostamenti/movimenti."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, render
from ..models import (
    STATUS_IN_USE,
    STATUS_STOCK,
    STATUSES,
    Category,
    Component,
    Machine,
    Movement,
)

router = APIRouter()


def _parse_attributes(form) -> dict:
    """Trasforma coppie attr_key[]/attr_value[] in un dizionario ordinato."""
    keys = form.getlist("attr_key")
    values = form.getlist("attr_value")
    attrs = {}
    for k, v in zip(keys, values):
        k = (k or "").strip()
        v = (v or "").strip()
        if k:
            attrs[k] = v
    return attrs


def _ensure_category(db: Session, name: str):
    name = (name or "").strip()
    if not name:
        return
    exists = db.query(Category).filter(Category.name == name).first()
    if not exists:
        db.add(Category(name=name))


def _machine_name(db: Session, machine_id):
    if not machine_id:
        return ""
    m = db.query(Machine).get(machine_id)
    return m.name if m else ""


@router.get("/components")
def list_components(
    request: Request,
    q: str = "",
    category: str = "",
    status: str = "",
    machine: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(Component)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Component.name.ilike(like))
            | (Component.object_code.ilike(like))
            | (Component.model.ilike(like))
            | (Component.manufacturer.ilike(like))
            | (Component.serial_number.ilike(like))
        )
    if category:
        query = query.filter(Component.category == category)
    if status:
        query = query.filter(Component.status == status)
    if machine:
        query = query.filter(Component.machine_id == int(machine))

    items = query.order_by(Component.updated_at.desc()).all()
    categories = [c.name for c in db.query(Category).order_by(Category.name).all()]
    machines = db.query(Machine).order_by(Machine.name).all()

    return render(request, "components_list.html", {
        "items": items,
        "categories": categories,
        "machines": machines,
        "filters": {"q": q, "category": category, "status": status, "machine": machine},
    })


@router.get("/components/new")
def new_component(request: Request, db: Session = Depends(get_db)):
    categories = [c.name for c in db.query(Category).order_by(Category.name).all()]
    machines = db.query(Machine).order_by(Machine.name).all()
    return render(request, "component_form.html", {
        "component": None,
        "categories": categories,
        "machines": machines,
    })


@router.post("/components/new")
async def create_component(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    machine_id = form.get("machine_id") or None
    machine_id = int(machine_id) if machine_id else None
    status = form.get("status") or STATUS_STOCK
    # Coerenza: se assegnato a macchina lo stato diventa "in uso"
    if machine_id and status == STATUS_STOCK:
        status = STATUS_IN_USE
    if not machine_id and status == STATUS_IN_USE:
        machine_id = None

    comp = Component(
        object_code=form.get("object_code", "").strip(),
        name=form.get("name", "").strip(),
        category=form.get("category", "").strip(),
        model=form.get("model", "").strip(),
        manufacturer=form.get("manufacturer", "").strip(),
        serial_number=form.get("serial_number", "").strip(),
        quantity=int(form.get("quantity") or 1),
        status=status,
        location=form.get("location", "").strip(),
        notes=form.get("notes", "").strip(),
        attributes=_parse_attributes(form),
        machine_id=machine_id,
    )
    if not comp.name:
        flash(request, "Il nome del componente e obbligatorio.", "error")
        return RedirectResponse(url="/components/new", status_code=303)

    _ensure_category(db, comp.category)
    db.add(comp)
    db.flush()

    db.add(Movement(
        component_id=comp.id,
        action="created",
        to_machine=_machine_name(db, machine_id),
        note="Componente creato",
    ))
    db.commit()
    flash(request, f"Componente \"{comp.name}\" aggiunto.")
    return RedirectResponse(url=f"/components/{comp.id}", status_code=303)


@router.get("/components/{comp_id}")
def component_detail(comp_id: int, request: Request, db: Session = Depends(get_db)):
    comp = db.query(Component).get(comp_id)
    if not comp:
        flash(request, "Componente non trovato.", "error")
        return RedirectResponse(url="/components", status_code=303)
    return render(request, "component_detail.html", {"component": comp})


@router.get("/components/{comp_id}/edit")
def edit_component(comp_id: int, request: Request, db: Session = Depends(get_db)):
    comp = db.query(Component).get(comp_id)
    if not comp:
        flash(request, "Componente non trovato.", "error")
        return RedirectResponse(url="/components", status_code=303)
    categories = [c.name for c in db.query(Category).order_by(Category.name).all()]
    machines = db.query(Machine).order_by(Machine.name).all()
    return render(request, "component_form.html", {
        "component": comp,
        "categories": categories,
        "machines": machines,
    })


@router.post("/components/{comp_id}/edit")
async def update_component(comp_id: int, request: Request, db: Session = Depends(get_db)):
    comp = db.query(Component).get(comp_id)
    if not comp:
        flash(request, "Componente non trovato.", "error")
        return RedirectResponse(url="/components", status_code=303)

    form = await request.form()
    old_machine_id = comp.machine_id
    old_status = comp.status

    machine_id = form.get("machine_id") or None
    machine_id = int(machine_id) if machine_id else None
    status = form.get("status") or STATUS_STOCK
    if machine_id and status == STATUS_STOCK:
        status = STATUS_IN_USE
    if not machine_id and status == STATUS_IN_USE:
        status = STATUS_STOCK

    comp.object_code = form.get("object_code", "").strip()
    comp.name = form.get("name", "").strip() or comp.name
    comp.category = form.get("category", "").strip()
    comp.model = form.get("model", "").strip()
    comp.manufacturer = form.get("manufacturer", "").strip()
    comp.serial_number = form.get("serial_number", "").strip()
    comp.quantity = int(form.get("quantity") or 1)
    comp.status = status
    comp.location = form.get("location", "").strip()
    comp.notes = form.get("notes", "").strip()
    comp.attributes = _parse_attributes(form)
    comp.machine_id = machine_id

    _ensure_category(db, comp.category)

    # Log movimento se cambia macchina
    if machine_id != old_machine_id:
        db.add(Movement(
            component_id=comp.id,
            action="moved",
            from_machine=_machine_name(db, old_machine_id),
            to_machine=_machine_name(db, machine_id),
            note="Spostamento",
        ))
    elif status != old_status:
        db.add(Movement(
            component_id=comp.id,
            action="status",
            note=f"Stato: {STATUSES.get(old_status, old_status)} -> {STATUSES.get(status, status)}",
        ))

    db.commit()
    flash(request, "Componente aggiornato.")
    return RedirectResponse(url=f"/components/{comp.id}", status_code=303)


@router.post("/components/{comp_id}/delete")
def delete_component(comp_id: int, request: Request, db: Session = Depends(get_db)):
    comp = db.query(Component).get(comp_id)
    if comp:
        name = comp.name
        db.delete(comp)
        db.commit()
        flash(request, f"Componente \"{name}\" eliminato.")
    return RedirectResponse(url="/components", status_code=303)


@router.post("/components/{comp_id}/duplicate")
def duplicate_component(comp_id: int, request: Request, db: Session = Depends(get_db)):
    src = db.query(Component).get(comp_id)
    if not src:
        flash(request, "Componente non trovato.", "error")
        return RedirectResponse(url="/components", status_code=303)

    # Copia i campi "noiosi" (modello, categoria, attributi...) ma azzera i
    # campi unici per unita: codice oggetto e seriale. Nuova unita a magazzino.
    copy = Component(
        object_code="",
        name=(src.name + " (copia)")[:160],
        category=src.category,
        model=src.model,
        manufacturer=src.manufacturer,
        serial_number="",
        quantity=src.quantity,
        status=STATUS_STOCK,
        location=src.location,
        notes=src.notes,
        attributes=dict(src.attributes or {}),
        machine_id=None,
    )
    db.add(copy)
    db.flush()
    db.add(Movement(
        component_id=copy.id,
        action="created",
        note=f"Duplicato da: {src.name}",
    ))
    db.commit()
    flash(request, "Componente duplicato. Inserisci seriale e codice oggetto.")
    return RedirectResponse(url=f"/components/{copy.id}/edit", status_code=303)


@router.get("/movements")
def movements(request: Request, db: Session = Depends(get_db)):
    items = db.query(Movement).order_by(Movement.timestamp.desc()).limit(200).all()
    return render(request, "movements.html", {"items": items})
