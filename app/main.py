"""Entry point FastAPI: middleware auth, static, startup, routing."""
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import config
from .database import Base, SessionLocal, engine
from .models import Category
from .routers import auth, components, dashboard, machines

app = FastAPI(title="Magazzino Hardware", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Percorsi accessibili senza login
PUBLIC_PREFIXES = ("/login", "/static", "/health", "/favicon.ico")

DEFAULT_CATEGORIES = [
    "RAM", "SSD", "HDD", "CPU", "GPU", "Scheda madre", "Alimentatore",
    "Case", "Ventola", "Cavo", "Scheda di rete", "Periferica", "Altro",
]


# NB ordine middleware: require_login registrato PRIMA, SessionMiddleware DOPO.
# Starlette rende outermost l'ultimo aggiunto -> Session gira per prima e popola
# request.session, poi require_login puo leggerla senza errori.
@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if not any(path.startswith(p) for p in PUBLIC_PREFIXES) and not request.session.get("auth"):
        return RedirectResponse(url="/login", status_code=303)
    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key=config.get_secret_key(),
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    # Seed categorie predefinite (solo se tabella vuota)
    db = SessionLocal()
    try:
        if db.query(Category).count() == 0:
            for name in DEFAULT_CATEGORIES:
                db.add(Category(name=name))
            db.commit()
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(components.router)
app.include_router(machines.router)
