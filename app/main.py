"""Entry point FastAPI: factory, lifespan, middleware, routing."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .config import load_settings
from .database import Base, make_engine
from .models import Category
from .routers import auth, components, dashboard, machines

DEFAULT_CATEGORIES = [
    "RAM", "SSD", "HDD", "CPU", "GPU", "Scheda madre", "Alimentatore",
    "Case", "Ventola", "Cavo", "Scheda di rete", "Periferica", "Altro",
]


def create_app(data_dir: str | Path | None = None, *, start_worker: bool = True) -> FastAPI:
    settings = load_settings(data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.db_path)
        app.state.engine = engine
        Base.metadata.create_all(bind=engine)
        with Session(bind=engine) as db:
            if db.query(Category).count() == 0:
                db.add_all(Category(name=n) for n in DEFAULT_CATEGORIES)
                db.commit()
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
