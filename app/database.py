"""SQLite + SQLAlchemy: engine per istanza app, sessione per richiesta."""
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, declarative_base

Base = declarative_base()


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def get_db(request: Request) -> Iterator[Session]:
    """Dependency FastAPI: sessione legata all'engine dell'app."""
    with Session(bind=request.app.state.engine, autoflush=False, expire_on_commit=False) as db:
        yield db
