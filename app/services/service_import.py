"""Import una tantum di servizi da file JSON (es. l'elenco delle app di Umbrel).

Regole di sicurezza per i dati esistenti:
- un servizio con lo stesso nome (attivo) non viene toccato, al massimo viene collegato
  alla macchina se non ne ha già una;
- la macchina viene cercata per nome e creata solo se non esiste; una macchina esistente
  non viene modificata;
- niente viene cancellato. Ogni creazione finisce nel registro firmato.
"""
import json
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import MODULE_KINDS, SERVICE_STATUSES, Machine, Service, ServiceModule
from . import audit
from .inventory import MACHINE_FIELDS, make_tag
from .links import is_safe_url

MAX_BYTES = 1_000_000
MAX_SERVICES = 500
MAX_MODULES = 30
SERVICE_FIELDS = ["name", "slug", "machine_id", "description", "url", "status", "runbook_md"]


class ServiceImportError(ValueError):
    """File di import non valido (messaggio per l'utente)."""


@dataclass
class ImportReport:
    machine: Machine | None = None
    machine_created: bool = False
    created: list[str] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _text(value, limit: int | None = None) -> str:
    text = value.strip() if isinstance(value, str) else ""
    return text[:limit] if limit else text


def _name(value) -> str:
    return " ".join(_text(value).split())[:160]


def parse(raw: bytes | str) -> dict:
    if isinstance(raw, bytes):
        if len(raw) > MAX_BYTES:
            raise ServiceImportError("File troppo grande (massimo 1 MB).")
        try:
            raw = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ServiceImportError("Il file deve essere testo UTF-8.") from exc
    if len(raw.encode("utf-8")) > MAX_BYTES:
        raise ServiceImportError("Testo troppo lungo (massimo 1 MB).")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ServiceImportError(f"JSON non valido (riga {exc.lineno}, colonna {exc.colno}).") from exc
    if not isinstance(data, dict) or not isinstance(data.get("services"), list):
        raise ServiceImportError('Il JSON deve avere la forma {"machine": …, "services": [ … ]}.')
    if not data["services"]:
        raise ServiceImportError("L'elenco dei servizi è vuoto.")
    if len(data["services"]) > MAX_SERVICES:
        raise ServiceImportError(f"Troppi servizi (massimo {MAX_SERVICES}).")
    return data


def _machine(db: Session, spec, signer, report: ImportReport) -> Machine | None:
    if spec in (None, ""):
        return None
    spec = {"name": spec} if isinstance(spec, str) else spec
    if not isinstance(spec, dict):
        raise ServiceImportError('"machine" deve essere un nome o un oggetto con "name".')
    name = _name(spec.get("name"))
    if not name:
        raise ServiceImportError('La macchina deve avere un nome ("name").')
    existing = db.query(Machine).filter(func.lower(Machine.name) == name.lower()).first()
    if existing is not None:
        if existing.deleted_at is not None:
            raise ServiceImportError(f'La macchina "{existing.name}" è nel cestino: ripristinala prima dell\'import.')
        return existing
    m = Machine(name=name, kind=_text(spec.get("kind"), 60), location=_text(spec.get("location"), 160),
                description=_text(spec.get("description")), hostname=_text(spec.get("hostname"), 120),
                ip_address=_text(spec.get("ip_address"), 60), os=_text(spec.get("os"), 120))
    db.add(m)
    db.flush()
    m.asset_tag = make_tag("M", m.id)
    audit.record(db, entity_type="machine", entity_id=m.id, action="create",
                 after=audit.snapshot(m, MACHINE_FIELDS + ["asset_tag"]), signer=signer)
    report.machine_created = True
    return m


def _url(value, where: str, report: ImportReport) -> str:
    url = _text(value, 500)
    if url and not is_safe_url(url):
        report.warnings.append(f"{where}: indirizzo ignorato (deve iniziare con http:// o https://).")
        return ""
    return url


def apply(db: Session, data: dict, signer, slugger) -> ImportReport:
    """Crea servizi e moduli. `slugger(db, name)` genera lo slug unico. Il commit lo fa il chiamante."""
    report = ImportReport()
    report.machine = _machine(db, data.get("machine"), signer, report)
    seen: set[str] = set()
    for i, spec in enumerate(data["services"], start=1):
        if not isinstance(spec, dict):
            report.warnings.append(f"Voce {i}: non è un oggetto, ignorata.")
            continue
        name = _name(spec.get("name"))
        if not name:
            report.warnings.append(f"Voce {i}: senza nome, ignorata.")
            continue
        if name.lower() in seen:
            report.warnings.append(f'"{name}": ripetuto nel file, ignorato.')
            continue
        seen.add(name.lower())
        existing = (db.query(Service).filter(func.lower(Service.name) == name.lower(), Service.deleted_at.is_(None))
                    .first())
        if existing is not None:
            if report.machine is not None and existing.machine_id is None:
                existing.machine_id = report.machine.id
                audit.record(db, entity_type="service", entity_id=existing.id, action="update",
                             before={"machine_id": None}, after={"machine_id": report.machine.id}, signer=signer)
                report.linked.append(existing.name)
            else:
                report.skipped.append(existing.name)
            continue
        status = spec.get("status") if spec.get("status") in SERVICE_STATUSES else "operational"
        s = Service(slug=slugger(db, name), name=name, status=status,
                    machine_id=report.machine.id if report.machine else None,
                    url=_url(spec.get("url"), name, report), description=_text(spec.get("description")),
                    runbook_md=_text(spec.get("runbook_md")))
        db.add(s)
        db.flush()
        audit.record(db, entity_type="service", entity_id=s.id, action="create",
                     after=audit.snapshot(s, SERVICE_FIELDS), signer=signer)
        modules = spec.get("modules") if isinstance(spec.get("modules"), list) else []
        for mspec in modules[:MAX_MODULES]:
            if not isinstance(mspec, dict) or not _name(mspec.get("name")):
                continue
            kind = mspec.get("kind") if mspec.get("kind") in MODULE_KINDS else "altro"
            m = ServiceModule(service_id=s.id, name=_name(mspec.get("name")), kind=kind,
                              current_version=_text(mspec.get("current_version"), 60),
                              repo_url=_url(mspec.get("repo_url"), f"{name} / {mspec.get('name')}", report),
                              notes=_text(mspec.get("notes")))
            db.add(m)
            db.flush()
            audit.record(db, entity_type="service_module", entity_id=m.id, action="create",
                         after={"service": s.id, "name": m.name, "kind": kind, "version": m.current_version},
                         signer=signer)
        report.created.append(name)
    return report
