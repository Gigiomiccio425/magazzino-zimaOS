"""Consegna webhook dalla coda: tentativi con attesa crescente, rispetto del rate limit (429)."""
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from ..models import OutboxItem
from ..timeutil import utcnow

BACKOFF_SECONDS = (10, 30, 60, 300, 900, 1800, 3600, 7200)
BATCH = 20
RETENTION_DAYS = 30


def _retry_after(resp: httpx.Response) -> float:
    try:
        value = resp.json().get("retry_after")
    except (ValueError, AttributeError):
        value = None
    if value is None:
        value = resp.headers.get("retry-after", 5)
    try:
        return max(float(value), 0.5)
    except (TypeError, ValueError):
        return 5.0


def _fail(item: OutboxItem, now: datetime, error: str) -> None:
    item.attempts = (item.attempts or 0) + 1
    item.last_error = error[:500]
    if item.attempts >= len(BACKOFF_SECONDS):
        item.status = "dead"
    else:
        item.status = "pending"
        item.next_attempt_at = now + timedelta(seconds=BACKOFF_SECONDS[item.attempts - 1])


async def deliver_one(db: Session, item: OutboxItem, client: httpx.AsyncClient, now: datetime) -> None:
    try:
        resp = await client.post(item.webhook.url, json=item.payload, timeout=10)
    except httpx.HTTPError as exc:
        _fail(item, now, f"Errore di rete: {exc}")
        return
    if 200 <= resp.status_code < 300:
        item.status, item.sent_at, item.last_error = "sent", now, ""
    elif resp.status_code == 429:
        item.status = "pending"
        item.next_attempt_at = now + timedelta(seconds=_retry_after(resp))
        item.last_error = "HTTP 429 (limite di invio)"
    elif 400 <= resp.status_code < 500:
        item.status, item.last_error = "dead", f"HTTP {resp.status_code}: {resp.text[:300]}"
    else:
        _fail(item, now, f"HTTP {resp.status_code}")


async def deliver_due(engine, client: httpx.AsyncClient, now: datetime | None = None) -> int:
    now = now or utcnow()
    with Session(bind=engine, expire_on_commit=False) as db:
        items = (
            db.query(OutboxItem)
            .filter(OutboxItem.status == "pending", OutboxItem.next_attempt_at <= now)
            .order_by(OutboxItem.id).limit(BATCH).all()
        )
        for item in items:
            await deliver_one(db, item, client, now)
            db.commit()
        return len(items)


def purge_old(engine, now: datetime | None = None) -> int:
    """Pulisce solo il registro invii gia' consegnati (non dati utente)."""
    cutoff = (now or utcnow()) - timedelta(days=RETENTION_DAYS)
    with Session(bind=engine) as db:
        n = db.query(OutboxItem).filter(OutboxItem.status == "sent", OutboxItem.sent_at < cutoff).delete()
        db.commit()
        return n
