"""Backup: elenco, download, export zip, ripristino (azione critica)."""
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from ..deps import flash, is_fetch, redirect, render
from ..services import audit, backup
from ..services.signing import SignerInfo, require_signer

router = APIRouter()


@router.get("/backups")
def backups_page(request: Request):
    return render(request, "backups.html", {"items": backup.list_backups(request.app.state.settings)})


@router.get("/backups/export")
def backups_export(request: Request):
    path = backup.export_zip(request.app.state.settings)
    return FileResponse(path, media_type="application/zip", filename=path.name,
                        background=BackgroundTask(path.unlink, missing_ok=True))


def _find(request: Request, name: str):
    return next((b for b in backup.list_backups(request.app.state.settings) if b.path.name == name), None)


@router.get("/backups/{kind}/{name}/download")
def backups_download(kind: str, name: str, request: Request):
    item = _find(request, name)
    if not item or item.kind != kind:
        flash(request, "Backup non trovato.", "error")
        return redirect(request, "/backups")
    return FileResponse(item.path, media_type="application/octet-stream", filename=f"{kind}-{name}")


@router.post("/backups/restore")
async def backups_restore(request: Request, file: UploadFile | None = File(None), name: str = Form(""),
                          signer: SignerInfo = Depends(require_signer(critical=True))):
    settings = request.app.state.settings
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = None
    if file is not None and file.filename:
        tmp = settings.tmp_dir / f"restore-{uuid.uuid4().hex}"
        with tmp.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        source = tmp
    else:
        item = _find(request, name)
        if not item:
            return _fail(request, "Scegli un backup o carica un file.")
        source = item.path
    try:
        report = backup.restore_backup(request.app, source)
    except backup.BackupError as exc:
        return _fail(request, str(exc))
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    with Session(bind=request.app.state.engine) as db:  # sessione sul nuovo engine
        # La firma appartiene al DB sostituito: nel DB ripristinato si registra chi e quando, senza riferimenti.
        audit.record(db, entity_type="backup", entity_id=None, action="restore", actor_type="system",
                     after={"from_schema": report.from_schema, "to_schema": report.to_schema,
                            "pre_restore": report.pre_restore_path.name, "operator": signer.operator_name})
        db.commit()
    flash(request, f"Ripristino completato. Stato precedente salvato in {report.pre_restore_path.name}.")
    return redirect(request, "/backups")


def _fail(request: Request, message: str):
    if is_fetch(request):
        return JSONResponse({"error": "restore_failed", "message": message}, status_code=422)
    flash(request, message, "error")
    return redirect(request, "/backups")
