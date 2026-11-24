"""Eventi -> coda webhook (outbox). Gli eventi nascono solo da azioni manuali degli operatori."""
from collections.abc import Sequence

from sqlalchemy.orm import Session

from ..models import OutboxItem, Webhook
from . import discord

SEVERITY_RANK = {"SEV1": 1, "SEV2": 2, "SEV3": 3, "SEV4": 4}


def _matches(hook: Webhook, event: str, severity: str | None, service_ids: Sequence[int]) -> bool:
    if not hook.enabled or event not in (hook.events or []):
        return False
    if hook.min_severity and severity:
        if SEVERITY_RANK.get(severity, 9) > SEVERITY_RANK.get(hook.min_severity, 9):
            return False
    if hook.service_ids and service_ids:
        if not set(hook.service_ids) & set(service_ids):
            return False
    return True


def matching_hooks(db: Session, event: str, severity: str | None = None, service_ids: Sequence[int] = ()):
    return [h for h in db.query(Webhook).order_by(Webhook.id) if _matches(h, event, severity, service_ids)]


def default_notify(db: Session, event: str, severity: str | None = None, service_ids: Sequence[int] = ()) -> bool:
    """Preimpostazione della casella "Pubblica su Discord"."""
    return bool(matching_hooks(db, event, severity, service_ids))


def payload_for(hook: Webhook, event: str, data: dict, base_url: str, app_name: str) -> dict:
    if hook.kind == "generic":
        return discord.build_generic_payload(event, data, app_name)
    return discord.build_payload(
        event, data, base_url=base_url, app_name=app_name, mention_role_id=hook.mention_role_id or None,
        username=hook.username or None, avatar_url=hook.avatar_url or None,
    )


def emit(db: Session, event: str, data: dict, *, base_url: str, severity: str | None = None,
         service_ids: Sequence[int] = (), notify: bool = True, app_name: str = "MAGAZZINO") -> int:
    if not notify:
        return 0
    hooks = matching_hooks(db, event, severity, service_ids)
    for hook in hooks:
        db.add(OutboxItem(webhook_id=hook.id, event=event, payload=payload_for(hook, event, data, base_url, app_name)))
    db.flush()
    return len(hooks)
