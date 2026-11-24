"""Audit log: una riga per ogni scrittura, concatenate con hash SHA-256 (a prova di manomissione)."""
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import AuditLog
from ..timeutil import utcnow

GENESIS = "0" * 64


@dataclass(frozen=True)
class ChainReport:
    ok: bool
    checked: int
    first_bad_id: int | None


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def snapshot(obj, fields: Sequence[str]) -> dict:
    return {f: _plain(getattr(obj, f, None)) for f in fields}


def changed(before: dict, after: dict) -> tuple[dict, dict]:
    """Solo le chiavi che cambiano (chiave assente = None)."""
    keys = set(before) | set(after)
    diff = [k for k in sorted(keys) if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in diff}, {k: after.get(k) for k in diff}


def _canonical(row: AuditLog, prev_hash: str) -> str:
    payload = {
        "ts": row.ts.isoformat(timespec="microseconds"),
        "actor_type": row.actor_type,
        "operator_id": row.operator_id,
        "signature_id": row.signature_id,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "action": row.action,
        "before": row.before,
        "after": row.after,
        "prev_hash": prev_hash,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash(row: AuditLog, prev_hash: str) -> str:
    return hashlib.sha256((prev_hash + _canonical(row, prev_hash)).encode("utf-8")).hexdigest()


def record(
    db: Session,
    *,
    entity_type: str,
    entity_id: int | None,
    action: str,
    before: dict | None = None,
    after: dict | None = None,
    signer=None,
    actor_type: str = "operator",
) -> AuditLog:
    """Aggiunge una riga (flush, senza commit: il chiamante committa con la sua transazione)."""
    db.flush()
    # Scrittura fittizia: apre la transazione di scrittura (lock SQLite) PRIMA di leggere l'ultimo hash,
    # cosi' due salvataggi contemporanei non possono partire dallo stesso prev_hash.
    db.execute(text("UPDATE audit_log SET id = id WHERE 0"))
    last = db.query(AuditLog.hash).order_by(AuditLog.id.desc()).first()
    prev_hash = last[0] if last else GENESIS
    row = AuditLog(
        ts=utcnow(),
        actor_type=actor_type,
        operator_id=getattr(signer, "operator_id", None),
        signature_id=getattr(signer, "signature_id", None),
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before=json.loads(json.dumps(before, default=_plain)) if before is not None else None,
        after=json.loads(json.dumps(after, default=_plain)) if after is not None else None,
        prev_hash=prev_hash,
    )
    row.hash = _hash(row, prev_hash)
    db.add(row)
    db.flush()
    return row


def verify_chain(db: Session) -> ChainReport:
    prev = GENESIS
    checked = 0
    for row in db.query(AuditLog).order_by(AuditLog.id).yield_per(500):
        if row.prev_hash != prev or _hash(row, prev) != row.hash:
            return ChainReport(False, checked, row.id)
        prev = row.hash
        checked += 1
    return ChainReport(True, checked, None)
