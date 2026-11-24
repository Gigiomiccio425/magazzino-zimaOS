"""Export/import CSV dei componenti (separatore ';', UTF-8 con BOM: si apre bene in Excel italiano)."""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from ..models import STATUSES, TRACKING, Component, Location, Machine, Tag
from . import audit
from .component_form import parse_price
from .inventory import COMPONENT_FIELDS, add_movement, make_tag
from .locations import SEP, location_path

COLUMNS = ["asset_tag", "object_code", "name", "category", "tracking", "model", "manufacturer", "serial_number",
           "quantity", "unit", "min_stock", "status", "location_path", "machine", "supplier", "purchase_date",
           "purchase_price", "currency", "warranty_until", "invoice_ref", "tags", "notes"]
TEXT_FIELDS = ["object_code", "name", "category", "model", "manufacturer", "serial_number", "unit", "supplier",
               "currency", "invoice_ref", "notes"]
NUMBER_RE = re.compile(r"^-?\d+([.,]\d+)?$")


@dataclass
class ImportRow:
    line: int
    action: Literal["create", "update", "unchanged", "error"]
    match: str | None
    data: dict
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportPlan:
    rows: list[ImportRow]

    def count(self, action: str) -> int:
        return sum(1 for r in self.rows if r.action == action)


@dataclass
class ImportResult:
    created: int
    updated: int


def _price(cents) -> str:
    return "" if cents is None else f"{cents / 100:.2f}".replace(".", ",")


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _safe(value: str) -> str:
    """Protezione CSV injection: Excel non deve interpretare il contenuto come formula."""
    return "'" + value if value.startswith(FORMULA_START) else value


def export_components_csv(db: Session) -> str:
    comps = db.query(Component).filter(Component.deleted_at.is_(None)).order_by(Component.id).all()
    attr_keys = sorted({k for c in comps for k in (c.attributes or {})})
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(COLUMNS + [f"attr:{k}" for k in attr_keys])
    for c in comps:
        row = {name: _cell(getattr(c, name, None)) for name in COLUMNS}
        row["location_path"] = location_path(c.place) if c.place else ""
        row["machine"] = c.machine.name if c.machine else ""
        row["purchase_price"] = _price(c.purchase_price)
        row["tags"] = ", ".join(t.name for t in c.tags)
        cells = [row[n] for n in COLUMNS] + [_cell((c.attributes or {}).get(k)) for k in attr_keys]
        w.writerow([_safe(v) for v in cells])
    return "﻿" + buf.getvalue()


def _read(text: str) -> tuple[list[str], list[dict]]:
    text = text.lstrip("﻿")
    first = text.splitlines()[0] if text.strip() else ""
    delimiter = ";" if ";" in first or "," not in first else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [h.strip() for h in (reader.fieldnames or [])], list(reader)


FORMULA_START = ("=", "+", "-", "@")


def _attr_value(raw: str) -> str:
    """Gli attributi importati restano testo (niente "007" -> 7)."""
    return raw.strip()


def _unescape(value: str) -> str:
    """Toglie l'apostrofo aggiunto dall'export davanti alle celle che Excel leggerebbe come formula."""
    if value.startswith("'") and value[1:2] in FORMULA_START:
        return value[1:]
    return value


def _parse_row(raw: dict, headers: list[str]) -> tuple[dict, list[str]]:
    data, errors = {}, []
    get = lambda k: _unescape((raw.get(k) or "").strip())  # noqa: E731
    for k in TEXT_FIELDS:
        if k in headers:
            data[k] = get(k)
    if "status" in headers and get("status"):
        if get("status") not in STATUSES:
            errors.append(f"Stato sconosciuto: {get('status')}")
        data["status"] = get("status")
    if "tracking" in headers and get("tracking"):
        if get("tracking") not in TRACKING:
            errors.append(f"Tipo articolo sconosciuto: {get('tracking')}")
        data["tracking"] = get("tracking")
    for k in ("quantity", "min_stock"):
        if k in headers:
            if get(k) and not get(k).lstrip("-").isdigit():
                errors.append(f"{k}: numero intero atteso")
            else:
                data[k] = int(get(k)) if get(k) else (1 if k == "quantity" else None)
    for k in ("purchase_date", "warranty_until"):
        if k in headers:
            try:
                data[k] = date.fromisoformat(get(k)) if get(k) else None
            except ValueError:
                errors.append(f"{k}: data AAAA-MM-GG attesa")
    if "purchase_price" in headers:
        try:
            data["purchase_price"] = parse_price(get("purchase_price"))
        except ValueError:
            errors.append("Prezzo non valido")
    if "location_path" in headers:
        data["location_path"] = get("location_path")
    if "machine" in headers:
        data["machine"] = get("machine")
    if "tags" in headers:
        data["tags"] = sorted({t.strip().lower() for t in get("tags").split(",") if t.strip()})
    attrs = {h[5:]: _attr_value(get(h)) for h in headers if h.startswith("attr:") and get(h)}
    if attrs:
        data["attributes"] = attrs
    return data, errors


