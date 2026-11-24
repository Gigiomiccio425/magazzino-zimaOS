"""Entry point FastAPI: factory, lifespan, middleware, routing."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import load_settings
from .database import make_engine
from .migrations.runner import run_migrations
from .routers import auth, components, dashboard, machines

log = logging.getLogger("magazzino")


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
            engine.dispose()

    app = FastAPI(title="Magazzino Hardware", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=60 * 60 * 24 * 30,
        same_site="lax",
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(components.router)
    app.include_router(machines.router)
    return app
