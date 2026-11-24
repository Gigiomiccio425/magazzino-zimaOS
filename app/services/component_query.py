"""Filtri lista componenti, inclusi i campi tipizzati (numeri: solo valori davvero numerici)."""
from collections.abc import Mapping

from sqlalchemy import Float, String, and_, cast, func, or_
from sqlalchemy.orm import Query, Session

from ..models import CategoryField, Component, Tag
from .locations import descendant_ids


def _json_value(key: str):
    path = '$."' + key.replace('"', "") + '"'
    return func.json_extract(Component.attributes, path), func.json_type(Component.attributes, path)


def _numeric(key: str):
    value, jtype = _json_value(key)
    is_number = or_(
        jtype.in_(["integer", "real"]),
        and_(jtype == "text", value.op("GLOB")("[0-9]*"), ~value.op("GLOB")("*[^0-9.]*")),
    )
    return value, is_number


def _float(text: str):
    try:
        return float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        return None


def build_component_query(db: Session, params: Mapping[str, str], fields: list[CategoryField]) -> Query:
    q = db.query(Component).filter(Component.deleted_at.is_(None))
    text = (params.get("q") or "").strip()
    if text:
        like = f"%{text}%"
        q = q.filter(or_(
            Component.name.ilike(like), Component.object_code.ilike(like), Component.model.ilike(like),
            Component.manufacturer.ilike(like), Component.serial_number.ilike(like),
            Component.asset_tag.ilike(like), cast(Component.attributes, String).ilike(like),
        ))
    if params.get("category"):
        q = q.filter(Component.category == params["category"])
    if params.get("status"):
        q = q.filter(Component.status == params["status"])
    if params.get("tracking"):
        q = q.filter(Component.tracking == params["tracking"])
    if str(params.get("machine", "")).isdigit():
        q = q.filter(Component.machine_id == int(params["machine"]))
    if str(params.get("location", "")).isdigit():
        q = q.filter(Component.location_id.in_(descendant_ids(db, int(params["location"]))))
    if params.get("tag"):
        q = q.filter(Component.tags.any(Tag.name == params["tag"].strip().lower()))
    if params.get("low_stock") == "1":
        q = q.filter(Component.tracking == "quantity", Component.min_stock.isnot(None),
                     Component.quantity < Component.min_stock)
    for f in fields:
        if not f.filterable:
            continue
        if f.type == "number":
            lo, hi = _float(params.get(f"f{f.id}_min")), _float(params.get(f"f{f.id}_max"))
            if lo is None and hi is None:
                continue
            value, is_number = _numeric(f.key)
            q = q.filter(is_number)
            if lo is not None:
                q = q.filter(cast(value, Float) >= lo)
            if hi is not None:
                q = q.filter(cast(value, Float) <= hi)
        elif params.get(f"f{f.id}"):
            value, _ = _json_value(f.key)
            wanted = params[f"f{f.id}"]
            q = q.filter(value == (1 if f.type == "bool" and wanted == "1" else wanted))
    return q
