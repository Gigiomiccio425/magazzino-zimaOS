"""Ricerca globale: JSON per la palette Ctrl+K e pagina HTML per chi non usa JavaScript."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import render
from ..services.search import global_search

router = APIRouter()


@router.get("/search.json")
def search_json(q: str = "", db: Session = Depends(get_db)):
    return {"q": q, "groups": [asdict(g) for g in global_search(db, q)]}


@router.get("/search")
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    return render(request, "search.html", {"q": q, "groups": global_search(db, q, limit=25)})
