"""PWA: manifest, service worker servito dalla radice (scope /), pagina offline."""
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from ..deps import templates

router = APIRouter()


@router.get("/manifest.webmanifest")
def manifest(request: Request):
    name = request.app.state.settings.app_name
    data = {
        "name": f"{name} – Magazzino e centro di comando",
        "short_name": name,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f4f1e9",
        "theme_color": "#111111",
        "lang": "it",
        "icons": [
            {"src": "/static/pwa/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/pwa/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/pwa/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Nuovo componente", "url": "/components/new"},
            {"name": "Incidenti", "url": "/incidents?status=open"},
        ],
    }
    return JSONResponse(data, media_type="application/manifest+json")


@router.get("/sw.js")
def service_worker():
    return FileResponse("static/pwa/sw.js", media_type="text/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@router.get("/offline")
def offline(request: Request):
    html = templates.get_template("offline.html").render(APP_NAME=request.app.state.settings.app_name)
    return HTMLResponse(html)
