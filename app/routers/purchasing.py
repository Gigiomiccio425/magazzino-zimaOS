"""Fornitori, ordini d'acquisto e riordino dalle scorte minime. Ogni modifica è firmata."""
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import ORDER_STATUSES, Component, PurchaseOrder, PurchaseOrderLine, Supplier, SupplierPart
from ..services import audit, events, purchasing
from ..services.component_form import parse_price
from ..services.links import is_safe_url
from ..services.settings_store import base_url
from ..services.signing import SignerInfo, require_signer
from ..timeutil import utcnow

router = APIRouter()


def _refuse(request: Request, status: int, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _text(form, key: str, limit: int = 300) -> str:
    return " ".join(str(form.get(key) or "").split())[:limit]


def _alive_suppliers(db: Session):
    return db.query(Supplier).filter(Supplier.deleted_at.is_(None)).order_by(Supplier.name)


def _int(value, default=None):
    return int(value) if str(value or "").strip().isdigit() else default


# ---------------------------------------------------------------- fornitori
@router.get("/suppliers")
def suppliers_list(request: Request, db: Session = Depends(get_db)):
    sups = _alive_suppliers(db).all()
    parts = {s.id: db.query(SupplierPart).filter_by(supplier_id=s.id).count() for s in sups}
    return render(request, "suppliers_list.html", {"suppliers": sups, "parts": parts})


@router.post("/suppliers/new")
async def supplier_create(request: Request, db: Session = Depends(get_db),
                          signer: SignerInfo = Depends(require_signer())):
    form = await request.form()
    name = _text(form, "name", 160)
    website = _text(form, "website", 500)
    if not name:
        return _refuse(request, 422, "Il nome del fornitore è obbligatorio.", "/suppliers")
    if website and not is_safe_url(website):
        return _refuse(request, 422, "Il sito deve iniziare con http:// o https://", "/suppliers")
    if db.query(Supplier).filter(Supplier.name == name).first():
        return _refuse(request, 409, "Esiste già un fornitore con questo nome.", "/suppliers")
    s = Supplier(name=name, website=website, email=_text(form, "email", 200), phone=_text(form, "phone", 60),
                 notes=str(form.get("notes") or "").strip())
    db.add(s)
    db.flush()
    audit.record(db, entity_type="supplier", entity_id=s.id, action="create", after={"name": name}, signer=signer)
    db.commit()
    flash(request, f"Fornitore \"{name}\" aggiunto.")
    return redirect(request, "/suppliers")


@router.post("/suppliers/{sid}/parts")
async def supplier_part_save(sid: int, request: Request, db: Session = Depends(get_db),
                             signer: SignerInfo = Depends(require_signer())):
    """Collega un componente al fornitore (codice articolo, prezzo, link, preferito)."""
    form = await request.form()
    back = str(form.get("next") or "/suppliers")
    back = back if back.startswith("/") and not back.startswith("//") else "/suppliers"
    sup = db.get(Supplier, sid)
    comp = db.get(Component, _int(form.get("component_id"), 0))
    url = _text(form, "url", 500)
    if not sup or sup.deleted_at or not comp or comp.deleted_at:
        return _refuse(request, 404, "Fornitore o componente non trovato.", back)
    if url and not is_safe_url(url):
        return _refuse(request, 422, "Il link deve iniziare con http:// o https://", back)
    part = db.query(SupplierPart).filter_by(supplier_id=sid, component_id=comp.id).first() or \
        SupplierPart(supplier_id=sid, component_id=comp.id)
    part.sku, part.url = _text(form, "sku", 120), url
    part.price = parse_price(form.get("price"))
    part.preferred = form.get("preferred") == "1"
    if part.preferred:
        db.query(SupplierPart).filter(SupplierPart.component_id == comp.id, SupplierPart.supplier_id != sid) \
            .update({SupplierPart.preferred: False})
    db.add(part)
    db.flush()
    audit.record(db, entity_type="supplier_part", entity_id=part.id, action="update",
                 after={"supplier": sup.name, "component": comp.id, "sku": part.sku, "price": part.price}, signer=signer)
    db.commit()
    flash(request, f"{comp.name}: fornitore {sup.name} salvato.")
    return redirect(request, back)


# ---------------------------------------------------------------- ordini
@router.get("/orders")
def orders_list(request: Request, status: str = "", db: Session = Depends(get_db)):
    q = db.query(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    if status in ORDER_STATUSES:
        q = q.filter(PurchaseOrder.status == status)
    groups = purchasing.reorder_list(db)
    return render(request, "orders_list.html", {
        "orders": q.limit(200).all(), "ORDER_STATUSES": ORDER_STATUSES, "status": status,
        "suppliers": _alive_suppliers(db).all(), "to_reorder": sum(len(v) for v in groups.values()),
    })


@router.get("/orders/reorder")
def reorder_page(request: Request, db: Session = Depends(get_db)):
    groups = purchasing.reorder_list(db)
    sups = {s.id: s for s in db.query(Supplier)}
    return render(request, "orders_reorder.html", {"groups": groups, "sups": sups,
                                                   "suppliers": _alive_suppliers(db).all()})


def _new_order(db: Session, supplier_id: int | None, signer) -> PurchaseOrder:
    order = PurchaseOrder(number=purchasing.next_number(db), supplier_id=supplier_id, status="draft",
                          created_by=signer.operator_id)
    db.add(order)
    db.flush()
    return order


@router.post("/orders/new")
async def order_create(request: Request, db: Session = Depends(get_db),
                       signer: SignerInfo = Depends(require_signer())):
    """Nuovo ordine vuoto, oppure dal riordino: righe `component_id` + `qty_<id>`."""
    form = await request.form()
    sup_id = _int(form.get("supplier_id"))
    if sup_id and not db.get(Supplier, sup_id):
        return _refuse(request, 404, "Fornitore non trovato.", "/orders")
    order = _new_order(db, sup_id, signer)
    for cid in form.getlist("component_id"):
        comp = db.get(Component, _int(cid, 0))
        qty = _int(form.get(f"qty_{cid}"), 0)
        if comp and qty > 0:
            part = db.query(SupplierPart).filter_by(supplier_id=sup_id, component_id=comp.id).first() if sup_id else None
            db.add(PurchaseOrderLine(order_id=order.id, component_id=comp.id, description=comp.name[:200], qty=qty,
                                     unit_price=part.price if part else comp.purchase_price))
    audit.record(db, entity_type="purchase_order", entity_id=order.id, action="create",
                 after={"number": order.number, "supplier_id": sup_id}, signer=signer)
    db.commit()
    flash(request, f"Ordine {order.number} creato.")
    return redirect(request, f"/orders/{order.id}")


def _get_order(db: Session, oid: int) -> PurchaseOrder | None:
    return db.get(PurchaseOrder, oid)


@router.get("/orders/{oid}")
def order_detail(oid: int, request: Request, db: Session = Depends(get_db)):
    order = _get_order(db, oid)
    if not order:
        flash(request, "Ordine non trovato.", "error")
        return redirect(request, "/orders")
    comps = (db.query(Component).filter(Component.deleted_at.is_(None)).order_by(Component.name).limit(2000).all())
    total = sum((line.unit_price or 0) * line.qty for line in order.lines)
    return render(request, "order_detail.html", {"order": order, "ORDER_STATUSES": ORDER_STATUSES,
                                                 "components": comps, "total": total,
                                                 "suppliers": _alive_suppliers(db).all()})


@router.post("/orders/{oid}/lines")
async def order_add_line(oid: int, request: Request, db: Session = Depends(get_db),
                         signer: SignerInfo = Depends(require_signer())):
    form = await request.form()
    back = f"/orders/{oid}"
    order = _get_order(db, oid)
    if not order or order.status not in ("draft", "ordered", "partial"):
        return _refuse(request, 409, "Ordine non modificabile.", back)
    comp = db.get(Component, _int(form.get("component_id"), 0)) if form.get("component_id") else None
    desc = _text(form, "description", 200) or (comp.name if comp else "")
    qty = _int(form.get("qty"), 0)
    if not desc or qty <= 0:
        return _refuse(request, 422, "Servono descrizione (o componente) e quantità.", back)
    line = PurchaseOrderLine(order_id=order.id, component_id=comp.id if comp else None, description=desc[:200],
                             qty=qty, unit_price=parse_price(form.get("unit_price")))
    db.add(line)
    db.flush()
    audit.record(db, entity_type="purchase_order", entity_id=order.id, action="add_line",
                 after={"line": line.id, "description": desc, "qty": qty}, signer=signer)
    db.commit()
    return redirect(request, back)


@router.post("/orders/{oid}/status")
async def order_status(oid: int, request: Request, db: Session = Depends(get_db),
                       signer: SignerInfo = Depends(require_signer())):
    form = await request.form()
    back = f"/orders/{oid}"
    order = _get_order(db, oid)
    target = form.get("status")
    allowed = {"draft": {"ordered", "cancelled"}, "ordered": {"cancelled"}, "partial": {"cancelled"}}
    if not order or target not in allowed.get(order.status, set()):
        return _refuse(request, 409, "Cambio di stato non permesso.", back)
    if target == "ordered":
        if not order.lines:
            return _refuse(request, 422, "Aggiungi almeno una riga prima di ordinare.", back)
        order.ordered_at = utcnow()
        exp = str(form.get("expected_at") or "")
        try:
            order.expected_at = date.fromisoformat(exp) if exp else None
        except ValueError:
            return _refuse(request, 422, "Data di arrivo non valida.", back)
    before = order.status
    order.status = target
    audit.record(db, entity_type="purchase_order", entity_id=order.id, action="status",
                 before={"status": before}, after={"status": target}, signer=signer)
    db.commit()
    flash(request, f"Ordine {order.number}: {ORDER_STATUSES[target]}.")
    return redirect(request, back)


@router.post("/orders/{oid}/receive")
async def order_receive(oid: int, request: Request, db: Session = Depends(get_db),
                        signer: SignerInfo = Depends(require_signer())):
    """Carico merce: per ogni riga la quantità arrivata (`recv_<id>`)."""
    form = await request.form()
    back = f"/orders/{oid}"
    order = _get_order(db, oid)
    if not order or order.status not in ("ordered", "partial"):
        return _refuse(request, 409, "Si può ricevere solo un ordine già inviato.", back)
    got, created = 0, []
    for line in order.lines:
        qty = _int(form.get(f"recv_{line.id}"), 0)
        if qty > 0:
            created += purchasing.receive(db, line, qty, signer)
            got += qty
    if not got:
        return _refuse(request, 422, "Indica quanti pezzi sono arrivati.", back)
    purchasing.refresh_status(order)
    audit.record(db, entity_type="purchase_order", entity_id=order.id, action="receive",
                 after={"received": got, "new_components": [c.id for c in created], "status": order.status},
                 signer=signer)
    events.emit(db, "order.received", {
        "title": f"{order.number}: ricevuti {got} pezzi", "description": order.supplier.name if order.supplier else None,
        "url_path": f"/orders/{order.id}", "fields": [], "status_label": ORDER_STATUSES[order.status],
        "operator": signer.operator_name, "resolved": order.status == "received",
    }, base_url=base_url(request, db), notify=form.get("notify") == "1", app_name=request.app.state.settings.app_name)
    db.commit()
    msg = f"Caricati {got} pezzi."
    if created:
        msg += f" Create {len(created)} schede nuove da testare: aggiungi i seriali."
    flash(request, msg)
    return redirect(request, back)
