"""Centro di comando: servizi, moduli, changelog, link, incidenti, problemi, manutenzioni."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utcnow

incident_services = Table(
    "incident_services",
    Base.metadata,
    Column("incident_id", Integer, ForeignKey("incidents.id"), primary_key=True),
    Column("service_id", Integer, ForeignKey("services.id"), primary_key=True),
)
problem_services = Table(
    "problem_services",
    Base.metadata,
    Column("problem_id", Integer, ForeignKey("problems.id"), primary_key=True),
    Column("service_id", Integer, ForeignKey("services.id"), primary_key=True),
)
problem_incidents = Table(
    "problem_incidents",
    Base.metadata,
    Column("problem_id", Integer, ForeignKey("problems.id"), primary_key=True),
    Column("incident_id", Integer, ForeignKey("incidents.id"), primary_key=True),
)
maintenance_services = Table(
    "maintenance_services",
    Base.metadata,
    Column("maintenance_id", Integer, ForeignKey("maintenances.id"), primary_key=True),
    Column("service_id", Integer, ForeignKey("services.id"), primary_key=True),
)


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True)
    slug = Column(String(120), nullable=False, unique=True)
    name = Column(String(160), nullable=False)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    description = Column(Text, default="")
    url = Column(String(500), default="")
    status = Column(String(30), default="operational")
    runbook_md = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    deleted_at = Column(DateTime)

    machine = relationship("Machine")
    modules = relationship("ServiceModule", back_populates="service", cascade="all, delete-orphan")


class ServiceModule(Base):
    __tablename__ = "service_modules"

    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    name = Column(String(160), nullable=False)
    kind = Column(String(30), default="altro")
    current_version = Column(String(60), default="")
    repo_url = Column(String(500), default="")
    notes = Column(Text, default="")

    service = relationship("Service", back_populates="modules")


class Change(Base):
    """Voce di changelog (sempre inserita a mano)."""
    __tablename__ = "changes"

    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    module_id = Column(Integer, ForeignKey("service_modules.id"), nullable=True)
    type = Column(String(20), default="note")
    version = Column(String(60), default="")
    title = Column(String(200), nullable=False)
    body_md = Column(Text, default="")
    occurred_at = Column(DateTime, default=utcnow)
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=True)
    signature_id = Column(Integer, ForeignKey("signatures.id"), nullable=True)

    service = relationship("Service")
    module = relationship("ServiceModule")
    operator = relationship("Operator")


class Link(Base):
    """Link (es. GitHub) collegato a un'entita'. Tipo ricavato dall'URL, nessuna chiamata di rete."""
    __tablename__ = "links"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(Integer, nullable=False)
    url = Column(String(1000), nullable=False)
    title = Column(String(200), default="")
    kind = Column(String(30), default="altro")
    owner = Column(String(120), default="")
    repo = Column(String(120), default="")
    ref = Column(String(120), default="")


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    severity = Column(String(10), default="SEV3")
    status = Column(String(20), default="open")
    started_at = Column(DateTime, default=utcnow)
    resolved_at = Column(DateTime)
    summary = Column(Text, default="")
    root_cause = Column(Text, default="")
    postmortem_md = Column(Text, default="")
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=True)

    services = relationship("Service", secondary=incident_services)
    updates = relationship(
        "IncidentUpdate", back_populates="incident", cascade="all, delete-orphan",
        order_by="desc(IncidentUpdate.created_at)",
    )
    operator = relationship("Operator")


class IncidentUpdate(Base):
    __tablename__ = "incident_updates"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    status = Column(String(20), nullable=False)
    message = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=True)
    signature_id = Column(Integer, ForeignKey("signatures.id"), nullable=True)
    notified = Column(Boolean, default=False)

    incident = relationship("Incident", back_populates="updates")
    operator = relationship("Operator")


class Problem(Base):
    """Problema noto / ricorrente con workaround."""
    __tablename__ = "problems"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description_md = Column(Text, default="")
    workaround_md = Column(Text, default="")
    status = Column(String(20), default="open")
    created_at = Column(DateTime, default=utcnow)

    services = relationship("Service", secondary=problem_services)
    incidents = relationship("Incident", secondary=problem_incidents)


class Maintenance(Base):
    __tablename__ = "maintenances"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description_md = Column(Text, default="")
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=False)
    status = Column(String(20), default="scheduled")
    created_at = Column(DateTime, default=utcnow)

    services = relationship("Service", secondary=maintenance_services)
