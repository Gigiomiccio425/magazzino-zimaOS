"""Fixture condivise: app isolata su cartella dati temporanea."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def data_dir(tmp_path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def app(data_dir):
    return create_app(data_dir, start_worker=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(client, app):
    from sqlalchemy.orm import Session

    with Session(bind=app.state.engine) as s:
        yield s
