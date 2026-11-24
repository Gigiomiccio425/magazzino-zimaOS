"""Endpoint di firma: stato, elenco operatori, password, passkey/impronta, uscita."""
import base64
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Operator, OperatorCredential
from ..services import audit, signing, webauthn_svc
from ..services.signing import MIN_PASSWORD_LEN, normalize_name

router = APIRouter()


class PasswordSign(BaseModel):
    operator_id: int | None = None
    new_name: str | None = None
    password: str | None = None
    action: str | None = None


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


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
    _, rp_id = webauthn_svc.origin_and_rp_id(request, request.app.state.settings)
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


# ---- Passkey / impronta (WebAuthn) ----

CHALLENGE_TTL = 120


class PasskeyBegin(BaseModel):
    new_name: str | None = None
    operator_id: int | None = None
    action: str | None = None


class PasskeyFinish(BaseModel):
    credential: dict
    password: str | None = None
    label: str | None = None


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _store_challenge(request: Request, **data) -> None:
    data["exp"] = signing._now() + CHALLENGE_TTL
    request.session["webauthn"] = data


def _pop_challenge(request: Request, kind: str) -> dict | None:
    data = request.session.pop("webauthn", None)
    if not data or data.get("kind") != kind or data.get("exp", 0) <= signing._now():
        return None
    return data


@router.post("/sign/passkey/register/begin")
def passkey_register_begin(body: PasskeyBegin, request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    origin, rp_id = webauthn_svc.origin_and_rp_id(request, settings)
    if body.new_name is not None:
        display, key = normalize_name(body.new_name)
        if not display:
            return _error(422, "name_required", "Scrivi il nome dell'operatore.")
        if name_taken(db, key):
            return _error(409, "exists", f"Esiste già un operatore \"{display}\": sceglilo dall'elenco.")
        user_id, user_name, exclude, op_id = secrets.token_bytes(16), display, [], None
    else:
        signer = signing.current_signer(request, db)
        if not signer:
            return _error(428, "signature_required", "Firma prima con la password per aggiungere un'impronta.")
        op = db.get(Operator, signer.operator_id)
        user_id, user_name, op_id = str(op.id).encode(), op.name, op.id
        exclude = [c.credential_id for c in op.credentials if c.rp_id == rp_id]
    options, challenge = webauthn_svc.registration_options(rp_id, settings.app_name, user_id, user_name, exclude)
    _store_challenge(request, kind="register", challenge=_b64(challenge), origin=origin, rp_id=rp_id,
                     name=body.new_name, operator_id=op_id, action=body.action)
    return {"options": options}


@router.post("/sign/passkey/register/finish")
def passkey_register_finish(body: PasskeyFinish, request: Request, db: Session = Depends(get_db)):
    ch = _pop_challenge(request, "register")
    if not ch:
        return _error(400, "expired", "Richiesta scaduta: riprova.")
    try:
        reg = webauthn_svc.verify_registration(body.credential, _unb64(ch["challenge"]), ch["origin"], ch["rp_id"])
    except webauthn_svc.PasskeyError:
        return _error(400, "invalid", "Impronta non verificata: riprova.")
    created = ch["operator_id"] is None
    if created:
        display, key = normalize_name(ch["name"] or "")
        if name_taken(db, key):
            return _error(409, "exists", f"Esiste già un operatore \"{display}\".")
        if body.password and len(body.password) < MIN_PASSWORD_LEN:
            return _error(422, "password_short", f"La password deve avere almeno {MIN_PASSWORD_LEN} caratteri.")
        op = create_operator(db, display, key)
        if body.password:
            op.password_hash = signing.hash_password(body.password)
    else:
        op = db.get(Operator, ch["operator_id"])
        if not op or not op.active:
            return _error(404, "not_found", "Operatore non trovato.")
    db.add(OperatorCredential(
        operator_id=op.id, credential_id=reg.credential_id, public_key=reg.public_key,
        sign_count=reg.sign_count, transports=reg.transports, rp_id=ch["rp_id"],
        label=(body.label or request.headers.get("user-agent", ""))[:120],
    ))
    db.flush()
    return _success(request, db, op, "passkey", ch.get("action"), rp_id=ch["rp_id"], created=created)


@router.post("/sign/passkey/auth/begin")
def passkey_auth_begin(body: PasskeyBegin, request: Request, db: Session = Depends(get_db)):
    origin, rp_id = webauthn_svc.origin_and_rp_id(request, request.app.state.settings)
    op = db.get(Operator, body.operator_id) if body.operator_id else None
    if not op or not op.active:
        return _error(404, "not_found", "Operatore non trovato o disattivato.")
    if signing.is_locked(op):
        return _error(423, "locked", "Operatore bloccato per troppi tentativi: riprova tra 15 minuti.")
    creds = [c.credential_id for c in op.credentials if c.rp_id == rp_id]
    if not creds:
        return _error(409, "no_passkey_here", "Nessuna impronta registrata per questo indirizzo: usa la password")
    options, challenge = webauthn_svc.authentication_options(rp_id, creds)
    _store_challenge(request, kind="auth", challenge=_b64(challenge), origin=origin, rp_id=rp_id,
                     operator_id=op.id, action=body.action)
    return {"options": options}


@router.post("/sign/passkey/auth/finish")
def passkey_auth_finish(body: PasskeyFinish, request: Request, db: Session = Depends(get_db)):
    ch = _pop_challenge(request, "auth")
    if not ch:
        return _error(400, "expired", "Richiesta scaduta: riprova.")
    op = db.get(Operator, ch["operator_id"])
    if not op or not op.active:
        return _error(404, "not_found", "Operatore non trovato.")
    creds = [c for c in op.credentials if c.rp_id == ch["rp_id"]]
    wanted = webauthn_svc.credential_id_of(body.credential)
    cred = next((c for c in creds if c.credential_id == wanted), creds[0] if len(creds) == 1 else None)
    if not cred:
        return _error(400, "unknown_credential", "Impronta non riconosciuta per questo operatore.")
    try:
        new_count = webauthn_svc.verify_authentication(
            body.credential, _unb64(ch["challenge"]), ch["origin"], ch["rp_id"], cred.public_key, cred.sign_count,
        )
    except webauthn_svc.PasskeyError:
        signing.register_failure(db, op)
        return _error(400, "invalid", "Impronta non verificata: riprova.")
    cred.sign_count = new_count
    cred.last_used_at = signing._now_dt()
    signing.register_success(db, op)
    return _success(request, db, op, "passkey", ch.get("action"), rp_id=ch["rp_id"])
