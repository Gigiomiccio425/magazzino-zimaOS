"""Ammortamento lineare: valore attuale dal prezzo e dalla data di acquisto, vita utile per categoria."""
from datetime import date

from sqlalchemy.orm import Session

from ..models import Category, Component

DEFAULT_LIFE_MONTHS = 60


def life_by_category(db: Session) -> dict[str, int]:
    return {c.name: c.useful_life_months for c in db.query(Category) if c.useful_life_months}


def months_between(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + end.month - start.month - (1 if end.day < start.day else 0))


def current_value(comp: Component, life_months: int | None, today: date | None = None) -> int | None:
    """Valore attuale in centesimi (prezzo unitario x quantità), lineare fino a zero. None se manca il prezzo."""
    if comp.purchase_price is None:
        return None
    qty = max(1, comp.quantity or 1) if comp.tracking == "quantity" else 1
    total = comp.purchase_price * qty
    if not comp.purchase_date:
        return total
    life = life_months or DEFAULT_LIFE_MONTHS
    used = months_between(comp.purchase_date, today or date.today())
    return max(0, round(total * (1 - min(used, life) / life)))


def totals(db: Session, comps: list[Component], today: date | None = None) -> dict:
    lives = life_by_category(db)
    bought = current = 0
    for c in comps:
        if c.purchase_price is None:
            continue
        qty = max(1, c.quantity or 1) if c.tracking == "quantity" else 1
        bought += c.purchase_price * qty
        current += current_value(c, lives.get(c.category), today) or 0
    return {"bought": bought, "current": current}
