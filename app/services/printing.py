"""Coda di stampa e impaginazione delle etichette su fogli A4.

Tre formati:
- label: etichetta 70 x 37 mm (fogli 3 x 8, i più diffusi), codice scaffale grande + nome + QR;
- qr:    solo QR, quadretti da 35 mm (6 x 8 per foglio);
- flag:  bandiera per cavi: lato A | zona di giro | lato B. La zona di giro si avvolge attorno
         al cavo e i due lati si chiudono uno sull'altro; la lunghezza dipende dal diametro.
"""
import math
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import Component, Location, Machine, PrintItem
from .locations import location_path

FORMATS = {"label": "Etichetta", "qr": "Solo QR", "flag": "Bandiera cavo"}
SHEET_NAMES = {"label": "Etichette 70 × 37 mm", "qr": "Solo QR 30 mm", "flag": "Bandiere per cavi"}
ENTITY_MODELS = {"component": Component, "location": Location, "machine": Machine}
MAX_COPIES = 99
MAX_QUEUE = 500

A4_W, A4_H = 210.0, 297.0
FLAG_SIDE = 36.0
FLAG_H = 22.0
FLAG_MARGIN = 10.0
DIAM_MIN, DIAM_MAX, DIAM_DEFAULT = 2, 14, 6


@dataclass
class Entry:
    item_id: int
    entity_type: str
    entity_id: int
    tag: str
    title: str
    place: str
    sub: str
    format: str
    copies: int

    @property
    def short(self) -> str:
        return self.title if len(self.title) <= 26 else self.title[:25].rstrip() + "…"


@dataclass
class Sheet:
    format: str
    cell_w: float
    cell_h: float
    cols: int
    rows: int
    left: float
    top: float
    wrap: float = 0.0
    pages: list[list[Entry | None]] = field(default_factory=list)

    @property
    def per_page(self) -> int:
        return self.cols * self.rows

    def slot_style(self, index: int) -> str:
        col, row = index % self.cols, index // self.cols
        return (f"left:{self.left + col * self.cell_w:.2f}mm;top:{self.top + row * self.cell_h:.2f}mm;"
                f"width:{self.cell_w:.2f}mm;height:{self.cell_h:.2f}mm")


def wrap_length(diameter_mm: int) -> int:
    """Circonferenza del cavo più 4 mm di sovrapposizione, arrotondata al millimetro."""
    return round(math.pi * diameter_mm + 4)


def clamp_diameter(value) -> int:
    try:
        d = int(value)
    except (TypeError, ValueError):
        return DIAM_DEFAULT
    return max(DIAM_MIN, min(DIAM_MAX, d))


