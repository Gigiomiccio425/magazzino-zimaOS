"""QR (segno, offline) e risoluzione delle scansioni: URL /q/TAG, tag nudo, seriale, codice oggetto."""
import io
import re
from urllib.parse import quote, urlparse

import segno
from sqlalchemy.orm import Session

from ..models import Component, Location, Machine

TAG_RE = re.compile(r"^[CML]-\d{3,}$")
_URL_TAG = re.compile(r"/q/([CMLcml]-\d{3,})/?$")
_MODELS = {"C": (Component, "/components/"), "M": (Machine, "/machines/"), "L": (Location, "/locations/")}


def qr_svg(data: str, scale: int = 4, standalone: bool = False) -> str:
    """SVG del QR. standalone=True aggiunge xmlns (file .svg servito come immagine)."""
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=scale, border=2, dark="#111111", light="#ffffff",
                                     xmldecl=False, svgns=standalone, nl=False)
    return buf.getvalue().decode("utf-8")


def tag_url(base_url: str, tag: str) -> str:
    return f"{base_url.rstrip('/')}/q/{tag}"


def resolve_tag(db: Session, tag: str) -> str | None:
    tag = (tag or "").strip().upper()
    if not TAG_RE.match(tag):
        return None
    model, prefix = _MODELS[tag[0]]
    obj = db.query(model).filter(model.asset_tag == tag, model.deleted_at.is_(None)).first()
    return f"{prefix}{obj.id}" if obj else None


def resolve_scan(db: Session, value: str) -> dict:
    value = (value or "").strip()
    match = _URL_TAG.search(urlparse(value).path) if "://" in value else None
    candidate = match.group(1) if match else value
    url = resolve_tag(db, candidate)
    if url:
        return {"url": url}
    if value:
        hits = (
            db.query(Component.id)
            .filter(Component.deleted_at.is_(None),
                    (Component.serial_number == value) | (Component.object_code == value)
                    | (Component.stock_serial == value.upper()) | (Component.ref_code == value.upper()))
            .limit(2).all()
        )
        if len(hits) == 1:
            return {"url": f"/components/{hits[0][0]}"}
    if value:
        from .presets import recognize  # modello riconosciuto dalla sigla: si propone un nuovo componente
        found = recognize(value)
        if found is not None:
            return {"new": f"/components/new?part={quote(value)}", "model": found.label,
                    "search": f"/components?q={quote(found.part or value)}"}
    return {"search": f"/components?q={quote(value)}"}
