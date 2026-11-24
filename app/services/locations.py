"""Posizioni ad albero (stanza > scaffale > box ...)."""
from sqlalchemy.orm import Session

from ..models import Location

SEP = " › "


def _alive(db: Session) -> list[Location]:
    return db.query(Location).filter(Location.deleted_at.is_(None)).all()


def location_path(loc: Location | None) -> str:
    parts, seen = [], set()
    while loc is not None and loc.id not in seen:
        seen.add(loc.id)
        parts.append(loc.name)
        loc = loc.parent
    return SEP.join(reversed(parts))


def descendant_ids(db: Session, loc_id: int) -> list[int]:
    children: dict[int | None, list[int]] = {}
    for loc in _alive(db):
        children.setdefault(loc.parent_id, []).append(loc.id)
    out, stack = [], [loc_id]
    while stack:
        current = stack.pop()
        if current in out:
            continue
        out.append(current)
        stack.extend(children.get(current, []))
    return out


def would_cycle(db: Session, loc_id: int, new_parent_id: int | None) -> bool:
    if new_parent_id is None:
        return False
    return new_parent_id in descendant_ids(db, loc_id)


def location_options(db: Session) -> list[tuple[int, str]]:
    return sorted(((loc.id, location_path(loc)) for loc in _alive(db)), key=lambda x: x[1].casefold())
