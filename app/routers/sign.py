"""Endpoint di firma: stato, elenco operatori, firma con password, uscita."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Operator, OperatorCredential
from ..services import audit, signing
from ..services.signing import MIN_PASSWORD_LEN, normalize_name

router = APIRouter()


class PasswordSign(BaseModel):
    operator_id: int | None = None
    new_name: str | None = None
    password: str | None = None
    action: str | None = None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


def request_rp_id(request: Request) -> str:
    """Dominio usato per le passkey (sostituito da webauthn_svc in Task 8)."""
    from urllib.parse import urlparse

    settings = request.app.state.settings
    if settings.webauthn_rp_id:
        return settings.webauthn_rp_id
    origin = request.headers.get("origin")
    return (urlparse(origin).hostname if origin else request.url.hostname) or ""


def _success(request: Request, db: Session, op: Operator, method: str, action: str | None,
             rp_id: str | None = None, created: bool = False) -> JSONResponse:
    sig = signing.create_signature(db, request, op, method, purpose=action, rp_id=rp_id)
    info = signing.start_signing_session(request, db, op, sig)
    if created:
        audit.record(db, entity_type="operator", entity_id=op.id, action="create",
                     after={"name": op.name, "is_admin": op.is_admin, "method": method}, signer=info)
    body = {"ok": True, "operator": op.name, "is_admin": bool(op.is_admin)}
    if action:
        if not signing.parse_action(action):
            db.rollback()
            return _error(422, "bad_action", "Azione da firmare non valida.")
        body["action_token"] = signing.issue_action_token(request, op, sig.id, action)
    db.commit()
    return JSONResponse(body)


def create_operator(db: Session, display: str, key: str) -> Operator:
    first = db.query(Operator).count() == 0
    op = Operator(name=display, name_key=key, is_admin=first, active=True)
    db.add(op)
    db.flush()
    return op


def name_taken(db: Session, key: str) -> bool:
    return db.query(Operator).filter(Operator.name_key == key).first() is not None


@router.get("/sign/state")
def sign_state(request: Request, db: Session = Depends(get_db)):
    info = signing.current_signer(request, db)
    if not info:
        return {"signed": False, "operator": None, "expires_in": 0}
    return {"signed": True, "operator": info.operator_name,
            "expires_in": max(0, int(info.expires_at - signing._now()))}


@router.get("/sign/operators")
def sign_operators(request: Request, db: Session = Depends(get_db)):
    rp_id = request_rp_id(request)
    ops = db.query(Operator).filter(Operator.active.is_(True)).order_by(Operator.name).all()
    here = {
        op_id for (op_id,) in db.query(OperatorCredential.operator_id).filter(OperatorCredential.rp_id == rp_id)
    }
    return [
        {"id": o.id, "name": o.name, "has_password": bool(o.password_hash), "passkey_here": o.id in here}
        for o in ops
    ]


@router.post("/sign/password")
def sign_password(body: PasswordSign, request: Request, db: Session = Depends(get_db)):
    password = body.password or ""
    if body.new_name is not None:
        display, key = normalize_name(body.new_name)
        if not display:
            return _error(422, "name_required", "Scrivi il nome dell'operatore.")
        if name_taken(db, key):
            return _error(409, "exists", f"Esiste già un operatore \"{display}\": sceglilo dall'elenco.")
        if len(password) < MIN_PASSWORD_LEN:
            return _error(422, "password_short", f"La password deve avere almeno {MIN_PASSWORD_LEN} caratteri.")
        op = create_operator(db, display, key)
        op.password_hash = signing.hash_password(password)
        return _success(request, db, op, "password", body.action, created=True)

    op = db.get(Operator, body.operator_id) if body.operator_id else None
    if not op or not op.active:
        return _error(404, "not_found", "Operatore non trovato o disattivato.")
    if signing.is_locked(op):
        return _error(423, "locked", "Troppi tentativi errati: riprova tra 15 minuti.")
    if not op.password_hash:
        return _error(409, "no_password", "Questo operatore non ha una password: usa l'impronta.")
    if not signing.verify_password(password, op.password_hash):
        signing.register_failure(db, op)
        return _error(401, "wrong_password", "Password errata.")
    signing.register_success(db, op)
    return _success(request, db, op, "password", body.action)


@router.post("/sign/logout")
def sign_logout(request: Request):
    signing.end_signing_session(request)
    return {"ok": True}
