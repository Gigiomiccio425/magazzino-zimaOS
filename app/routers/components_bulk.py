"""Modifica di massa ed export/import CSV dei componenti (registrato prima di /components/{id})."""
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import STATUSES, Component, Location, Machine, Tag
from ..services import audit, csv_io
from ..services.inventory import add_movement, machine_name, normalize_assignment, soft_delete
from ..services.locations import location_path
from ..services.signing import SignerInfo, require_signer
from ..timeutil import utcnow

router = APIRouter()
ACTIONS = {"move_location", "move_machine", "set_status", "add_tag"}
MAX_IMPORT = 5 * 1024 * 1024


def _refuse(request: Request, status: int, message: str, back: str = "/components"):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _selected(db: Session, form) -> list[Component]:
    ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    if not ids:
        return []
    return db.query(Component).filter(Component.id.in_(ids), Component.deleted_at.is_(None)).all()


@router.post("/components/bulk")
async def components_bulk(request: Request, db: Session = Depends(get_db),
                          signer: SignerInfo = Depends(require_signer())):
    form = await request.form()
    comps = _selected(db, form)
    action = form.get("action")
    if not comps:
        return _refuse(request, 422, "Seleziona almeno un componente.")
    if action not in ACTIONS:
        return _refuse(request, 422, "Azione non valida.")
    if action == "move_location":
        loc_id = int(form.get("location_id")) if str(form.get("location_id", "")).isdigit() else None
        loc = db.get(Location, loc_id) if loc_id else None
        if loc_id and (not loc or loc.deleted_at):
            return _refuse(request, 422, "Posizione non trovata.")
        for c in comps:
            if c.location_id != loc_id:
                add_movement(db, c, signer, "moved", note=f"Posizione: {location_path(loc) if loc else 'nessuna'}")
                c.location_id = loc_id
    elif action == "move_machine":
        mid = int(form.get("machine_id")) if str(form.get("machine_id", "")).isdigit() else None
        if mid and not db.get(Machine, mid):
            return _refuse(request, 422, "Macchina non trovata.")
        for c in comps:
            old = c.machine_id
            c.machine_id, c.status = normalize_assignment(mid, c.status)
            if old != c.machine_id:
                add_movement(db, c, signer, "moved", note="Spostamento di massa",
                             from_machine=machine_name(db, old), to_machine=machine_name(db, c.machine_id))
    elif action == "set_status":
        status = form.get("status")
        if status not in STATUSES:
            return _refuse(request, 422, "Stato non valido.")
        for c in comps:
            _, new_status = normalize_assignment(c.machine_id, status)
            if c.status != new_status:
                add_movement(db, c, signer, "status", note=f"Stato: {STATUSES.get(c.status)} -> {STATUSES[new_status]}")
                c.status = new_status
    elif action == "add_tag":
        name = " ".join((form.get("tag") or "").split()).lower()[:60]
        if not name:
            return _refuse(request, 422, "Scrivi il tag.")
        tag = db.query(Tag).filter_by(name=name).first() or Tag(name=name)
        db.add(tag)
        for c in comps:
            if tag not in c.tags:
                c.tags.append(tag)
    for c in comps:
        c.updated_by = signer.operator_id
        c.updated_at = utcnow()
    audit.record(db, entity_type="component", entity_id=None, action=f"bulk_{action}",
                 after={"ids": [c.id for c in comps], **{k: form.get(k) for k in ("location_id", "machine_id",
                                                                                  "status", "tag") if form.get(k)}},
                 signer=signer)
    db.commit()
    flash(request, f"{len(comps)} componenti aggiornati.")
    return redirect(request, "/components")


@router.post("/components/bulk/delete")
async def components_bulk_delete(request: Request, db: Session = Depends(get_db),
                                 signer: SignerInfo = Depends(require_signer(critical=True))):
    comps = _selected(db, await request.form())
    for c in comps:
        soft_delete(db, c, signer)
    db.commit()
    flash(request, f"{len(comps)} componenti nel cestino.")
    return redirect(request, "/components")


@router.get("/components/export.csv")
def components_export(db: Session = Depends(get_db)):
    data = csv_io.export_components_csv(db).encode("utf-8")
    name = f"componenti-{utcnow():%Y%m%d}.csv"
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/components/import")
def components_import_page(request: Request, db: Session = Depends(get_db)):
    plan = None
    token = request.session.get("import_file")
    path = request.app.state.settings.tmp_dir / f"import-{token}.csv" if token else None
    if path and path.exists():
        plan = csv_io.plan_import(db, path.read_text(encoding="utf-8"))
    return render(request, "import_preview.html", {"plan": plan})


@router.post("/components/import")
async def components_import_upload(request: Request, file: UploadFile = File(...)):
    raw = await file.read(MAX_IMPORT + 1)
    if len(raw) > MAX_IMPORT:
        return _refuse(request, 413, "File troppo grande (massimo 5 MB).", "/components/import")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _refuse(request, 415, "Il file deve essere CSV in UTF-8.", "/components/import")
    settings = request.app.state.settings
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    (settings.tmp_dir / f"import-{token}.csv").write_text(text, encoding="utf-8")
    request.session["import_file"] = token
    return redirect(request, "/components/import")


@router.post("/components/import/apply")
def components_import_apply(request: Request, db: Session = Depends(get_db),
                            signer: SignerInfo = Depends(require_signer())):
    token = request.session.pop("import_file", None)
    path = request.app.state.settings.tmp_dir / f"import-{token}.csv" if token else None
    if not path or not path.exists():
        return _refuse(request, 422, "Nessun file da importare: caricalo di nuovo.", "/components/import")
    plan = csv_io.plan_import(db, path.read_text(encoding="utf-8"))
    result = csv_io.apply_import(db, plan, signer)
    db.commit()
    path.unlink(missing_ok=True)
    flash(request, f"Import completato: {result.created} creati, {result.updated} aggiornati, "
                   f"{plan.count('error')} righe con errori saltate.")
    return redirect(request, "/components")
