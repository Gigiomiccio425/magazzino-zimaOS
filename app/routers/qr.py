"""QR: redirect /q/TAG, immagine SVG, risoluzione scansioni, fogli etichette stampabili."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import render
from ..models import Component, Location, Machine
from ..services.locations import descendant_ids, location_options
from ..services.qr import TAG_RE, qr_svg, resolve_scan, resolve_tag, tag_url
from ..services.settings_store import base_url

router = APIRouter()
FORMATS = {"small": "25 × 25 mm", "medium": "50 × 25 mm", "a4": "A4 70 × 37 mm"}


@router.get("/q/{tag}")
def q_redirect(tag: str, db: Session = Depends(get_db)):
    url = resolve_tag(db, tag)
    if not url:
        return PlainTextResponse("Codice non trovato (o elemento nel cestino).", status_code=404)
    return RedirectResponse(url, status_code=302)


@router.get("/qr/{tag}.svg")
def qr_image(tag: str, request: Request, db: Session = Depends(get_db)):
    tag = tag.upper()
    if not TAG_RE.match(tag):
        return PlainTextResponse("Codice non valido.", status_code=404)
    svg = qr_svg(tag_url(base_url(request, db), tag), scale=6, standalone=True)
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/scan/resolve")
def scan_resolve(v: str = "", db: Session = Depends(get_db)):
    return JSONResponse(resolve_scan(db, v))


def _ids(text: str) -> list[int]:
    return [int(x) for x in (text or "").split(",") if x.strip().isdigit()]


@router.get("/labels")
def labels(request: Request, components: str = "", locations: str = "", machines: str = "",
           format: str = "medium", db: Session = Depends(get_db)):
    fmt = format if format in FORMATS else "medium"
    base = base_url(request, db)
    paths = dict(location_options(db))
    loc_ids: list[int] = []
    for lid in _ids(locations):
        loc_ids += [i for i in descendant_ids(db, lid) if i not in loc_ids]
    entries = []
    for loc in db.query(Location).filter(Location.id.in_(loc_ids), Location.deleted_at.is_(None)):
        entries.append({"tag": loc.asset_tag, "title": loc.name, "sub": paths.get(loc.id, "")})
    comp_q = db.query(Component).filter(Component.deleted_at.is_(None))
    wanted = set(_ids(components))
    comps = comp_q.filter((Component.id.in_(wanted)) | (Component.location_id.in_(loc_ids))).order_by(Component.name)
    for c in comps:
        entries.append({"tag": c.asset_tag, "title": c.name, "sub": c.category or ""})
    for m in db.query(Machine).filter(Machine.id.in_(_ids(machines)), Machine.deleted_at.is_(None)):
        entries.append({"tag": m.asset_tag, "title": m.name, "sub": m.kind or ""})
    for e in entries:
        e["svg"] = qr_svg(tag_url(base, e["tag"]), scale=3)
    return render(request, "labels.html", {"entries": [e for e in entries if e["tag"]], "fmt": fmt,
                                           "FORMATS": FORMATS, "query": request.url.query})