def _current(c: Component) -> dict:
    return {
        **{k: getattr(c, k) or "" for k in TEXT_FIELDS},
        "status": c.status, "tracking": c.tracking, "quantity": c.quantity, "min_stock": c.min_stock,
        "purchase_date": c.purchase_date, "warranty_until": c.warranty_until, "purchase_price": c.purchase_price,
        "location_path": location_path(c.place) if c.place else "", "machine": c.machine.name if c.machine else "",
        "tags": sorted(t.name for t in c.tags), "attributes": c.attributes or {},
    }


def _differs(comp: Component, data: dict) -> bool:
    cur = _current(comp)
    for k, v in data.items():
        if k == "attributes":
            merged = {**cur["attributes"], **v}
            if {a: _cell(b) for a, b in merged.items()} != {a: _cell(b) for a, b in cur["attributes"].items()}:
                return True
        elif _cell(cur.get(k)) != _cell(v):
            return True
    return False


def _find(db: Session, raw: dict) -> tuple[Component | None, str | None]:
    alive = db.query(Component).filter(Component.deleted_at.is_(None))
    tag = _unescape((raw.get("asset_tag") or "").strip()).upper()
    if tag:
        comp = alive.filter(Component.asset_tag == tag).first()
        if comp:
            return comp, tag
    serial = _unescape((raw.get("serial_number") or "").strip())
    if serial:
        hits = alive.filter(Component.serial_number == serial).limit(2).all()
        if len(hits) == 1:
            return hits[0], f"S/N {serial}"
    return None, None


def plan_import(db: Session, text: str) -> ImportPlan:
    headers, rows = _read(text)
    plan = []
    for i, raw in enumerate(rows, start=2):
        data, errors = _parse_row(raw, headers)
        comp, match = _find(db, raw)
        if comp is None and not data.get("name"):
            errors.append("Nome obbligatorio per i nuovi componenti")
        if comp is not None and "name" in data and not data["name"]:
            errors.append("Nome vuoto")
        if data.get("machine") and not db.query(Machine).filter(
                Machine.name == data["machine"], Machine.deleted_at.is_(None)).first():
            errors.append(f"Macchina sconosciuta: {data['machine']}")
        if errors:
            action = "error"
        elif comp is None:
            action = "create"
        else:
            action = "update" if _differs(comp, data) else "unchanged"
        plan.append(ImportRow(i, action, match, data, errors))
    return ImportPlan(plan)


def _location_by_path(db: Session, path: str) -> int | None:
    parent = None
    for name in [p.strip() for p in path.split(SEP.strip()) if p.strip()]:
        q = db.query(Location).filter(Location.name == name, Location.deleted_at.is_(None))
        q = q.filter(Location.parent_id.is_(None) if parent is None else Location.parent_id == parent)
        loc = q.first()
        if not loc:
            loc = Location(name=name[:120], kind="altro", parent_id=parent)
            db.add(loc)
            db.flush()
            loc.asset_tag = make_tag("L", loc.id)
        parent = loc.id
    return parent


def apply_import(db: Session, plan: ImportPlan, signer) -> ImportResult:
    created = updated = 0
    for row in plan.rows:
        if row.action not in ("create", "update"):
            continue
        data = dict(row.data)
        comp = _find(db, {"asset_tag": (row.match or "") if row.match and not row.match.startswith("S/N") else "",
                          "serial_number": row.match[4:] if row.match and row.match.startswith("S/N") else ""})[0]
        before = audit.snapshot(comp, COMPONENT_FIELDS) if comp else None
        if comp is None:
            comp = Component(name=data["name"], attributes={}, created_by=signer.operator_id, currency="EUR")
            db.add(comp)
            db.flush()
            comp.asset_tag = make_tag("C", comp.id)
        if "location_path" in data:
            path = data.pop("location_path")
            comp.location_id = _location_by_path(db, path) if path else None
        if "machine" in data:
            name = data.pop("machine")
            m = db.query(Machine).filter(Machine.name == name, Machine.deleted_at.is_(None)).first() if name else None
            comp.machine_id = m.id if m else None
        if "tags" in data:
            names = data.pop("tags")
            tags = []
            for n in names:
                t = db.query(Tag).filter_by(name=n).first() or Tag(name=n)
                db.add(t)
                tags.append(t)
            comp.tags = tags
        if "attributes" in data:
            comp.attributes = {**(comp.attributes or {}), **data.pop("attributes")}
        for k, v in data.items():
            setattr(comp, k, v)
        comp.updated_by = signer.operator_id
        if before is None:
            created += 1
            add_movement(db, comp, signer, "created", note="Importato da CSV")
            audit.record(db, entity_type="component", entity_id=comp.id, action="import_create",
                         after=audit.snapshot(comp, COMPONENT_FIELDS + ["asset_tag"]), signer=signer)
        else:
            updated += 1
            b, a = audit.changed(before, audit.snapshot(comp, COMPONENT_FIELDS))
            audit.record(db, entity_type="component", entity_id=comp.id, action="import_update", before=b, after=a,
                         signer=signer)
    db.flush()
    return ImportResult(created, updated)
