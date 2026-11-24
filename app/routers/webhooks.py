"""Configurazione webhook (Discord o JSON generico), invio di prova, registro invii."""
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import EVENTS, SEVERITIES, OutboxItem, Webhook
from ..services import audit, discord, events, outbox
from ..services.settings_store import base_url
from ..services.signing import SignerInfo, require_signer
from ..timeutil import utcnow

router = APIRouter()
FIELDS = ["name", "kind", "url", "enabled", "events", "min_severity", "service_ids", "mention_role_id",
          "username", "avatar_url"]


def _parse(form) -> tuple[dict, str | None]:
    kind = form.get("kind") if form.get("kind") in ("discord", "generic") else "discord"
    url = (form.get("url") or "").strip()
    name = (form.get("name") or "").strip()
    chosen = [e for e in form.getlist("events") if e in EVENTS]
    severity = form.get("min_severity") if form.get("min_severity") in SEVERITIES else None
    services = [int(s) for s in form.getlist("service_ids") if str(s).isdigit()] or None
    role = (form.get("mention_role_id") or "").strip()
    avatar = (form.get("avatar_url") or "").strip()
    if not name:
        return {}, "Dai un nome al webhook."
    if kind == "discord" and not discord.is_valid_discord_url(url):
        return {}, "URL Discord non valido: deve iniziare con https://discord.com/api/webhooks/"
    if kind == "generic" and urlparse(url).scheme not in ("http", "https"):
        return {}, "L'URL deve iniziare con http:// o https://"
    if role and not role.isdigit():
        return {}, "L'ID del ruolo Discord è un numero."
    if avatar and urlparse(avatar).scheme != "https":
        return {}, "L'avatar deve essere un URL https://"
    if not chosen:
        return {}, "Scegli almeno un evento."
    return {
        "name": name[:120], "kind": kind, "url": url, "enabled": form.get("enabled") == "1", "events": chosen,
        "min_severity": severity, "service_ids": services, "mention_role_id": role,
        "username": (form.get("username") or "").strip()[:80], "avatar_url": avatar,
    }, None


def _invalid(request: Request, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=422)
    flash(request, message, "error")
    return redirect(request, back)


def _safe_snapshot(hook: Webhook) -> dict:
    snap = audit.snapshot(hook, FIELDS)
    snap["url"] = discord.mask_url(hook.url)
    return snap


def _form_ctx(hook):
    return {"hook": hook, "EVENTS": EVENTS, "SEVERITIES": SEVERITIES}


@router.get("/webhooks")
def webhooks_list(request: Request, db: Session = Depends(get_db)):
    hooks = db.query(Webhook).order_by(Webhook.name).all()
    return render(request, "webhooks_list.html", {"hooks": hooks, "mask": discord.mask_url, "EVENTS": EVENTS})


@router.get("/webhooks/new")
def webhook_new(request: Request):
    return render(request, "webhook_form.html", _form_ctx(None))


@router.post("/webhooks/new")
async def webhook_create(request: Request, db: Session = Depends(get_db),
                         signer: SignerInfo = Depends(require_signer(critical=True))):
    data, error = _parse(await request.form())
    if error:
        return _invalid(request, error, "/webhooks/new")
    hook = Webhook(**data)
    db.add(hook)
    db.flush()
    audit.record(db, entity_type="webhook", entity_id=hook.id, action="create", after=_safe_snapshot(hook), signer=signer)
    db.commit()
    flash(request, f"Webhook \"{hook.name}\" creato. Usa \"Invia test\" per provarlo.")
    return redirect(request, "/webhooks")


@router.get("/webhooks/log")
def webhooks_log(request: Request, db: Session = Depends(get_db)):
    items = db.query(OutboxItem).order_by(OutboxItem.id.desc()).limit(200).all()
    return render(request, "webhooks_log.html", {"items": items, "EVENTS": EVENTS})


@router.get("/webhooks/{hook_id}/edit")
def webhook_edit(hook_id: int, request: Request, db: Session = Depends(get_db)):
    hook = db.get(Webhook, hook_id)
    if not hook:
        flash(request, "Webhook non trovato.", "error")
        return redirect(request, "/webhooks")
    return render(request, "webhook_form.html", _form_ctx(hook))


@router.post("/webhooks/{hook_id}/edit")
async def webhook_update(hook_id: int, request: Request, db: Session = Depends(get_db),
                         signer: SignerInfo = Depends(require_signer(critical=True))):
    hook = db.get(Webhook, hook_id)
    if not hook:
        return _invalid(request, "Webhook non trovato.", "/webhooks")
    data, error = _parse(await request.form())
    if error:
        return _invalid(request, error, f"/webhooks/{hook_id}/edit")
    before = _safe_snapshot(hook)
    for k, v in data.items():
        setattr(hook, k, v)
    b, a = audit.changed(before, _safe_snapshot(hook))
    if a or b:
        audit.record(db, entity_type="webhook", entity_id=hook.id, action="update", before=b, after=a, signer=signer)
    db.commit()
    flash(request, "Webhook aggiornato.")
    return redirect(request, "/webhooks")


@router.post("/webhooks/{hook_id}/delete")
def webhook_delete(hook_id: int, request: Request, db: Session = Depends(get_db),
                   signer: SignerInfo = Depends(require_signer(critical=True))):
    hook = db.get(Webhook, hook_id)
    if hook:
        audit.record(db, entity_type="webhook", entity_id=hook.id, action="delete", before=_safe_snapshot(hook),
                     signer=signer)
        db.query(OutboxItem).filter(OutboxItem.webhook_id == hook.id).delete()
        db.delete(hook)
        db.commit()
        flash(request, "Webhook eliminato.")
    return redirect(request, "/webhooks")


@router.post("/webhooks/{hook_id}/test")
async def webhook_test(hook_id: int, request: Request, db: Session = Depends(get_db),
                       signer: SignerInfo = Depends(require_signer())):
    hook = db.get(Webhook, hook_id)
    if not hook:
        return _invalid(request, "Webhook non trovato.", "/webhooks")
    data = {"title": "Messaggio di prova", "description": f"Webhook \"{hook.name}\" configurato correttamente.",
            "url_path": "/webhooks", "fields": [], "operator": signer.operator_name}
    app_name = request.app.state.settings.app_name
    item = OutboxItem(webhook_id=hook.id, event="webhook.test",
                      payload=events.payload_for(hook, "webhook.test", data, base_url(request, db), app_name))
    db.add(item)
    db.commit()  # nessun lock di scrittura tenuto durante la chiamata HTTP
    await outbox.deliver_one(db, item, request.app.state.http, utcnow())
    db.commit()
    if item.status == "sent":
        flash(request, "Messaggio di prova inviato.")
    else:
        flash(request, f"Invio non riuscito: {item.last_error or 'riprovo più tardi'}", "error")
    return redirect(request, "/webhooks")
