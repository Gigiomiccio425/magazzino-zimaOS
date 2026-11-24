"""Utility condivise: templates, render con flash, redirect compatibili con fetch."""
import hashlib
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup

from .core.csrf import get_csrf_token
from .models import STATUSES
from .services.markdown import render_markdown
from .services.signing import session_signer
from .timeutil import to_local, utcnow
from .version import APP_VERSION

templates = Jinja2Templates(directory="templates")


def _fmt_dt(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return to_local(value).strftime("%d/%m/%Y %H:%M")


@pass_context
def _csrf_field(ctx) -> Markup:
    token = get_csrf_token(ctx["request"])
    return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')


@pass_context
def _csrf_token(ctx) -> str:
    return get_csrf_token(ctx["request"])


_ASSET_HASHES: dict[str, str] = {}


def _asset(path: str) -> str:
    """URL di un file statico con l'impronta del contenuto: dopo un aggiornamento il browser
    scarica subito CSS e JS nuovi invece di usare la copia in cache."""
    if path not in _ASSET_HASHES:
        try:
            _ASSET_HASHES[path] = hashlib.sha256((Path("static") / path).read_bytes()).hexdigest()[:10]
        except OSError:
            _ASSET_HASHES[path] = APP_VERSION
    return f"/static/{path}?v={_ASSET_HASHES[path]}"


def _nav_current(path: str, match: str) -> bool:
    return path == "/" if match == "/" else path.startswith(match)


templates.env.globals["csrf_field"] = _csrf_field
templates.env.globals["csrf_token"] = _csrf_token
templates.env.globals["nav_current"] = _nav_current
templates.env.globals["asset"] = _asset
templates.env.globals["STATUSES"] = STATUSES
templates.env.globals["APP_VERSION"] = APP_VERSION
templates.env.globals["current_year"] = utcnow().year
templates.env.globals["today"] = lambda: to_local(utcnow()).strftime("%d/%m/%Y")
templates.env.filters["dt"] = _fmt_dt
templates.env.filters["md"] = render_markdown


def flash(request: Request, message: str, category: str = "success"):
    """Messaggio flash in sessione, mostrato al prossimo render."""
    msgs = request.session.get("flashes", [])
    msgs.append({"message": message, "category": category})
    request.session["flashes"] = msgs


def _print_count(request: Request) -> int:
    """Etichette in coda di stampa, per il contatore nel menu."""
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        return 0
    try:
        with engine.connect() as conn:
            return int(conn.exec_driver_sql("SELECT COALESCE(SUM(copies), 0) FROM print_queue").scalar() or 0)
    except Exception:  # tabella non ancora creata o DB occupato: il menu non deve rompere la pagina
        return 0


def render(request: Request, template_name: str, context: dict | None = None, status_code: int = 200):
    ctx = dict(context or {})
    ctx["APP_NAME"] = request.app.state.settings.app_name
    ctx["flashes"] = request.session.pop("flashes", [])
    ctx["signer"] = session_signer(request)
    ctx.setdefault("print_count", _print_count(request))
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)


def is_fetch(request: Request) -> bool:
    return request.headers.get("x-requested-with", "").lower() == "fetch"


def redirect(request: Request, url: str) -> Response:
    """303 per i form classici, JSON con chiave redirect per le richieste fetch."""
    if is_fetch(request):
        return JSONResponse({"redirect": url})
    return RedirectResponse(url=url, status_code=303)
