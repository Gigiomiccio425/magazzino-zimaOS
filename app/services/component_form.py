"""Lettura e validazione del form componente (campi tipizzati per categoria + attributi liberi)."""
import re
from dataclasses import dataclass, field
from datetime import date

from ..models import STATUS_STOCK, STATUSES, TRACKING, CategoryField


class FormError(ValueError):
    """Valore non valido nel form (messaggio per l'utente)."""


def parse_price(text: str | None) -> int | None:
    """Prezzo in euro -> centesimi. Accetta '12,50', '1.234,56', '12.5'."""
    text = (text or "").strip().replace("€", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", text):
        raise ValueError(f"Prezzo non valido: {text}")
    euros, _, cents = text.partition(".")
    return int(euros) * 100 + int((cents + "00")[:2])


def parse_number(text: str):
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise FormError(f"\"{text}\" non è un numero") from exc
    return int(value) if value.is_integer() else value


def _int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _date(value: str | None) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise FormError(f"Data non valida: {value}") from exc


def parse_tags(text: str | None) -> list[str]:
    seen = {}
    for raw in (text or "").split(","):
        name = " ".join(raw.split()).lower()[:60]
        if name:
            seen[name] = True
    return sorted(seen)


@dataclass
class ComponentData:
    name: str
    object_code: str = ""
    category: str = ""
    model: str = ""
    manufacturer: str = ""
    serial_number: str = ""
    tracking: str = "serial"
    quantity: int = 1
    unit: str = "pz"
    min_stock: int | None = None
    status: str = STATUS_STOCK
    machine_id: int | None = None
    location_id: int | None = None
    location: str = ""
    notes: str = ""
    supplier: str = ""
    purchase_date: date | None = None
    purchase_price: int | None = None
    warranty_until: date | None = None
    invoice_ref: str = ""
    attributes: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


def typed_value(f: CategoryField, raw, legacy=None):
    """Valore tipizzato. Un valore storico v1.1.1 (testo libero, fuori dalle scelte o non numerico)
    reinviato identico viene conservato cosi' com'e'."""
    if legacy is not None and isinstance(legacy, str) and (raw or "").strip() == legacy.strip():
        return legacy
    if f.type == "number":
        return parse_number(raw)
    if f.type == "bool":
        return True if raw == "1" else None
    if f.type == "date":
        d = _date(raw)
        return d.isoformat() if d else None
    value = (raw or "").strip()
    if f.type == "choice" and value and value not in (f.choices or []):
        raise FormError(f"{f.label}: valore non previsto")
    return value or None


def parse_component_form(form, fields: list[CategoryField], current: dict | None = None) -> ComponentData:
    def s(name):
        return (form.get(name) or "").strip()

    tracking = s("tracking") if s("tracking") in TRACKING else "serial"
    quantity = max(_int(form.get("quantity"), 1), 0)
    if tracking == "serial":
        quantity = 1
    try:
        price = parse_price(form.get("purchase_price"))
    except ValueError as exc:
        raise FormError("Prezzo non valido (es. 49,90).") from exc
    attrs: dict = {}
    for k, v in zip(form.getlist("attr_key"), form.getlist("attr_value")):
        k, v = (k or "").strip(), (v or "").strip()
        if k:
            attrs[k] = v
    for f in fields:
        value = typed_value(f, form.get(f"cf_{f.id}"), (current or {}).get(f.key))
        if value is None:
            attrs.pop(f.key, None)
        else:
            attrs[f.key] = value
    status = s("status") if s("status") in STATUSES else STATUS_STOCK
    return ComponentData(
        name=s("name")[:160], object_code=s("object_code"), category=s("category"), model=s("model"),
        manufacturer=s("manufacturer"), serial_number=s("serial_number"), tracking=tracking, quantity=quantity,
        unit=s("unit")[:20] or "pz", min_stock=_int(form.get("min_stock")), status=status,
        machine_id=_int(form.get("machine_id")), location_id=_int(form.get("location_id")), location=s("location"),
        notes=s("notes"), supplier=s("supplier"), purchase_date=_date(form.get("purchase_date")),
        purchase_price=price, warranty_until=_date(form.get("warranty_until")), invoice_ref=s("invoice_ref"),
        attributes=attrs, tags=parse_tags(form.get("tags")),
    )


def apply_component_data(comp, data: ComponentData) -> None:
    for name in ("object_code", "category", "model", "manufacturer", "serial_number", "tracking", "quantity",
                 "unit", "min_stock", "status", "machine_id", "location_id", "location", "notes", "supplier",
                 "purchase_date", "purchase_price", "warranty_until", "invoice_ref", "attributes"):
        setattr(comp, name, getattr(data, name))
    comp.name = data.name or comp.name
