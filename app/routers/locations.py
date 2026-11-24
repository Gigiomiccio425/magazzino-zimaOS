"""Posizioni: elenco ad albero, scheda con contenuto (anche sottoposizioni), CRUD firmato."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import LOCATION_KINDS, Component, Location, Machine
from ..services import audit
from ..services.inventory import alive, make_tag, soft_delete
from ..services.locations import descendant_ids, location_options, location_path, would_cycle
from ..services.signing import SignerInfo, require_signer

router = APIRouter()
FIELDS = ["name", "kind", "parent_id", "notes"]


def _refuse(request: Request, status: int, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "refused", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _get(db: Session, loc_id: int) -> Location | None:
    loc = db.get(Location, loc_id)
    return loc if loc and loc.deleted_at is None else None


def _parent(value: str) -> int | None:
    return int(value) if str(value).isdigit() else None


@router.get("/locations")
def locations_list(request: Request, db: Session = Depends(get_db)):
    locs = alive(db.query(Location), Location).all()
    counts = {}
    for loc_id, in alive(db.query(Component.location_id), Component).filter(Component.location_id.isnot(None)):
        counts[loc_id] = counts.get(loc_id, 0) + 1
    tree: dict[int | None, list[Location]] = {}
    for loc in sorted(locs, key=lambda x: x.name.casefold()):
        tree.setdefault(loc.parent_id, []).append(loc)
    return render(request, "locations_list.html", {"tree": tree, "counts": counts, "KINDS": LOCATION_KINDS})


@router.get("/locations/new")
def location_new(request: Request, parent: str = "", db: Session = Depends(get_db)):
    return render(request, "location_form.html", {"loc": None, "options": location_options(db),
                                                  "parent": _parent(parent), "KINDS": LOCATION_KINDS})


@router.post("/locations/new")
def location_create(request: Request, name: str = Form(""), kind: str = Form("altro"), parent_id: str = Form(""),
                    notes: str = Form(""), db: Session = Depends(get_db),
                    signer: SignerInfo = Depends(require_signer())):
    name = name.strip()
    if not name:
        return _refuse(request, 422, "Il nome della posizione è obbligatorio.", "/locations/new")
    parent = _parent(parent_id)
    if parent and not _get(db, parent):
        return _refuse(request, 422, "Posizione superiore non trovata.", "/locations/new")
    loc = Location(name=name[:120], kind=kind if kind in LOCATION_KINDS else "altro", parent_id=parent,
                   notes=notes.strip())
    db.add(loc)
    db.flush()
    loc.asset_tag = make_tag("L", loc.id)
    audit.record(db, entity_type="location", entity_id=loc.id, action="create",
                 after=audit.snapshot(loc, FIELDS + ["asset_tag"]), signer=signer)
    db.commit()
    flash(request, f"Posizione \"{location_path(loc)}\" creata ({loc.asset_tag}).")
    return redirect(request, f"/locations/{loc.id}")


@router.get("/locations/{loc_id}")
def location_detail(loc_id: int, request: Request, db: Session = Depends(get_db)):
    loc = _get(db, loc_id)
    if not loc:
        flash(request, "Posizione non trovata.", "error")
        return redirect(request, "/locations")
    ids = descendant_ids(db, loc.id)
    items = alive(db.query(Component), Component).filter(Component.location_id.in_(ids)).order_by(Component.name).all()
    machines = alive(db.query(Machine), Machine).filter(Machine.location_id.in_(ids)).order_by(Machine.name).all()
    children = alive(db.query(Location), Location).filter(Location.parent_id == loc.id).order_by(Location.name).all()
    return render(request, "location_detail.html", {
        "loc": loc, "path": location_path(loc), "items": items, "machines": machines, "children": children,
        "paths": dict(location_options(db)), "KINDS": LOCATION_KINDS,
    })


@router.get("/locations/{loc_id}/edit")
def location_edit(loc_id: int, request: Request, db: Session = Depends(get_db)):
    loc = _get(db, loc_id)
    if not loc:
        flash(request, "Posizione non trovata.", "error")
        return redirect(request, "/locations")
    options = [(i, p) for i, p in location_options(db) if not would_cycle(db, loc.id, i)]
    return render(request, "location_form.html", {"loc": loc, "options": options, "parent": loc.parent_id,
                                                  "KINDS": LOCATION_KINDS})


@router.post("/locations/{loc_id}/edit")
def location_update(loc_id: int, request: Request, name: str = Form(""), kind: str = Form("altro"),
                    parent_id: str = Form(""), notes: str = Form(""), db: Session = Depends(get_db),
                    signer: SignerInfo = Depends(require_signer())):
    loc = _get(db, loc_id)
    if not loc:
        return _refuse(request, 404, "Posizione non trovata.", "/locations")
    parent = _parent(parent_id)
    if would_cycle(db, loc.id, parent):
        return _refuse(request, 422, "Una posizione non può stare dentro sé stessa o una sua sottoposizione.",
                       f"/locations/{loc.id}/edit")
    before = audit.snapshot(loc, FIELDS)
    loc.name = name.strip()[:120] or loc.name
    loc.kind = kind if kind in LOCATION_KINDS else loc.kind
    loc.parent_id = parent
    loc.notes = notes.strip()
    b, a = audit.changed(before, audit.snapshot(loc, FIELDS))
    if a or b:
        audit.record(db, entity_type="location", entity_id=loc.id, action="update", before=b, after=a, signer=signer)
    db.commit()
    flash(request, "Posizione aggiornata.")
    return redirect(request, f"/locations/{loc.id}")


@router.post("/locations/{loc_id}/delete")
def location_delete(loc_id: int, request: Request, db: Session = Depends(get_db),
                    signer: SignerInfo = Depends(require_signer(critical=True))):
    loc = _get(db, loc_id)
    if not loc:
        return _refuse(request, 404, "Posizione non trovata.", "/locations")
    has_children = alive(db.query(Location), Location).filter(Location.parent_id == loc.id).count()
    has_items = alive(db.query(Component), Component).filter(Component.location_id == loc.id).count()
    if has_children or has_items:
        return _refuse(request, 409, "La posizione non è vuota: sposta prima componenti e sottoposizioni.",
                       f"/locations/{loc.id}")
    soft_delete(db, loc, signer)
    db.commit()
    flash(request, f"Posizione \"{loc.name}\" nel cestino.")
    return redirect(request, "/locations")
