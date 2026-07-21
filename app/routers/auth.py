"""Login / logout con password unica."""
import hmac

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import config
from ..deps import flash, render

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    if request.session.get("auth"):
        return RedirectResponse(url="/", status_code=303)
    return render(request, "login.html")


@router.post("/login")
def login_submit(request: Request, password: str = Form("")):
    # compare_digest evita timing attack sul confronto password
    if hmac.compare_digest(password, config.APP_PASSWORD):
        request.session["auth"] = True
        flash(request, "Accesso effettuato.")
        return RedirectResponse(url="/", status_code=303)
    flash(request, "Password errata.", "error")
    return RedirectResponse(url="/login", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
