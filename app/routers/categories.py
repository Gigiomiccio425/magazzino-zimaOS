"""Categorie e campi tipizzati. La chiave di un campo e' fissata alla creazione (dati esistenti al sicuro)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import FIELD_TYPES, Category, CategoryField, Component
from ..services import audit
from ..services.signing import SignerInfo, require_signer

router = APIRouter()
FIELDS = ["label", "type", "unit", "choices", "sort_order", "filterable", "active"]


def _refuse(request: Request, status: int, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _choices(text: str) -> list[str]:
    seen = {}
    for part in (text or "").split(","):
        part = " ".join(part.split())
        if part:
            seen[part] = True
    return list(seen)


@router.get("/categories")
def categories(request: Request, db: Session = Depends(get_db)):
    counts = dict(db.query(Component.category, func.count(Component.id))
                  .filter(Component.deleted_at.is_(None)).group_by(Component.category).all())
    cats = db.query(Category).order_by(Category.name).all()
    return render(request, "categories.html", {"categories": cats, "counts": counts})


@router.post("/categories/{cat_id}/life")
async def category_life(cat_id: int, request: Request, db: Session = Depends(get_db),
                        signer: SignerInfo = Depends(require_signer())):
    form = await request.form()
    cat = db.get(Category, cat_id)
    raw = str(form.get("months") or "").strip()
    if cat is None or (raw and not (raw.isdigit() and 1 <= int(raw) <= 240)):
        flash(request, "Vita utile non valida (da 1 a 240 mesi).", "error")
        return redirect(request, "/categories")
    before = cat.useful_life_months
    cat.useful_life_months = int(raw) if raw else None
    audit.record(db, entity_type="category", entity_id=cat.id, action="update",
                 before={"useful_life_months": before}, after={"useful_life_months": cat.useful_life_months},
                 signer=signer)
    db.commit()
    flash(request, f"{cat.name}: vita utile {cat.useful_life_months or 'predefinita'} mesi.")
    return redirect(request, "/categories")


@router.get("/categories/{cat_id}/fields")
def category_fields(cat_id: int, request: Request, db: Session = Depends(get_db)):
    cat = db.get(Category, cat_id)
    if not cat:
        flash(request, "Categoria non trovata.", "error")
        return redirect(request, "/categories")
    fields = db.query(CategoryField).filter_by(category_id=cat.id).order_by(CategoryField.sort_order).all()
    return render(request, "category_fields.html", {"cat": cat, "fields": fields, "TYPES": FIELD_TYPES})


@router.post("/categories/{cat_id}/fields")
def field_add(cat_id: int, request: Request, label: str = Form(""), type: str = Form("text"),
              unit: str = Form(""), choices: str = Form(""), db: Session = Depends(get_db),
              signer: SignerInfo = Depends(require_signer())):
    back = f"/categories/{cat_id}/fields"
    cat = db.get(Category, cat_id)
    if not cat:
        return _refuse(request, 404, "Categoria non trovata.", "/categories")
    label = " ".join(label.split())[:80]
    if not label:
        return _refuse(request, 422, "Scrivi il nome del campo.", back)
    if '"' in label:
        return _refuse(request, 422, "Il nome del campo non può contenere virgolette.", back)
    if db.query(CategoryField).filter_by(category_id=cat.id, key=label).first():
        return _refuse(request, 409, "Esiste già un campo con questo nome.", back)
    ftype = type if type in FIELD_TYPES else "text"
    order = (db.query(func.max(CategoryField.sort_order)).filter_by(category_id=cat.id).scalar() or 0) + 1
    f = CategoryField(category_id=cat.id, key=label, label=label, type=ftype, unit=unit.strip()[:20],
                      choices=_choices(choices) if ftype == "choice" else [], sort_order=order,
                      filterable=True, active=True, required=False)
    db.add(f)
    db.flush()
    audit.record(db, entity_type="category_field", entity_id=f.id, action="create",
                 after={"category": cat.name, **audit.snapshot(f, ["key"] + FIELDS)}, signer=signer)
    db.commit()
    flash(request, f"Campo \"{label}\" aggiunto a {cat.name}.")
    return redirect(request, back)


@router.post("/categories/fields/{field_id}/edit")
def field_edit(field_id: int, request: Request, label: str = Form(""), unit: str = Form(""),
               choices: str = Form(""), sort_order: str = Form("0"), filterable: str = Form(""),
               active: str = Form(""), db: Session = Depends(get_db),
               signer: SignerInfo = Depends(require_signer())):
    f = db.get(CategoryField, field_id)
    if not f:
        return _refuse(request, 404, "Campo non trovato.", "/categories")
    back = f"/categories/{f.category_id}/fields"
    label = " ".join(label.split())[:80]
    if not label or '"' in label:
        return _refuse(request, 422, "Nome del campo non valido.", back)
    before = audit.snapshot(f, FIELDS)
    f.label = label  # la chiave (f.key) non cambia mai
    f.unit = unit.strip()[:20]
    if f.type == "choice":
        f.choices = _choices(choices)
    f.sort_order = int(sort_order) if sort_order.strip().lstrip("-").isdigit() else f.sort_order
    f.filterable = filterable == "1"
    f.active = active == "1"
    b, a = audit.changed(before, audit.snapshot(f, FIELDS))
    if a or b:
        audit.record(db, entity_type="category_field", entity_id=f.id, action="update", before=b, after=a,
                     signer=signer)
    db.commit()
    flash(request, "Campo aggiornato.")
    return redirect(request, back)
