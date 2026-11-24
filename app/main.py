"""Entry point FastAPI: factory, lifespan, middleware, routing."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import load_settings
from .core.csrf import CSRFError, verify_csrf
from .core.headers import SecurityHeadersMiddleware
from .database import make_engine
from .deps import is_fetch
from .migrations.runner import run_migrations
from .routers import auth, components, dashboard, machines

log = logging.getLogger("magazzino")

ROUTERS = [auth, dashboard, components, machines]


async def _csrf_error(request: Request, _exc: CSRFError):
    if is_fetch(request):
        return JSONResponse({"error": "csrf"}, status_code=403)
    return PlainTextResponse("Richiesta non valida (token CSRF). Ricarica la pagina e riprova.", status_code=403)


def create_app(data_dir: str | Path | None = None, *, start_worker: bool = True) -> FastAPI:
    settings = load_settings(data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        report = run_migrations(settings.db_path, settings.backups_dir)
        if report.from_version != report.to_version:
            log.info("Schema DB: v%s -> v%s (backup: %s)", report.from_version, report.to_version, report.backup_path)
        engine = make_engine(settings.db_path)
        app.state.engine = engine
        try:
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(
        title="Magazzino Hardware",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        exception_handlers={CSRFError: _csrf_error},
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
