"""Cestino: elementi eliminati (soft delete), ripristino o eliminazione definitiva (critica)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, redirect, render
from ..models import Component, Location, Machine
from ..services.inventory import purge, restore
from ..services.signing import SignerInfo, require_signer

router = APIRouter()

# tipo -> (modello, etichetta). Posizioni e servizi si aggiungono nei rispettivi task.
TRASH_TYPES: dict[str, tuple[type, str]] = {
    "component": (Component, "Componenti"),
    "machine": (Machine, "Macchine"),
    "location": (Location, "Posizioni"),
}


def _deleted(db: Session, model):
    return db.query(model).filter(model.deleted_at.isnot(None)).order_by(model.deleted_at.desc()).all()


@router.get("/trash")
def trash(request: Request, db: Session = Depends(get_db)):
    groups = [(key, label, _deleted(db, model)) for key, (model, label) in TRASH_TYPES.items()]
    return render(request, "trash.html", {"groups": groups})


def _find(db: Session, kind: str, obj_id: int):
    entry = TRASH_TYPES.get(kind)
    if not entry:
        return None
    obj = db.get(entry[0], obj_id)
    return obj if obj is not None and obj.deleted_at is not None else None


@router.post("/trash/{kind}/{obj_id}/restore")
def trash_restore(kind: str, obj_id: int, request: Request, db: Session = Depends(get_db),
                  signer: SignerInfo = Depends(require_signer())):
    obj = _find(db, kind, obj_id)
    if obj is None:
        flash(request, "Elemento non trovato nel cestino.", "error")
        return redirect(request, "/trash")
    restore(db, obj, signer)
    db.commit()
    flash(request, f"\"{obj.name}\" ripristinato.")
    return redirect(request, "/trash")


@router.post("/trash/{kind}/{obj_id}/purge")
def trash_purge(kind: str, obj_id: int, request: Request, db: Session = Depends(get_db),
                signer: SignerInfo = Depends(require_signer(critical=True))):
    obj = _find(db, kind, obj_id)
    if obj is None:
        flash(request, "Elemento non trovato nel cestino.", "error")
        return redirect(request, "/trash")
    name = obj.name
    purge(db, obj, signer)
    db.commit()
    flash(request, f"\"{name}\" eliminato definitivamente.")
    return redirect(request, "/trash")
