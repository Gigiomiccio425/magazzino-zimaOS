"""Protezione CSRF: token per sessione, verificato su ogni metodo non sicuro."""
import hmac
import secrets

from fastapi import Request

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
FIELD = "csrf_token"
HEADER = "x-csrf-token"


class CSRFError(Exception):
    """Token CSRF mancante o errato."""


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Dipendenza applicata a tutti i router: header X-CSRF-Token o campo csrf_token."""
    if request.method in SAFE_METHODS:
        return
    expected = request.session.get("csrf")
    sent = request.headers.get(HEADER)
    if not sent:
        content_type = request.headers.get("content-type", "")
        if "form" in content_type:
            sent = (await request.form()).get(FIELD)
    if not expected or not sent or not hmac.compare_digest(str(sent), expected):
        raise CSRFError()
