"""CRUD componenti: ogni scrittura firmata, registrata in audit log, eliminazione nel cestino."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, redirect, render
from ..models import STATUS_STOCK, STATUSES, Category, Component, Machine, Movement
from ..services import audit
from ..services.inventory import (
    COMPONENT_FIELDS,
    add_movement,
    alive,
    machine_name,
    make_tag,
    normalize_assignment,
    soft_delete,
)
from ..services.signing import SignerInfo, require_signer

router = APIRouter()


def _parse_attributes(form) -> dict:
    """Coppie attr_key[]/attr_value[] -> dizionario ordinato."""
    attrs = {}
    for k, v in zip(form.getlist("attr_key"), form.getlist("attr_value")):
        k, v = (k or "").strip(), (v or "").strip()
        if k:
            attrs[k] = v
    return attrs


def _ensure_category(db: Session, name: str):
    name = (name or "").strip()
    if name and not db.query(Category).filter(Category.name == name).first():
        db.add(Category(name=name))


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _form_lists(db: Session):
    categories = [c.name for c in db.query(Category).order_by(Category.name).all()]
    machines = alive(db.query(Machine), Machine).order_by(Machine.name).all()
    return categories, machines


def _get_alive(db: Session, comp_id: int) -> Component | None:
    comp = db.get(Component, comp_id)
    return comp if comp and comp.deleted_at is None else None


def _apply_form(comp: Component, form) -> None:
    machine_id, status = normalize_assignment(_int(form.get("machine_id")), form.get("status") or STATUS_STOCK)
    comp.object_code = (form.get("object_code") or "").strip()
    comp.name = (form.get("name") or "").strip() or comp.name
    comp.category = (form.get("category") or "").strip()
    comp.model = (form.get("model") or "").strip()
    comp.manufacturer = (form.get("manufacturer") or "").strip()
    comp.serial_number = (form.get("serial_number") or "").strip()
    comp.quantity = max(_int(form.get("quantity"), 1), 0)
    comp.status = status
    comp.location = (form.get("location") or "").strip()
    comp.notes = (form.get("notes") or "").strip()
    comp.attributes = _parse_attributes(form)
    comp.machine_id = machine_id


@router.get("/components")
def list_components(request: Request, q: str = "", category: str = "", status: str = "", machine: str = "",
                    db: Session = Depends(get_db)):
    query = alive(db.query(Component), Component)
    if q:
        like = f"%{q}%"
        query = query.filter(
            Component.name.ilike(like) | Component.object_code.ilike(like) | Component.model.ilike(like)
            | Component.manufacturer.ilike(like) | Component.serial_number.ilike(like)
            | Component.asset_tag.ilike(like)
        )
    if category:
        query = query.filter(Component.category == category)
    if status:
        query = query.filter(Component.status == status)
    if machine.isdigit():
        query = query.filter(Component.machine_id == int(machine))
    categories, machines = _form_lists(db)
    return render(request, "components_list.html", {
        "items": query.order_by(Component.updated_at.desc()).all(),
        "categories": categories,
        "machines": machines,
        "filters": {"q": q, "category": category, "status": status, "machine": machine},
    })


@router.get("/components/new")
def new_component(request: Request, db: Session = Depends(get_db)):
    categories, machines = _form_lists(db)
    return render(request, "component_form.html", {"component": None, "categories": categories, "machines": machines})


@router.post("/components/new")
async def create_component(request: Request, db: Session = Depends(get_db),
                           signer: SignerInfo = Depends(require_signer())):
    form = await request.form()
    if not (form.get("name") or "").strip():
        flash(request, "Il nome del componente è obbligatorio.", "error")
        return redirect(request, "/components/new")
    comp = Component(attributes={}, created_by=signer.operator_id, updated_by=signer.operator_id)
    _apply_form(comp, form)
    _ensure_category(db, comp.category)
    db.add(comp)
    db.flush()
    comp.asset_tag = make_tag("C", comp.id)
    add_movement(db, comp, signer, "created", note="Componente creato", to_machine=machine_name(db, comp.machine_id))
    audit.record(db, entity_type="component", entity_id=comp.id, action="create",
                 after=audit.snapshot(comp, COMPONENT_FIELDS + ["asset_tag"]), signer=signer)
    db.commit()
    flash(request, f"Componente \"{comp.name}\" aggiunto ({comp.asset_tag}).")
    return redirect(request, f"/components/{comp.id}")


@router.get("/components/{comp_id}")
def component_detail(comp_id: int, request: Request, db: Session = Depends(get_db)):
    comp = _get_alive(db, comp_id)
    if not comp:
        flash(request, "Componente non trovato.", "error")
        return redirect(request, "/components")
    return render(request, "component_detail.html", {"component": comp})


@router.get("/components/{comp_id}/edit")
def edit_component(comp_id: int, request: Request, db: Session = Depends(get_db)):
    comp = _get_alive(db, comp_id)
    if not comp:
        flash(request, "Componente non trovato.", "error")
        return redirect(request, "/components")
    categories, machines = _form_lists(db)
    return render(request, "component_form.html", {"component": comp, "categories": categories, "machines": machines})


@router.post("/components/{comp_id}/edit")
async def update_component(comp_id: int, request: Request, db: Session = Depends(get_db),
                           signer: SignerInfo = Depends(require_signer())):
    comp = _get_alive(db, comp_id)
    if not comp:
        flash(request, "Componente non trovato.", "error")
        return redirect(request, "/components")
    form = await request.form()
    before = audit.snapshot(comp, COMPONENT_FIELDS)
    old_machine, old_status = comp.machine_id, comp.status
    _apply_form(comp, form)
    comp.updated_by = signer.operator_id
    _ensure_category(db, comp.category)
    if comp.machine_id != old_machine:
        add_movement(db, comp, signer, "moved", note="Spostamento",
                     from_machine=machine_name(db, old_machine), to_machine=machine_name(db, comp.machine_id))
    elif comp.status != old_status:
        add_movement(db, comp, signer, "status",
                     note=f"Stato: {STATUSES.get(old_status, old_status)} -> {STATUSES.get(comp.status, comp.status)}")
    b, a = audit.changed(before, audit.snapshot(comp, COMPONENT_FIELDS))
    if a or b:
        audit.record(db, entity_type="component", entity_id=comp.id, action="update", before=b, after=a, signer=signer)
    db.commit()
    flash(request, "Componente aggiornato.")
    return redirect(request, f"/components/{comp.id}")


@router.post("/components/{comp_id}/delete")
def delete_component(comp_id: int, request: Request, db: Session = Depends(get_db),
                     signer: SignerInfo = Depends(require_signer(critical=True))):
    comp = _get_alive(db, comp_id)
    if comp:
        soft_delete(db, comp, signer)
        db.commit()
        flash(request, f"\"{comp.name}\" spostato nel cestino.")
    return redirect(request, "/components")


@router.post("/components/{comp_id}/duplicate")
def duplicate_component(comp_id: int, request: Request, db: Session = Depends(get_db),
                        signer: SignerInfo = Depends(require_signer())):
    src = _get_alive(db, comp_id)
    if not src:
        flash(request, "Componente non trovato.", "error")
        return redirect(request, "/components")
    # Copia i campi "noiosi" ma azzera quelli unici per unita': seriale, codice oggetto, asset tag.
    copy = Component(
        object_code="", serial_number="", name=(src.name + " (copia)")[:160], category=src.category,
        model=src.model, manufacturer=src.manufacturer, quantity=src.quantity, status=STATUS_STOCK,
        location=src.location, location_id=src.location_id, notes=src.notes,
        attributes=dict(src.attributes or {}), tracking=src.tracking, unit=src.unit, min_stock=src.min_stock,
        supplier=src.supplier, machine_id=None, created_by=signer.operator_id, updated_by=signer.operator_id,
    )
    db.add(copy)
    db.flush()
    copy.asset_tag = make_tag("C", copy.id)
    add_movement(db, copy, signer, "created", note=f"Duplicato da: {src.name}")
    audit.record(db, entity_type="component", entity_id=copy.id, action="duplicate",
                 after={"from": src.id, "asset_tag": copy.asset_tag}, signer=signer)
    db.commit()
    flash(request, "Componente duplicato. Inserisci seriale e codice oggetto.")
    return redirect(request, f"/components/{copy.id}/edit")


@router.get("/movements")
def movements(request: Request, db: Session = Depends(get_db)):
    items = db.query(Movement).order_by(Movement.timestamp.desc()).limit(200).all()
    return render(request, "movements.html", {"items": items})
