"""Registro test dei componenti, modelli di test, coda 'da testare'."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import flash, is_fetch, redirect, render
from ..models import STATUSES, STATUS_TO_TEST, TEST_RESULTS, Attachment, Component, TestRun, TestTemplate
from ..services import audit, events
from ..services.component_form import FormError
from ..services.inventory import add_movement
from ..services.settings_store import base_url
from ..services.signing import SignerInfo, require_signer
from ..services.testing import fields_from_form, parse_values, suggest_result
from ..timeutil import utcnow

router = APIRouter()


def _refuse(request: Request, status: int, message: str, back: str):
    if is_fetch(request):
        return JSONResponse({"error": "invalid", "message": message}, status_code=status)
    flash(request, message, "error")
    return redirect(request, back)


def _alive(db: Session, comp_id: int) -> Component | None:
    c = db.get(Component, comp_id)
    return c if c and c.deleted_at is None else None


def _templates(db: Session):
    return db.query(TestTemplate).filter(TestTemplate.active.is_(True)).order_by(TestTemplate.category,
                                                                                  TestTemplate.name).all()


@router.get("/tests/queue")
def tests_queue(request: Request, db: Session = Depends(get_db)):
    items = (db.query(Component).filter(Component.deleted_at.is_(None), Component.status == STATUS_TO_TEST)
             .order_by(Component.updated_at).all())
    recent = db.query(TestRun).order_by(TestRun.id.desc()).limit(20).all()
    return render(request, "test_queue.html", {"items": items, "recent": recent, "RESULTS": TEST_RESULTS})


@router.get("/tests/templates")
def templates_list(request: Request, db: Session = Depends(get_db)):
    return render(request, "test_templates.html", {"templates": db.query(TestTemplate).order_by(
        TestTemplate.category, TestTemplate.name).all()})


def _template_form(request: Request, tpl: TestTemplate | None):
    return render(request, "test_template_form.html", {"tpl": tpl})


@router.get("/tests/templates/new")
def template_new(request: Request):
    return _template_form(request, None)


@router.get("/tests/templates/{tpl_id}/edit")
def template_edit(tpl_id: int, request: Request, db: Session = Depends(get_db)):
    tpl = db.get(TestTemplate, tpl_id)
    if not tpl:
        flash(request, "Modello non trovato.", "error")
        return redirect(request, "/tests/templates")
    return _template_form(request, tpl)


async def _save_template(request: Request, db: Session, tpl: TestTemplate | None, signer):
    form = await request.form()
    name = " ".join((form.get("name") or "").split())[:160]
    back = f"/tests/templates/{tpl.id}/edit" if tpl else "/tests/templates/new"
    if not name:
        return _refuse(request, 422, "Dai un nome al modello.", back)
    try:
        fields = fields_from_form(form)
    except FormError as exc:
        return _refuse(request, 422, str(exc), back)
    checklist = [line.strip() for line in (form.get("checklist") or "").splitlines() if line.strip()]
    created = tpl is None
    before = None if created else {"name": tpl.name, "fields": tpl.fields, "checklist": tpl.checklist}
    if created:
        tpl = TestTemplate(active=True)
        db.add(tpl)
    tpl.name, tpl.category = name, (form.get("category") or "").strip()[:80]
    tpl.description = (form.get("description") or "").strip()
    tpl.fields, tpl.checklist = fields, checklist
    tpl.active = form.get("active", "1") == "1"
    db.flush()
    audit.record(db, entity_type="test_template", entity_id=tpl.id, action="create" if created else "update",
                 before=before, after={"name": tpl.name, "fields": fields, "checklist": checklist}, signer=signer)
    db.commit()
    flash(request, f"Modello \"{tpl.name}\" salvato.")
    return redirect(request, "/tests/templates")


@router.post("/tests/templates/new")
async def template_create(request: Request, db: Session = Depends(get_db),
                          signer: SignerInfo = Depends(require_signer())):
    return await _save_template(request, db, None, signer)


@router.post("/tests/templates/{tpl_id}/edit")
async def template_update(tpl_id: int, request: Request, db: Session = Depends(get_db),
                          signer: SignerInfo = Depends(require_signer())):
    tpl = db.get(TestTemplate, tpl_id)
    if not tpl:
        return _refuse(request, 404, "Modello non trovato.", "/tests/templates")
    return await _save_template(request, db, tpl, signer)


@router.get("/components/{comp_id}/tests/new")
def test_run_form(comp_id: int, request: Request, template: int | None = None, db: Session = Depends(get_db)):
    comp = _alive(db, comp_id)
    if not comp:
        flash(request, "Componente non trovato.", "error")
        return redirect(request, "/components")
    templates = _templates(db)
    chosen = next((t for t in templates if t.id == template), None) or \
        next((t for t in templates if t.category == comp.category), None)
    return render(request, "test_run_form.html", {
        "c": comp, "templates": templates, "tpl": chosen, "RESULTS": TEST_RESULTS, "STATUSES": STATUSES,
        "notify_default": events.default_notify(db, "test.failed"),
    })


@router.post("/components/{comp_id}/tests/new")
async def test_run_create(comp_id: int, request: Request, db: Session = Depends(get_db),
                          signer: SignerInfo = Depends(require_signer())):
    comp = _alive(db, comp_id)
    back = f"/components/{comp_id}/tests/new"
    if not comp:
        return _refuse(request, 404, "Componente non trovato.", "/components")
    form = await request.form()
    result = form.get("result")
    if result not in TEST_RESULTS:
        return _refuse(request, 422, "Scegli l'esito del test.", back)
    tpl_id = form.get("template_id")
    tpl = db.get(TestTemplate, int(tpl_id)) if str(tpl_id or "").isdigit() else None
    fields = tpl.fields if tpl else []
    try:
        values = parse_values(fields, form)
    except FormError as exc:
        return _refuse(request, 422, str(exc), back)
    checklist = {step: form.get(f"c_{i}") == "1" for i, step in enumerate(tpl.checklist if tpl else [])}
    now = utcnow()
    run = TestRun(component_id=comp.id, template_id=tpl.id if tpl else None, result=result, values=values,
                  checklist=checklist, tool=(form.get("tool") or "").strip()[:160],
                  notes=(form.get("notes") or "").strip(), started_at=now, finished_at=now,
                  operator_id=signer.operator_id, signature_id=signer.signature_id)
    db.add(run)
    comp.last_test_at, comp.last_test_result = now, result
    new_status = form.get("set_status")
    if new_status in STATUSES and new_status != comp.status:
        add_movement(db, comp, signer, "status",
                     note=f"Dopo test: {STATUSES.get(comp.status)} -> {STATUSES[new_status]}")
        comp.status = new_status
    db.flush()
    audit.record(db, entity_type="test_run", entity_id=run.id, action="create",
                 after={"component": comp.id, "result": result, "values": values,
                        "suggested": suggest_result(fields, values)}, signer=signer)
    if result == "fail":
        events.emit(db, "test.failed", {
            "title": f"{comp.name} ({comp.asset_tag})", "description": run.notes or None,
            "url_path": f"/tests/runs/{run.id}",
            "fields": [["Modello di test", tpl.name if tpl else "—"], ["Strumento", run.tool or "—"]],
            "operator": signer.operator_name,
        }, base_url=base_url(request, db), notify=form.get("notify") == "1",
            app_name=request.app.state.settings.app_name)
    db.commit()
    flash(request, f"Test registrato: {TEST_RESULTS[result]}.")
    return redirect(request, f"/tests/runs/{run.id}")


@router.get("/tests/runs/{run_id}")
def test_run_detail(run_id: int, request: Request, db: Session = Depends(get_db)):
    run = db.get(TestRun, run_id)
    if not run:
        flash(request, "Test non trovato.", "error")
        return redirect(request, "/tests/queue")
    fields = {f["key"]: f for f in (run.template.fields if run.template else [])}
    atts = db.query(Attachment).filter_by(entity_type="test_run", entity_id=run.id, deleted_at=None).all()
    return render(request, "test_run_detail.html", {"run": run, "fields": fields, "RESULTS": TEST_RESULTS,
                                                    "attachments": atts})
