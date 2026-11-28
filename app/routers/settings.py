"""Pagina impostazioni (salvataggio = azione critica firmata)."""
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..services import audit
from ..services.settings_store import DEFAULTS, get_setting, set_setting
from ..services.signing import SignerInfo, require_signer

router = APIRouter()


def _validate(window: str, audit_days: str, base: str, icecat: str = "") -> tuple[dict, str | None]:
    try:
        w, a = int(window), int(audit_days)
    except ValueError:
        return {}, "Inserisci numeri interi."
    if not 0 <= w <= 60:
        return {}, "La finestra di firma va da 0 a 60 minuti."
    if not 1 <= a <= 3650:
        return {}, "L'intervallo di inventario va da 1 a 3650 giorni."
    base = base.strip().rstrip("/")
    if base:
        u = urlparse(base)
        if u.scheme not in ("http", "https") or not u.netloc:
            return {}, "L'URL pubblico deve iniziare con http:// o https://."
    icecat = icecat.strip()[:80]
    if icecat and not icecat.replace("_", "").replace("-", "").replace(".", "").replace("@", "").isalnum():
        return {}, "Il nome utente Icecat contiene caratteri non validi."
    return {"signature_window_min": w, "audit_interval_days": a, "public_base_url": base, "icecat_username": icecat}, None


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    values = {k: get_setting(db, k) for k in DEFAULTS}
    return render(request, "settings.html", {"values": values})


@router.post("/settings")
def settings_save(request: Request, signature_window_min: str = Form("10"), audit_interval_days: str = Form("180"),
                  public_base_url: str = Form(""), icecat_username: str = Form(""), db: Session = Depends(get_db),
                  signer: SignerInfo = Depends(require_signer(critical=True))):
    values, error = _validate(signature_window_min, audit_interval_days, public_base_url, icecat_username)
    if error:
        if is_fetch(request):
            return JSONResponse({"error": "invalid", "message": error}, status_code=422)
        flash(request, error, "error")
        return redirect(request, "/settings")
    before = {k: get_setting(db, k) for k in DEFAULTS}
    for k, v in values.items():
        set_setting(db, k, v)
    b, a = audit.changed(before, values)
    if a or b:
        audit.record(db, entity_type="settings", entity_id=None, action="update", before=b, after=a, signer=signer)
    db.commit()
    flash(request, "Impostazioni salvate.")
    return redirect(request, "/settings")
