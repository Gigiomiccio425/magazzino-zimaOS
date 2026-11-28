"""Codici generati in automatico per ogni componente.

- Seriale di magazzino: leggibile e costruito dall'oggetto, CATEGORIA-MARCA-SPECIFICA-NNNN
  (es. RAM-KIN-D4-16G-0007, SSD-SAM-1T-0002, GPU-NVI-10G-0001). Il progressivo è per prefisso.
- Codice di riferimento: GD-XXXX-XXXX, casuale (alfabeto senza lettere ambigue) con l'ultima
  cifra di controllo: un errore di battitura viene riconosciuto.

Entrambi sono unici (indice unico nel DB) e non cambiano più dopo la creazione.
"""
import re
import secrets
import unicodedata

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Component

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: niente I, L, O, U
REF_RE = re.compile(r"^GD-([0-9A-HJKMNP-TV-Z]{4})-([0-9A-HJKMNP-TV-Z]{4})$")
CATEGORY_CODES = {
    "ram": "RAM", "ssd": "SSD", "hdd": "HDD", "cpu": "CPU", "gpu": "GPU", "scheda madre": "MB",
    "alimentatore": "PSU", "case": "CASE", "ventola": "FAN", "cavo": "CAV", "scheda di rete": "NET",
    "periferica": "PER", "altro": "ALT",
}


def _ascii(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _check_char(body: str) -> str:
    total = sum((i + 1) * ALPHABET.index(ch) for i, ch in enumerate(body))
    return ALPHABET[total % 32]


def new_ref_code() -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(7))
    code = body + _check_char(body)
    return f"GD-{code[:4]}-{code[4:]}"


def is_valid_ref_code(value: str) -> bool:
    m = REF_RE.match((value or "").strip().upper())
    if not m:
        return False
    code = m.group(1) + m.group(2)
    return _check_char(code[:7]) == code[7]


def _number(value) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _size(gb: float | None) -> str:
    if not gb:
        return ""
    if gb >= 1000:
        return f"{gb / 1000:g}T".replace(".", "")
    if gb < 1:
        return f"{int(gb * 1024)}M"
    return f"{gb:g}G".replace(".", "")


def _spec(comp: Component) -> str:
    attrs = comp.attributes or {}
    cat = (comp.category or "").strip().lower()
    if cat == "ram":
        tipo = str(attrs.get("Tipo") or "")
        gen = re.search(r"DDR(\d?)", tipo.upper())
        short = ("S" if "SO-DIMM" in tipo.upper() else "") + ("D" + (gen.group(1) or "1") if gen else "")
        return "-".join(x for x in [short, _size(_number(attrs.get("Capacita (GB)")))] if x)
    if cat in ("ssd", "hdd"):
        return _size(_number(attrs.get("Capacita (GB)")))
    if cat == "gpu":
        return _size(_number(attrs.get("VRAM (GB)")))
    if cat == "alimentatore":
        watt = _number(attrs.get("Potenza (W)"))
        return f"{watt:g}W" if watt else ""
    return _ascii(comp.model)[:6]


def stock_serial_prefix(comp: Component) -> str:
    cat = (comp.category or "").strip()
    cat_code = CATEGORY_CODES.get(cat.lower()) or (_ascii(cat)[:4] or "ART")
    maker = _ascii(comp.manufacturer)[:3] or "GEN"
    spec = _spec(comp)
    return "-".join(x for x in [cat_code, maker, spec] if x)[:34]


def new_stock_serial(db: Session, comp: Component) -> str:
    prefix = stock_serial_prefix(comp)
    used = [s for (s,) in db.query(Component.stock_serial).filter(Component.stock_serial.like(prefix + "-%"))]
    numbers = [int(s.rsplit("-", 1)[1]) for s in used if s.rsplit("-", 1)[-1].isdigit()]
    return f"{prefix}-{(max(numbers) + 1 if numbers else 1):04d}"


def assign_codes(db: Session, comp: Component) -> None:
    """Assegna i codici mancanti (mai sovrascrive quelli esistenti). Il chiamante fa flush/commit."""
    if not comp.ref_code:
        while True:
            code = new_ref_code()
            if not db.query(Component.id).filter(Component.ref_code == code).first():
                comp.ref_code = code
                break
    if not comp.stock_serial:
        db.flush()  # i seriali già assegnati in questa sessione contano per il progressivo
        comp.stock_serial = new_stock_serial(db, comp)


def backfill(db: Session) -> int:
    """Dà i codici ai componenti che non li hanno ancora (dopo l'aggiornamento). Ritorna quanti."""
    todo = db.query(Component).filter((Component.ref_code.is_(None)) | (Component.stock_serial.is_(None))
                                      | (Component.ref_code == "") | (Component.stock_serial == "")) \
        .order_by(Component.id).all()
    for comp in todo:
        assign_codes(db, comp)
        db.flush()
    return len(todo)


def count_missing(db: Session) -> int:
    return db.query(func.count(Component.id)).filter(Component.ref_code.is_(None)).scalar() or 0
