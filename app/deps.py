"""Utility condivise: templates, render con flash, redirect compatibili con fetch."""
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .models import STATUSES
from .timeutil import to_local, utcnow
from .version import APP_VERSION

templates = Jinja2Templates(directory="templates")


def _fmt_dt(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return to_local(value).strftime("%d/%m/%Y %H:%M")


templates.env.globals["STATUSES"] = STATUSES
templates.env.globals["APP_VERSION"] = APP_VERSION
templates.env.globals["current_year"] = utcnow().year
templates.env.filters["dt"] = _fmt_dt


def flash(request: Request, message: str, category: str = "success"):
    """Messaggio flash in sessione, mostrato al prossimo render."""
    msgs = request.session.get("flashes", [])
    msgs.append({"message": message, "category": category})
    request.session["flashes"] = msgs


def render(request: Request, template_name: str, context: dict | None = None, status_code: int = 200):
    ctx = dict(context or {})
    ctx["APP_NAME"] = request.app.state.settings.app_name
    ctx["flashes"] = request.session.pop("flashes", [])
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


def is_fetch(request: Request) -> bool:
    return request.headers.get("x-requested-with", "").lower() == "fetch"


def redirect(request: Request, url: str) -> Response:
    """303 per i form classici, JSON con chiave redirect per le richieste fetch."""
    if is_fetch(request):
        return JSONResponse({"redirect": url})
    return RedirectResponse(url=url, status_code=303)
