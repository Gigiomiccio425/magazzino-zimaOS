"""Login applicativo rimosso in v2: l'accesso e' protetto dal login Umbrel."""
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter()


@router.get("/login")
def login_page():
    return RedirectResponse(url="/", status_code=303)


@router.get("/logout")
def logout():
    return RedirectResponse(url="/", status_code=303)
