"""Ordini d'acquisto: numerazione, riordino dalle scorte minime, ricevimento merce."""
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import Component, PurchaseOrder, PurchaseOrderLine, SupplierPart
from ..timeutil import utcnow
from .inventory import add_movement, available_quantity, make_tag


def next_number(db: Session) -> str:
    year = utcnow().year
    prefix = f"ODA-{year}-"
    last = [n for (n,) in db.query(PurchaseOrder.number).filter(PurchaseOrder.number.like(prefix + "%"))]
    nums = [int(n.rsplit("-", 1)[1]) for n in last if n.rsplit("-", 1)[1].isdigit()]
    return f"{prefix}{(max(nums) + 1 if nums else 1):04d}"


@dataclass
class ReorderItem:
    component: Component
    available: int
    suggested: int
    supplier_part: SupplierPart | None


def reorder_list(db: Session) -> dict[int | None, list[ReorderItem]]:
    """Articoli a scorta sotto il minimo, raggruppati per fornitore preferito (None = senza fornitore).

    Quantità suggerita: quanto serve per tornare al doppio della scorta minima, meno quanto è già in ordine.
    """
    on_order: dict[int, int] = defaultdict(int)
    open_lines = (db.query(PurchaseOrderLine).join(PurchaseOrder)
                  .filter(PurchaseOrder.status.in_(("draft", "ordered", "partial")), PurchaseOrderLine.component_id.isnot(None)))
    for line in open_lines:
        on_order[line.component_id] += max(0, line.qty - line.qty_received)
    groups: dict[int | None, list[ReorderItem]] = defaultdict(list)
    comps = (db.query(Component).filter(Component.deleted_at.is_(None), Component.tracking == "quantity",
                                        Component.min_stock.isnot(None)).order_by(Component.name))
    for c in comps:
        avail = available_quantity(db, c)
        if avail > (c.min_stock or 0):
            continue
        need = (c.min_stock or 0) * 2 - avail - on_order[c.id]
        if need <= 0:
            continue
        parts = db.query(SupplierPart).filter_by(component_id=c.id).all()
        best = next((p for p in parts if p.preferred), parts[0] if parts else None)
        groups[best.supplier_id if best else None].append(ReorderItem(c, avail, need, best))
    return dict(groups)


def receive(db: Session, line: PurchaseOrderLine, qty: int, signer) -> list[Component]:
    """Carica a magazzino `qty` pezzi della riga. Articoli a scorta: aumenta la quantità;
    articoli con seriale: crea nuove schede uguali (una per pezzo) da completare con il seriale."""
    from . import codes

    qty = max(0, min(qty, line.qty - line.qty_received))
    if qty == 0 or line.component is None:
        line.qty_received += qty
        return []
    comp, created = line.component, []
    order = line.order
    if comp.tracking == "quantity":
        comp.quantity = (comp.quantity or 0) + qty
        add_movement(db, comp, signer, "received", note=f"Ricevuti {qty} da {order.number}", qty_delta=qty)
    else:
        for _ in range(qty):
            new = Component(name=comp.name, category=comp.category, model=comp.model, manufacturer=comp.manufacturer,
                            object_code=comp.object_code, attributes=dict(comp.attributes or {}), tracking="serial",
                            quantity=1, unit=comp.unit, status="to_test",
                            location_id=comp.location_id, supplier=order.supplier.name if order.supplier else "",
                            purchase_price=line.unit_price, purchase_date=utcnow().date(), invoice_ref=order.number,
                            created_by=signer.operator_id, updated_by=signer.operator_id, currency="EUR")
            db.add(new)
            db.flush()
            new.asset_tag = make_tag("C", new.id)
            codes.assign_codes(db, new)
            add_movement(db, new, signer, "created", note=f"Ricevuto da {order.number}")
            created.append(new)
    line.qty_received += qty
    return created


def refresh_status(order: PurchaseOrder) -> None:
    if order.status in ("draft", "cancelled"):
        return
    got = sum(line.qty_received for line in order.lines)
    want = sum(line.qty for line in order.lines)
    if want and got >= want:
        order.status, order.received_at = "received", utcnow()
    elif got:
        order.status = "partial"