def sheet_geometry(fmt: str, diameter: int = DIAM_DEFAULT) -> Sheet:
    if fmt == "qr":
        return Sheet("qr", 35.0, 35.0, 6, 8, 0.0, 8.5)
    if fmt == "flag":
        wrap = wrap_length(diameter)
        w = 2 * FLAG_SIDE + wrap
        cols = max(1, int((A4_W - 2 * FLAG_MARGIN) // w))
        rows = int((A4_H - 2 * FLAG_MARGIN) // FLAG_H)
        return Sheet("flag", w, FLAG_H, cols, rows, (A4_W - cols * w) / 2, (A4_H - rows * FLAG_H) / 2, wrap=wrap)
    return Sheet("label", 70.0, 37.0, 3, 8, 0.0, 0.5)


def _describe(db: Session, item: PrintItem) -> Entry | None:
    model = ENTITY_MODELS.get(item.entity_type)
    obj = db.get(model, item.entity_id) if model else None
    if obj is None or getattr(obj, "deleted_at", None) is not None or not obj.asset_tag:
        return None
    if isinstance(obj, Component):
        if obj.machine_id and obj.machine:
            place = obj.machine.name
        elif obj.location_id and obj.place:
            place = obj.place.name
        else:
            place = "—"
        title, sub = obj.name, obj.category or ""
    elif isinstance(obj, Location):
        place, title, sub = obj.name, location_path(obj), "Posizione"
    else:
        place, title, sub = obj.name, obj.kind or "Macchina", obj.hostname or ""
    return Entry(item.id, item.entity_type, item.entity_id, obj.asset_tag, title, place, sub,
                 item.format if item.format in FORMATS else "label", max(1, min(MAX_COPIES, item.copies or 1)))


def queue_entries(db: Session) -> list[Entry]:
    """Elementi in coda ancora esistenti, nell'ordine di inserimento."""
    items = db.query(PrintItem).order_by(PrintItem.created_at, PrintItem.id).all()
    return [e for e in (_describe(db, it) for it in items) if e is not None]


def add_to_queue(db: Session, entity_type: str, ids: list[int], fmt: str | None, operator: str | None) -> int:
    """Aggiunge (o aggiorna il formato di) elementi esistenti. Ritorna quanti ne ha toccati."""
    model = ENTITY_MODELS.get(entity_type)
    if model is None or not ids:
        return 0
    if fmt is not None and fmt not in FORMATS:
        fmt = None
    found = db.query(model).filter(model.id.in_(ids), model.deleted_at.is_(None)).all()
    existing = {p.entity_id: p for p in db.query(PrintItem).filter(PrintItem.entity_type == entity_type,
                                                                   PrintItem.entity_id.in_([o.id for o in found]))}
    room = MAX_QUEUE - db.query(PrintItem).count()
    touched = 0
    for obj in found:
        if not obj.asset_tag:
            continue
        item = existing.get(obj.id)
        if item is not None:
            if fmt:
                item.format = fmt
        elif room > 0:
            default = "flag" if entity_type == "component" and (obj.category or "").lower().startswith("cav") else "label"
            db.add(PrintItem(entity_type=entity_type, entity_id=obj.id, format=fmt or default, copies=1,
                             added_by=operator))
            room -= 1
        else:
            continue
        touched += 1
    return touched


def layout(entries: list[Entry], fmt: str, diameter: int = DIAM_DEFAULT, start: int = 1) -> Sheet:
    """Impagina le copie degli elementi del formato scelto; `start` salta le caselle già usate del primo foglio."""
    sheet = sheet_geometry(fmt, diameter)
    copies = [e for e in entries if e.format == fmt for _ in range(e.copies)]
    skip = max(0, min(sheet.per_page - 1, (start or 1) - 1))
    slots: list[Entry | None] = [None] * skip + copies
    for i in range(0, max(len(slots), 1), sheet.per_page):
        page = slots[i:i + sheet.per_page]
        sheet.pages.append(page + [None] * (sheet.per_page - len(page)))
    if not copies:
        sheet.pages = []
    return sheet


def page_counts(entries: list[Entry], diameter: int = DIAM_DEFAULT, start: int = 1) -> dict[str, tuple[int, int]]:
    """Per ogni formato: (etichette, fogli)."""
    out = {}
    for fmt in FORMATS:
        n = sum(e.copies for e in entries if e.format == fmt)
        out[fmt] = (n, len(layout(entries, fmt, diameter, start).pages))
    return out


# ---------------------------------------------------------------------------
# Foglio unico ottimizzato: tutti i formati insieme su carta adesiva A4 intera.
# ---------------------------------------------------------------------------
MIX_MARGIN = 6.0  # bordo che quasi tutte le stampanti non riescono a stampare
MIX_GAP = 2.0     # spazio fra un pezzo e l'altro per ritagliare
QR_CELL = (30.0, 34.0)
LABEL_CELL = (70.0, 37.0)


@dataclass
class Placement:
    entry: Entry
    format: str
    x: float
    y: float
    w: float
    h: float

    @property
    def style(self) -> str:
        return f"left:{self.x:.2f}mm;top:{self.y:.2f}mm;width:{self.w:.2f}mm;height:{self.h:.2f}mm"


def cell_size(fmt: str, diameter: int = DIAM_DEFAULT) -> tuple[float, float]:
    if fmt == "qr":
        return QR_CELL
    if fmt == "flag":
        return 2 * FLAG_SIDE + wrap_length(diameter), FLAG_H
    return LABEL_CELL


def pack(entries: list[Entry], diameter: int = DIAM_DEFAULT) -> list[list[Placement]]:
    """Impagina tutte le copie su fogli A4 a righe ("scaffali"), dal pezzo più alto al più basso.

    Ogni pezzo va nel primo spazio libero di qualsiasi foglio già aperto (anche nel resto di una
    riga di etichette ci entra un QR), così i fogli sono il meno possibile.
    """
    usable_w, usable_h = A4_W - 2 * MIX_MARGIN, A4_H - 2 * MIX_MARGIN
    items = []
    for order, e in enumerate(entries):
        w, h = cell_size(e.format, diameter)
        items += [(h, w, order, e)] * e.copies
    items.sort(key=lambda it: (-it[0], -it[1], it[2]))

    pages: list[dict] = []  # {"shelves": [[y, h, used_w]], "used_h": float, "items": [...]}
    for h, w, _order, e in items:
        if w > usable_w:
            continue  # più largo del foglio (non succede con i diametri ammessi)
        placed = False
        for page in pages:
            for shelf in page["shelves"]:
                gap = MIX_GAP if shelf[2] else 0.0
                if h <= shelf[1] and shelf[2] + gap + w <= usable_w:
                    page["items"].append(Placement(e, e.format, MIX_MARGIN + shelf[2] + gap, MIX_MARGIN + shelf[0], w, h))
                    shelf[2] += gap + w
                    placed = True
                    break
            if placed:
                break
            gap = MIX_GAP if page["shelves"] else 0.0
            if page["used_h"] + gap + h <= usable_h:
                y = page["used_h"] + gap
                page["shelves"].append([y, h, w])
                page["used_h"] = y + h
                page["items"].append(Placement(e, e.format, MIX_MARGIN, MIX_MARGIN + y, w, h))
                placed = True
                break
        if not placed:
            pages.append({"shelves": [[0.0, h, w]], "used_h": h,
                          "items": [Placement(e, e.format, MIX_MARGIN, MIX_MARGIN, w, h)]})
    return [p["items"] for p in pages]


def separate_page_count(entries: list[Entry], diameter: int = DIAM_DEFAULT) -> int:
    return sum(len(layout(entries, fmt, diameter).pages) for fmt in FORMATS)
