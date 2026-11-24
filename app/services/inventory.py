"""Regole di dominio dell'inventario: asset tag, coerenza stato/macchina, cestino, movimenti."""
from sqlalchemy.orm import Query, Session

from ..models import STATUS_IN_USE, STATUS_STOCK, Component, Location, Machine, Movement
from ..timeutil import utcnow
from . import audit

TAG_FORMATS = {"C": "C-{:06d}", "M": "M-{:03d}", "L": "L-{:04d}"}

COMPONENT_FIELDS = [
    "name", "object_code", "category", "model", "manufacturer", "serial_number", "quantity", "status",
    "location", "notes", "attributes", "machine_id", "location_id", "tracking", "unit", "min_stock",
    "supplier", "purchase_date", "purchase_price", "currency", "warranty_until", "invoice_ref",
]
MACHINE_FIELDS = ["name", "kind", "location", "description", "location_id", "hostname", "ip_address", "os"]


def make_tag(prefix: str, id: int) -> str:
    return TAG_FORMATS[prefix].format(id)


def normalize_assignment(machine_id: int | None, status: str) -> tuple[int | None, str]:
    """Regole v1.1.1: macchina + 'a magazzino' -> 'in uso'; nessuna macchina + 'in uso' -> 'a magazzino'."""
    if machine_id and status == STATUS_STOCK:
        status = STATUS_IN_USE
    if not machine_id and status == STATUS_IN_USE:
        status = STATUS_STOCK
    return machine_id, status


def alive(query: Query, model) -> Query:
    return query.filter(model.deleted_at.is_(None))


def entity_name(obj) -> str:
    return {Component: "component", Machine: "machine", Location: "location"}.get(type(obj), type(obj).__name__.lower())


def machine_name(db: Session, machine_id: int | None) -> str:
    if not machine_id:
        return ""
    m = db.get(Machine, machine_id)
    return m.name if m else ""


def add_movement(db: Session, comp: Component, signer, action: str, note: str = "",
                 from_machine: str = "", to_machine: str = "", qty_delta: int | None = None,
                 reason: str = "") -> Movement:
    mv = Movement(
        component_id=comp.id, action=action, note=note, from_machine=from_machine, to_machine=to_machine,
        qty_delta=qty_delta, reason=reason,
        operator_id=getattr(signer, "operator_id", None), signature_id=getattr(signer, "signature_id", None),
    )
    db.add(mv)
    return mv


def soft_delete(db: Session, obj, signer) -> None:
    obj.deleted_at = utcnow()
    audit.record(db, entity_type=entity_name(obj), entity_id=obj.id, action="delete",
                 before={"deleted_at": None}, after={"deleted_at": obj.deleted_at}, signer=signer)


def restore(db: Session, obj, signer) -> None:
    before = obj.deleted_at
    obj.deleted_at = None
    audit.record(db, entity_type=entity_name(obj), entity_id=obj.id, action="restore",
                 before={"deleted_at": before}, after={"deleted_at": None}, signer=signer)


def purge(db: Session, obj, signer) -> None:
    snap = audit.snapshot(obj, ["name"])
    audit.record(db, entity_type=entity_name(obj), entity_id=obj.id, action="purge", before=snap, signer=signer)
    db.delete(obj)
