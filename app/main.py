"""Entry point FastAPI: factory, lifespan, middleware, routing."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import load_settings
from .core.csrf import CSRFError, verify_csrf
from .core.headers import SecurityHeadersMiddleware
from .database import make_engine
from .deps import flash, is_fetch
from .migrations.runner import run_migrations
from .routers import attachments, audit_log, audits, auth, backups, categories, components, components_bulk, dashboard, locations, machines, qr, operators, projects, services, settings, sign, tests_log, trash, webhooks
from .services.signing import SignatureRequired
from .worker import Worker

log = logging.getLogger("magazzino")

ROUTERS = [auth, dashboard, attachments, components_bulk, components, categories, qr, locations, machines, audit_log, sign, operators, trash, settings, backups, webhooks, tests_log, audits, projects, services]


async def _csrf_error(request: Request, _exc: CSRFError):
    if is_fetch(request):
        return JSONResponse({"error": "csrf"}, status_code=403)
    return PlainTextResponse("Richiesta non valida (token CSRF). Ricarica la pagina e riprova.", status_code=403)


async def _signature_required(request: Request, exc: SignatureRequired):
    if is_fetch(request):
        return JSONResponse({"error": "signature_required", "critical": exc.critical}, status_code=428)
    flash(request, "Firma richiesta: abilita JavaScript e riprova.", "error")
    referer = urlparse(request.headers.get("referer", ""))
    back = referer.path if referer.path and referer.netloc in ("", request.url.netloc) else "/"
    if referer.query:
        back += "?" + referer.query
    return RedirectResponse(url=back, status_code=303)


def create_app(data_dir: str | Path | None = None, *, start_worker: bool = True) -> FastAPI:
    settings = load_settings(data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        report = run_migrations(settings.db_path, settings.backups_dir)
        if report.from_version != report.to_version:
            log.info("Schema DB: v%s -> v%s (backup: %s)", report.from_version, report.to_version, report.backup_path)
        app.state.engine = make_engine(settings.db_path)
        app.state.http = httpx.AsyncClient(timeout=10)
        stop = asyncio.Event()
        task = asyncio.create_task(Worker(app).run(stop)) if start_worker else None
        try:
            yield
        finally:
            stop.set()
            if task:
                await task
            await app.state.http.aclose()
            app.state.engine.dispose()

    app = FastAPI(
        title="Magazzino Hardware",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        exception_handlers={CSRFError: _csrf_error, SignatureRequired: _signature_required},
    )
    app.state.settings = settings
    app.state.start_worker = start_worker
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=60 * 60 * 24 * 30,
        same_site="lax",
    )
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    for module in ROUTERS:
        app.include_router(module.router, dependencies=[Depends(verify_csrf)])
    return app
