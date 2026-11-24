"""Gestione operatori (admin) e profilo personale."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, redirect, render
from ..models import Operator, OperatorCredential
from ..services import audit, signing, webauthn_svc
from ..services.signing import MIN_PASSWORD_LEN, SignerInfo, require_signer

router = APIRouter()


def _err(request: Request, status: int, message: str, back: str):
    if request.headers.get("x-requested-with", "").lower() == "fetch":
        return JSONResponse({"error": "refused", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _admins_active(db: Session) -> int:
    return db.query(Operator).filter(Operator.is_admin.is_(True), Operator.active.is_(True)).count()


def _target(db: Session, op_id: int) -> Operator | None:
    return db.get(Operator, op_id)


@router.get("/operators")
def operators_list(request: Request, db: Session = Depends(get_db)):
    ops = db.query(Operator).order_by(Operator.name).all()
    return render(request, "operators_list.html", {"operators": ops})


def _admin_action(request: Request, db: Session, signer: SignerInfo, op_id: int):
    if not signer.is_admin:
        return None, _err(request, 403, "Solo un amministratore può gestire gli operatori.", "/operators")
    op = _target(db, op_id)
    if not op:
        return None, _err(request, 404, "Operatore non trovato.", "/operators")
    return op, None


def _is_last_admin(db: Session, op: Operator) -> bool:
    return bool(op.is_admin and op.active and _admins_active(db) <= 1)


@router.post("/operators/{op_id}/disable")
def operator_disable(op_id: int, request: Request, db: Session = Depends(get_db),
                     signer: SignerInfo = Depends(require_signer(critical=True))):
    op, error = _admin_action(request, db, signer, op_id)
    if error:
        return error
    if _is_last_admin(db, op):
        return _err(request, 409, "Non puoi disattivare l'ultimo amministratore attivo.", "/operators")
    op.active = False
    audit.record(db, entity_type="operator", entity_id=op.id, action="disable",
                 before={"active": True}, after={"active": False}, signer=signer)
    db.commit()
    flash(request, f"Operatore \"{op.name}\" disattivato.")
    return redirect(request, "/operators")


@router.post("/operators/{op_id}/enable")
def operator_enable(op_id: int, request: Request, db: Session = Depends(get_db),
                    signer: SignerInfo = Depends(require_signer(critical=True))):
    op, error = _admin_action(request, db, signer, op_id)
    if error:
        return error
    op.active = True
    op.failed_attempts = 0
    op.locked_until = None
    audit.record(db, entity_type="operator", entity_id=op.id, action="enable",
                 before={"active": False}, after={"active": True}, signer=signer)
    db.commit()
    flash(request, f"Operatore \"{op.name}\" riattivato.")
    return redirect(request, "/operators")


@router.post("/operators/{op_id}/reset-password")
def operator_reset_password(op_id: int, request: Request, password: str = Form(""),
                            db: Session = Depends(get_db),
                            signer: SignerInfo = Depends(require_signer(critical=True))):
    op, error = _admin_action(request, db, signer, op_id)
    if error:
        return error
    if len(password) < MIN_PASSWORD_LEN:
        return _err(request, 422, f"La password deve avere almeno {MIN_PASSWORD_LEN} caratteri.", "/operators")
    op.password_hash = signing.hash_password(password)
    op.failed_attempts = 0
    op.locked_until = None
    audit.record(db, entity_type="operator", entity_id=op.id, action="reset_password",
                 after={"password": "impostata"}, signer=signer)
    db.commit()
    flash(request, f"Password di \"{op.name}\" reimpostata.")
    return redirect(request, "/operators")


@router.post("/operators/{op_id}/remove-passkeys")
def operator_remove_passkeys(op_id: int, request: Request, db: Session = Depends(get_db),
                             signer: SignerInfo = Depends(require_signer(critical=True))):
    op, error = _admin_action(request, db, signer, op_id)
    if error:
        return error
    removed = db.query(OperatorCredential).filter(OperatorCredential.operator_id == op.id).delete()
    audit.record(db, entity_type="operator", entity_id=op.id, action="remove_passkeys",
                 after={"rimosse": removed}, signer=signer)
    db.commit()
    flash(request, f"Impronte di \"{op.name}\" rimosse ({removed}).")
    return redirect(request, "/operators")


@router.post("/operators/{op_id}/toggle-admin")
def operator_toggle_admin(op_id: int, request: Request, db: Session = Depends(get_db),
                          signer: SignerInfo = Depends(require_signer(critical=True))):
    op, error = _admin_action(request, db, signer, op_id)
    if error:
        return error
    if _is_last_admin(db, op):
        return _err(request, 409, "Serve almeno un amministratore attivo.", "/operators")
    op.is_admin = not op.is_admin
    audit.record(db, entity_type="operator", entity_id=op.id, action="toggle_admin",
                 before={"is_admin": not op.is_admin}, after={"is_admin": op.is_admin}, signer=signer)
    db.commit()
    flash(request, f"\"{op.name}\": {'amministratore' if op.is_admin else 'operatore'}.")
    return redirect(request, "/operators")


@router.get("/profile")
def profile(request: Request, db: Session = Depends(get_db)):
    signer = signing.current_signer(request, db)
    op = db.get(Operator, signer.operator_id) if signer else None
    _, rp_id = webauthn_svc.origin_and_rp_id(request, request.app.state.settings)
    return render(request, "operator_profile.html", {"op": op, "rp_id": rp_id})


@router.post("/profile/password")
def profile_password(request: Request, password: str = Form(""), db: Session = Depends(get_db),
                     signer: SignerInfo = Depends(require_signer(critical=True))):
    if len(password) < MIN_PASSWORD_LEN:
        return _err(request, 422, f"La password deve avere almeno {MIN_PASSWORD_LEN} caratteri.", "/profile")
    op = db.get(Operator, signer.operator_id)
    op.password_hash = signing.hash_password(password)
    audit.record(db, entity_type="operator", entity_id=op.id, action="change_password",
                 after={"password": "cambiata"}, signer=signer)
    db.commit()
    flash(request, "Password aggiornata.")
    return redirect(request, "/profile")
