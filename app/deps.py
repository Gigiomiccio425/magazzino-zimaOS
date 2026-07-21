"""Utility condivise: templates, render con flash, helper sessione."""
from datetime import datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import config
from .models import STATUSES

templates = Jinja2Templates(directory="templates")


def _fmt_dt(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return value.strftime("%d/%m/%Y %H:%M")


# Variabili/funzioni disponibili in tutti i template
templates.env.globals["APP_NAME"] = config.APP_NAME
templates.env.globals["STATUSES"] = STATUSES
templates.env.globals["current_year"] = datetime.utcnow().year
templates.env.filters["dt"] = _fmt_dt


def flash(request: Request, message: str, category: str = "success"):
    """Aggiunge un messaggio flash alla sessione (mostrato al prossimo render)."""
    msgs = request.session.get("flashes", [])
    msgs.append({"message": message, "category": category})
    request.session["flashes"] = msgs


def render(request: Request, template_name: str, context: dict | None = None):
    """Render template con iniezione automatica di request + flash."""
    ctx = dict(context or {})
    ctx["request"] = request
    ctx["flashes"] = request.session.pop("flashes", [])
    return templates.TemplateResponse(template_name, ctx)


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("auth"))
