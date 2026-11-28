"""Report e grafici (sola lettura), stampabili in PDF dal browser. Sedi del magazzino."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import Component, Location, Machine, Site
from ..services import audit, reports
from ..services.signing import SignerInfo, require_signer

router = APIRouter()


@router.get("/reports")
def reports_page(request: Request, db: Session = Depends(get_db)):
    values = reports.value_by_category(db)
    top = max([v["bought"] for v in values] + [1])
    return render(request, "reports.html", {
        "values": values, "top": top,
        "total_bought": sum(v["bought"] for v in values), "total_current": sum(v["current"] for v in values),
        "consumption": reports.consumption(db), "faults": reports.faults(db), "idle": reports.idle(db),
    })


# ---------------------------------------------------------------- sedi
def _site_of_locations(db: Session) -> dict[int, int | None]:
    """Sede di ogni posizione: quella della posizione principale da cui discende."""
    locs = {loc.id: loc for loc in db.query(Location).filter(Location.deleted_at.is_(None))}
    out: dict[int, int | None] = {}
    for lid in locs:
        cur, seen = locs.get(lid), set()
        while cur is not None and cur.site_id is None and cur.parent_id and cur.parent_id not in seen:
            seen.add(cur.id)
            cur = locs.get(cur.parent_id)
        out[lid] = cur.site_id if cur is not None else None
    return out


@router.get("/sites")
def sites_page(request: Request, db: Session = Depends(get_db)):
    sites = db.query(Site).filter(Site.deleted_at.is_(None)).order_by(Site.name).all()
    loc_site = _site_of_locations(db)
    counts: dict[int | None, int] = {}
    for cid, lid in db.query(Component.id, Component.location_id).filter(Component.deleted_at.is_(None)):
        key = loc_site.get(lid) if lid else None
        counts[key] = counts.get(key, 0) + 1
    machines = dict(db.query(Machine.site_id, func.count(Machine.id)).filter(Machine.deleted_at.is_(None))
                    .group_by(Machine.site_id).all())
    roots = (db.query(Location).filter(Location.deleted_at.is_(None), Location.parent_id.is_(None))
             .order_by(Location.name).all())
    return render(request, "sites.html", {"sites": sites, "counts": counts, "machines": machines, "roots": roots,
                                          "all_machines": db.query(Machine).filter(Machine.deleted_at.is_(None))
                                          .order_by(Machine.name).all()})


def _back_err(request: Request, status: int, message: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, "/sites")


@router.post("/sites/new")
async def site_create(request: Request, db: Session = Depends(get_db), signer: SignerInfo = Depends(require_signer())):
    form = await request.form()
    name = " ".join(str(form.get("name") or "").split())[:120]
    if not name:
        return _back_err(request, 422, "Il nome della sede è obbligatorio.")
    if db.query(Site).filter(Site.name == name).first():
        return _back_err(request, 409, "Esiste già una sede con questo nome.")
    site = Site(name=name, address=" ".join(str(form.get("address") or "").split())[:300])
    db.add(site)
    db.flush()
    audit.record(db, entity_type="site", entity_id=site.id, action="create", after={"name": name}, signer=signer)
    db.commit()
    flash(request, f"Sede \"{name}\" creata.")
    return redirect(request, "/sites")


@router.post("/sites/assign")
async def site_assign(request: Request, db: Session = Depends(get_db), signer: SignerInfo = Depends(require_signer())):
    """Assegna una posizione principale o una macchina a una sede (vuoto = nessuna)."""
    form = await request.form()
    raw = str(form.get("site_id") or "")
    site = db.get(Site, int(raw)) if raw.isdigit() else None
    if raw and site is None:
        return _back_err(request, 404, "Sede non trovata.")
    kind, oid = form.get("kind"), str(form.get("id") or "")
    model = {"location": Location, "machine": Machine}.get(kind)
    obj = db.get(model, int(oid)) if model and oid.isdigit() else None
    if obj is None or obj.deleted_at is not None:
        return _back_err(request, 404, "Elemento non trovato.")
    before = obj.site_id
    obj.site_id = site.id if site else None
    audit.record(db, entity_type=kind, entity_id=obj.id, action="update", before={"site_id": before},
                 after={"site_id": obj.site_id}, signer=signer)
    db.commit()
    flash(request, f"{obj.name}: sede {site.name if site else 'nessuna'}.")
    return redirect(request, "/sites")
