"""Firma operatori: password (scrypt), sessione di firma, token monouso per azioni critiche.

Sessione: request.session["signer"] = {"op", "name", "admin", "sig", "exp"}.
Token azione: request.session["sig_tokens"][token] = {"op", "sig", "action", "exp"}.
"""
import base64
import hashlib
import hmac
import secrets
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Operator, Signature
from .settings_store import get_setting

LOCK_AFTER = 5
LOCK_MINUTES = 15
ACTION_TOKEN_TTL = 120
MIN_PASSWORD_LEN = 6
DEFAULT_WINDOW_MIN = 10
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def _now() -> float:
    """Orologio (sostituibile nei test)."""
    return time.time()


def _now_dt() -> datetime:
    return datetime.fromtimestamp(_now(), UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class SignerInfo:
    operator_id: int
    operator_name: str
    is_admin: bool
    signature_id: int
    expires_at: float


class SignatureRequired(Exception):
    def __init__(self, critical: bool = False):
        super().__init__("signature_required")
        self.critical = critical


# ---- password ----

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    try:
        _, n, r, p, salt_b64, hash_b64 = stored.split("$")
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p), dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def normalize_name(name: str) -> tuple[str, str]:
    """('Nome Visualizzato', 'chiave casefold'): spazi compressi, maiuscole ignorate nella chiave."""
    display = " ".join(unicodedata.normalize("NFC", name or "").split())
    return display, display.casefold()


def action_hash(method: str, path: str) -> str:
    return hashlib.sha256(f"{method.upper()} {path}".encode("utf-8")).hexdigest()


def parse_action(action: str | None) -> str | None:
    """'POST /percorso' -> hash; None se assente o malformato."""
    if not action:
        return None
    parts = action.strip().split(" ", 1)
    if len(parts) != 2 or not parts[1].startswith("/"):
        return None
    return action_hash(parts[0], urlparse(parts[1]).path)


# ---- blocco tentativi ----

def is_locked(op: Operator) -> bool:
    return bool(op.locked_until and op.locked_until > _now_dt())


def register_failure(db: Session, op: Operator) -> None:
    op.failed_attempts = (op.failed_attempts or 0) + 1
    if op.failed_attempts >= LOCK_AFTER:
        op.locked_until = _now_dt() + timedelta(minutes=LOCK_MINUTES)
        op.failed_attempts = 0
    db.commit()


def register_success(db: Session, op: Operator) -> None:
    op.failed_attempts = 0
    op.locked_until = None


# ---- sessione di firma ----

def window_minutes(db: Session) -> int:
    try:
        return int(get_setting(db, "signature_window_min"))
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_MIN


def create_signature(db: Session, request: Request, op: Operator, method: str,
                     purpose: str | None = None, rp_id: str | None = None) -> Signature:
    sig = Signature(
        operator_id=op.id, method=method, purpose=purpose,
        action_hash=parse_action(purpose), rp_id=rp_id,
        ip=(request.client.host if request.client else "")[:60],
        user_agent=request.headers.get("user-agent", "")[:300],
        created_at=_now_dt(),
    )
    db.add(sig)
    db.flush()
    return sig


def start_signing_session(request: Request, db: Session, op: Operator, sig: Signature) -> SignerInfo:
    exp = _now() + window_minutes(db) * 60
    request.session["signer"] = {"op": op.id, "name": op.name, "admin": bool(op.is_admin), "sig": sig.id, "exp": exp}
    return SignerInfo(op.id, op.name, bool(op.is_admin), sig.id, exp)


def _server_state(request: Request) -> tuple[set, set]:
    """Token gia' usati e firme chiuse con "Esci": tenuti in memoria dal server, cosi' ripresentare
    un cookie vecchio non li riattiva (un solo processo uvicorn)."""
    state = request.app.state
    if not hasattr(state, "used_sig_tokens"):
        state.used_sig_tokens, state.revoked_signatures = set(), set()
    return state.used_sig_tokens, state.revoked_signatures


def end_signing_session(request: Request) -> None:
    data = request.session.pop("signer", None)
    if data and data.get("sig") is not None:
        _server_state(request)[1].add(data["sig"])


def session_signer(request: Request) -> dict | None:
    """Dati di sessione ancora validi per la barra in alto (nessuna query DB)."""
    data = request.session.get("signer")
    if data and data.get("exp", 0) > _now() and data.get("sig") not in _server_state(request)[1]:
        return data
    return None


def _active_operator(db: Session, op_id: int) -> Operator | None:
    op = db.get(Operator, op_id)
    return op if op and op.active else None


def current_signer(request: Request, db: Session) -> SignerInfo | None:
    data = session_signer(request)
    if not data:
        return None
    op = _active_operator(db, data["op"])
    if not op:
        end_signing_session(request)
        return None
    return SignerInfo(op.id, op.name, bool(op.is_admin), data["sig"], data["exp"])


def issue_action_token(request: Request, op: Operator, signature_id: int, action: str) -> str:
    tokens = {k: v for k, v in request.session.get("sig_tokens", {}).items() if v["exp"] > _now()}
    token = secrets.token_urlsafe(24)
    tokens[token] = {"op": op.id, "sig": signature_id, "action": parse_action(action), "exp": _now() + ACTION_TOKEN_TTL}
    request.session["sig_tokens"] = tokens
    return token


def consume_action_token(request: Request, db: Session, token: str, action: str) -> SignerInfo | None:
    """Token valido una sola volta, solo per l'azione firmata e entro ACTION_TOKEN_TTL."""
    used = _server_state(request)[0]
    tokens = dict(request.session.get("sig_tokens", {}))
    data = tokens.pop(token, None)
    if token in used:
        return None
    used.add(token)
    request.session["sig_tokens"] = {k: v for k, v in tokens.items() if v["exp"] > _now()}
    if not data or data["exp"] <= _now() or not hmac.compare_digest(data["action"] or "", action):
        return None
    op = _active_operator(db, data["op"])
    if not op:
        return None
    return SignerInfo(op.id, op.name, bool(op.is_admin), data["sig"], data["exp"])


async def _sent_token(request: Request) -> str | None:
    token = request.headers.get("x-sig-token")
    if not token and "form" in request.headers.get("content-type", ""):
        token = (await request.form()).get("sig_token")
    return token or None


def require_signer(critical: bool = False):
    """Dipendenza FastAPI: operatore firmato (sessione) o token azione; critica = solo token."""

    async def dependency(request: Request, db: Session = Depends(get_db)) -> SignerInfo:
        token = await _sent_token(request)
        if token:
            info = consume_action_token(request, db, token, action_hash(request.method, request.url.path))
            if info:
                return info
        if not critical:
            info = current_signer(request, db)
            if info:
                return info
        raise SignatureRequired(critical)

    return dependency
