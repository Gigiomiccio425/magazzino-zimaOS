"""Zona stampa: coda di etichette (più pezzi insieme), anteprima A4 e fogli da stampare.

La coda non è un dato di magazzino: modificarla non richiede firma (resta la protezione CSRF).
"""
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, redirect, render
from ..models import PrintItem
from ..services import printing
from ..services.qr import qr_svg, tag_url
from ..services.settings_store import base_url
from ..services.signing import session_signer

router = APIRouter()


def _options(params) -> dict:
    sheet = params.get("sheet") if params.get("sheet") in printing.FORMATS else None
    start = params.get("start") or "1"
    return {
        "sheet": sheet,
        "diam": printing.clamp_diameter(params.get("diam")),
        "start": max(1, int(start)) if str(start).isdigit() else 1,
        "cuts": params.get("cuts", "1") != "0",
    }


def _query(opts: dict, **changes) -> str:
    data = {**opts, **changes}
    return urlencode({"sheet": data["sheet"] or "", "diam": data["diam"], "start": data["start"],
                      "cuts": "1" if data["cuts"] else "0"})


def _back(form, default: str = "/print") -> str:
    target = str(form.get("next") or default)
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return default
    return target


def _with_qr(request: Request, db: Session, sheet: printing.Sheet) -> list[list[dict | None]]:
    base = base_url(request, db)
    cache: dict[str, str] = {}
    pages = []
    for page in sheet.pages:
        slots = []
        for i, e in enumerate(page):
            if e is not None and e.tag not in cache:
                cache[e.tag] = qr_svg(tag_url(base, e.tag), scale=4)
            slots.append({"entry": e, "svg": cache.get(e.tag) if e else None, "style": sheet.slot_style(i)})
        pages.append(slots)
    return pages


@router.get("/print")
def print_page(request: Request, db: Session = Depends(get_db)):
    opts = _options(request.query_params)
    entries = printing.queue_entries(db)
    counts = printing.page_counts(entries, opts["diam"], opts["start"])
    if opts["sheet"] is None:  # primo formato con qualcosa da stampare
        opts["sheet"] = next((f for f in printing.FORMATS if counts[f][0]), "label")
    sheet = printing.layout(entries, opts["sheet"], opts["diam"], opts["start"])
    pages = _with_qr(request, db, sheet)
    return render(request, "print.html", {
        "entries": entries, "counts": counts, "opts": opts, "sheet": sheet, "preview": pages[0] if pages else None,
        "FORMATS": printing.FORMATS, "SHEET_NAMES": printing.SHEET_NAMES,
        "total_copies": sum(e.copies for e in entries), "total_pages": sum(p for _, p in counts.values()),
        "query": _query(opts), "query_for": lambda **kw: _query(opts, **kw),
        "self_url": f"/print?{_query(opts)}",
    })


@router.get("/print/sheets")
def print_sheets(request: Request, db: Session = Depends(get_db)):
    """Documento da stampare: un foglio A4 per pagina, misure reali in millimetri."""
    opts = _options(request.query_params)
    entries = printing.queue_entries(db)
    formats = [opts["sheet"]] if opts["sheet"] else list(printing.FORMATS)
    sheets = []
    for fmt in formats:
        sheet = printing.layout(entries, fmt, opts["diam"], opts["start"])
        if sheet.pages:
            sheets.append({"sheet": sheet, "pages": _with_qr(request, db, sheet), "name": printing.SHEET_NAMES[fmt]})
    return render(request, "print_sheets.html", {"sheets": sheets, "opts": opts,
                                                 "back": f"/print?{_query(opts)}"})


@router.post("/print/add")
async def print_add(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    raw = form.getlist("ids") or str(form.get("id") or "").split(",")
    ids = [int(i) for i in raw if str(i).strip().isdigit()]
    signer = session_signer(request)
    n = printing.add_to_queue(db, str(form.get("entity_type") or "component"), ids,
                              form.get("format") or None, signer["name"] if signer else None)
    db.commit()
    if n:
        flash(request, f"{n} {'elemento aggiunto' if n == 1 else 'elementi aggiunti'} alla stampa.")
    else:
        flash(request, "Niente da aggiungere: elementi non trovati o coda piena.", "error")
    return redirect(request, _back(form, "/print"))


@router.post("/print/item/{item_id}")
async def print_item_update(item_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    item = db.get(PrintItem, item_id)
    if item is not None:
        if form.get("format") in printing.FORMATS:
            item.format = form.get("format")
        copies = str(form.get("copies") or "")
        if copies.lstrip("-").isdigit():
            item.copies = max(1, min(printing.MAX_COPIES, int(copies)))
        db.commit()
    return redirect(request, _back(form))


@router.post("/print/item/{item_id}/remove")
async def print_item_remove(item_id: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    item = db.get(PrintItem, item_id)
    if item is not None:
        db.delete(item)
        db.commit()
    return redirect(request, _back(form))


@router.post("/print/all")
async def print_all_format(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    fmt = form.get("format")
    if fmt in printing.FORMATS:
        db.query(PrintItem).update({PrintItem.format: fmt})
        db.commit()
    return redirect(request, _back(form))


@router.post("/print/clear")
async def print_clear(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    n = db.query(PrintItem).delete()
    db.commit()
    flash(request, f"Coda svuotata ({n} elementi).")
    return redirect(request, _back(form))
