"""Allegati: caricamento (anche multiplo, anche da fotocamera), visualizzazione, cestino."""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect
from ..models import Attachment
from ..services import audit, uploads
from ..services.signing import SignerInfo, require_signer

router = APIRouter()
ENTITY_URLS = {"component": "/components/{}", "test_run": "/tests/runs/{}", "incident": "/incidents/{}",
               "change": "/changes/{}", "service": "/services/{}"}


def _back(entity_type: str, entity_id: int) -> str:
    return ENTITY_URLS.get(entity_type, "/").format(entity_id)


@router.post("/attachments")
async def attachments_upload(request: Request, entity_type: str = Form(""), entity_id: int = Form(0),
                             files: list[UploadFile] = File(default=[]), db: Session = Depends(get_db),
                             signer: SignerInfo = Depends(require_signer())):
    back = _back(entity_type, entity_id)
    if entity_type not in ENTITY_URLS or not entity_id:
        return JSONResponse({"error": "invalid", "message": "Destinazione non valida."}, status_code=422)
    saved = []
    try:
        for f in files:
            if f.filename:
                saved.append(uploads.save_upload(request.app.state.settings, db, f, entity_type, entity_id, signer))
    except uploads.UploadRejected as exc:
        db.rollback()
        if is_fetch(request):
            return JSONResponse({"error": "rejected", "message": exc.message}, status_code=exc.status)
        flash(request, exc.message, "error")
        return redirect(request, back)
    for att in saved:
        audit.record(db, entity_type="attachment", entity_id=att.id, action="create",
                     after={"for": f"{entity_type}#{entity_id}", "filename": att.filename, "size": att.size},
                     signer=signer)
    db.commit()
    flash(request, f"{len(saved)} allegati caricati." if len(saved) != 1 else "Allegato caricato.")
    return redirect(request, back)


def _alive(db: Session, att_id: int) -> Attachment | None:
    att = db.get(Attachment, att_id)
    return att if att and att.deleted_at is None else None


@router.get("/attachments/{att_id}")
def attachment_get(att_id: int, request: Request, db: Session = Depends(get_db)):
    att = _alive(db, att_id)
    path = request.app.state.settings.uploads_dir / att.path if att else None
    if not att or not path.exists():
        return PlainTextResponse("Allegato non trovato.", status_code=404)
    disposition = "inline" if att.mime in uploads.INLINE_MIME else "attachment"
    return FileResponse(path, media_type=att.mime, filename=att.filename, content_disposition_type=disposition,
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"})


@router.get("/attachments/{att_id}/thumb")
def attachment_thumb(att_id: int, request: Request, db: Session = Depends(get_db)):
    att = _alive(db, att_id)
    if not att or not att.thumb_path:
        return PlainTextResponse("Miniatura non disponibile.", status_code=404)
    return FileResponse(request.app.state.settings.uploads_dir / att.thumb_path, media_type="image/webp",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.post("/attachments/{att_id}/delete")
def attachment_delete(att_id: int, request: Request, db: Session = Depends(get_db),
                      signer: SignerInfo = Depends(require_signer())):
    att = _alive(db, att_id)
    if not att:
        return redirect(request, "/")
    uploads.trash_attachment(request.app.state.settings, db, att, signer)
    audit.record(db, entity_type="attachment", entity_id=att.id, action="delete",
                 before={"filename": att.filename}, signer=signer)
    db.commit()
    flash(request, f"\"{att.filename}\" spostato nel cestino allegati.")
    return redirect(request, _back(att.entity_type, att.entity_id))


@router.post("/attachments/trash/empty")
def attachments_empty_trash(request: Request, db: Session = Depends(get_db),
                            signer: SignerInfo = Depends(require_signer(critical=True))):
    n = uploads.empty_trash(request.app.state.settings)
    audit.record(db, entity_type="attachment", entity_id=None, action="empty_trash", after={"files": n}, signer=signer)
    db.commit()
    flash(request, f"Cestino allegati svuotato ({n} file).")
    return redirect(request, "/trash")
