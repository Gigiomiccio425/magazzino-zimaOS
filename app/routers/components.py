"""CRUD componenti: scritture firmate, audit log, campi tipizzati, scorte, tag, cestino."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import STATUS_STOCK, STATUSES, TRACKING, Category, CategoryField, Component, Machine, Movement, Tag
from ..services import audit, events
from ..services.component_form import FormError, apply_component_data, parse_component_form
from ..services.component_query import build_component_query
from ..services.inventory import (
    COMPONENT_FIELDS,
    add_movement,
    adjust_quantity,
    alive,
    available_quantity,
    machine_name,
    make_tag,
    normalize_assignment,
    soft_delete,
)
from ..services.locations import location_options
from ..services.settings_store import base_url
from ..services.signing import SignerInfo, require_signer

router = APIRouter()


def _refuse(request: Request, status: int, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _ensure_category(db: Session, name: str):
    name = (name or "").strip()
    if name and not db.query(Category).filter(Category.name == name).first():
        db.add(Category(name=name))


def _fields_for(db: Session, category: str) -> list[CategoryField]:
    if not category:
        return []
    return (
        db.query(CategoryField).join(Category)
        .filter(Category.name == category, CategoryField.active.is_(True))
        .order_by(CategoryField.sort_order).all()
    )


def _all_fields(db: Session) -> dict[str, list[CategoryField]]:
    out: dict[str, list[CategoryField]] = {}
    for f in db.query(CategoryField).filter(CategoryField.active.is_(True)).order_by(CategoryField.sort_order):
        out.setdefault(f.category.name, []).append(f)
    return out


def _form_ctx(db: Session, comp: Component | None) -> dict:
    return {
        "component": comp,
        "categories": [c.name for c in db.query(Category).order_by(Category.name)],
        "machines": alive(db.query(Machine), Machine).order_by(Machine.name).all(),
        "locations": location_options(db),
        "fields_by_category": _all_fields(db),
        "TRACKING": TRACKING,
    }


def _get_alive(db: Session, comp_id: int) -> Component | None:
    comp = db.get(Component, comp_id)
    return comp if comp and comp.deleted_at is None else None


def _set_tags(db: Session, comp: Component, names: list[str]) -> None:
    tags = []
    for name in names:
        tag = db.query(Tag).filter(Tag.name == name).first()
        if not tag:
            tag = Tag(name=name)
            db.add(tag)
        tags.append(tag)
    comp.tags = tags


async def _read_form(request: Request, db: Session):
    form = await request.form()
    data = parse_component_form(form, _fields_for(db, (form.get("category") or "").strip()))
    data.machine_id, data.status = normalize_assignment(data.machine_id, data.status)
    return data


@router.get("/components")
def list_components(request: Request, db: Session = Depends(get_db)):
    params = dict(request.query_params)
    fields = _fields_for(db, params.get("category", ""))
    items = build_component_query(db, params, fields).order_by(Component.updated_at.desc()).all()
    return render(request, "components_list.html", {
        "items": items,
        "categories": [c.name for c in db.query(Category).order_by(Category.name)],
        "machines": alive(db.query(Machine), Machine).order_by(Machine.name).all(),
        "locations": location_options(db),
        "tags": [t.name for t in db.query(Tag).order_by(Tag.name)],
        "fields": [f for f in fields if f.filterable],
        "filters": params,
        "TRACKING": TRACKING,
    })


@router.get("/components/new")
def new_component(request: Request, db: Session = Depends(get_db)):
    return render(request, "component_form.html", _form_ctx(db, None))


@router.post("/components/new")
async def create_component(request: Request, db: Session = Depends(get_db),
                           signer: SignerInfo = Depends(require_signer())):
    try:
        data = await _read_form(request, db)
    except FormError as exc:
        return _refuse(request, 422, str(exc), "/components/new")
    if not data.name:
        return _refuse(request, 422, "Il nome del componente è obbligatorio.", "/components/new")
    comp = Component(created_by=signer.operator_id, updated_by=signer.operator_id, currency="EUR")
    apply_component_data(comp, data)
    comp.name = data.name
    _ensure_category(db, comp.category)
    db.add(comp)
    db.flush()
    comp.asset_tag = make_tag("C", comp.id)
    _set_tags(db, comp, data.tags)
    add_movement(db, comp, signer, "created", note="Componente creato", to_machine=machine_name(db, comp.machine_id))
    after = audit.snapshot(comp, COMPONENT_FIELDS + ["asset_tag"])
    after["tags"] = data.tags
    audit.record(db, entity_type="component", entity_id=comp.id, action="create", after=after, signer=signer)
    db.commit()
    flash(request, f"Componente \"{comp.name}\" aggiunto ({comp.asset_tag}).")
    return redirect(request, f"/components/{comp.id}")


@router.get("/components/{comp_id}")
def component_detail(comp_id: int, request: Request, db: Session = Depends(get_db)):
    comp = _get_alive(db, comp_id)
    if not comp:
        flash(request, "Componente non trovato.", "error")
        return redirect(request, "/components")
    labels = {f.key: f for f in _fields_for(db, comp.category)}
    return render(request, "component_detail.html", {
        "component": comp, "field_by_key": labels, "available": available_quantity(db, comp),
        "location_path": dict(location_options(db)).get(comp.location_id, ""),
        "notify_stock": events.default_notify(db, "stock.low"),
    })


@router.get("/components/{comp_id}/edit")
def edit_component(comp_id: int, request: Request, db: Session = Depends(get_db)):
    comp = _get_alive(db, comp_id)
    if not comp:
        flash(request, "Componente non trovato.", "error")
        return redirect(request, "/components")
    return render(request, "component_form.html", _form_ctx(db, comp))


@router.post("/components/{comp_id}/edit")
async def update_component(comp_id: int, request: Request, db: Session = Depends(get_db),
                           signer: SignerInfo = Depends(require_signer())):
    comp = _get_alive(db, comp_id)
    if not comp:
        return _refuse(request, 404, "Componente non trovato.", "/components")
    try:
        data = await _read_form(request, db)
    except FormError as exc:
        return _refuse(request, 422, str(exc), f"/components/{comp_id}/edit")
    before = audit.snapshot(comp, COMPONENT_FIELDS)
    before["tags"] = [t.name for t in comp.tags]
    old_machine, old_status = comp.machine_id, comp.status
    apply_component_data(comp, data)
    comp.updated_by = signer.operator_id
    _ensure_category(db, comp.category)
    _set_tags(db, comp, data.tags)
    if comp.machine_id != old_machine:
        add_movement(db, comp, signer, "moved", note="Spostamento",
                     from_machine=machine_name(db, old_machine), to_machine=machine_name(db, comp.machine_id))
    elif comp.status != old_status:
        add_movement(db, comp, signer, "status",
                     note=f"Stato: {STATUSES.get(old_status, old_status)} -> {STATUSES.get(comp.status, comp.status)}")
    after = audit.snapshot(comp, COMPONENT_FIELDS)
    after["tags"] = data.tags
    b, a = audit.changed(before, after)
    if a or b:
        audit.record(db, entity_type="component", entity_id=comp.id, action="update", before=b, after=a, signer=signer)
    db.commit()
    flash(request, "Componente aggiornato.")
    return redirect(request, f"/components/{comp.id}")


@router.post("/components/{comp_id}/qty")
def component_qty(comp_id: int, request: Request, delta: str = Form("0"), reason: str = Form(""),
                  notify: str = Form(""), db: Session = Depends(get_db),
                  signer: SignerInfo = Depends(require_signer())):
    comp = _get_alive(db, comp_id)
    if not comp:
        return _refuse(request, 404, "Componente non trovato.", "/components")
    try:
        amount = int(delta)
    except ValueError:
        return _refuse(request, 422, "Quantità non valida.", f"/components/{comp_id}")
    if amount == 0:
        return _refuse(request, 422, "Indica di quanto cambia la quantità.", f"/components/{comp_id}")
    try:
        adjust_quantity(db, comp, amount, reason.strip()[:200], signer, base_url(request, db), notify=notify == "1",
                        app_name=request.app.state.settings.app_name)
    except ValueError as exc:
        db.rollback()
        return _refuse(request, 422, str(exc), f"/components/{comp_id}")
    db.commit()
    flash(request, f"Quantità aggiornata: {comp.quantity} {comp.unit or 'pz'}.")
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
        supplier=src.supplier, currency=src.currency, machine_id=None,
        created_by=signer.operator_id, updated_by=signer.operator_id,
    )
    db.add(copy)
    db.flush()
    copy.asset_tag = make_tag("C", copy.id)
    copy.tags = list(src.tags)
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
