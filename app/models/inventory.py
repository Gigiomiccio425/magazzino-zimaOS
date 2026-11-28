"""Inventario: componenti, macchine, posizioni, movimenti, categorie, tag, allegati, inventari, progetti."""
from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utcnow
from .constants import STATUS_STOCK

component_tags = Table(
    "component_tags",
    Base.metadata,
    Column("component_id", Integer, ForeignKey("components.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True)
    asset_tag = Column(String(20))
    name = Column(String(120), nullable=False)
    kind = Column(String(20), default="altro")
    parent_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    notes = Column(Text, default="")
    last_audit_at = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)
    deleted_at = Column(DateTime)

    parent = relationship("Location", remote_side=[id], back_populates="children")
    children = relationship("Location", back_populates="parent")


class Machine(Base):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, unique=True)
    kind = Column(String(60), default="")
    location = Column(String(160), default="")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    # v2
    asset_tag = Column(String(20))
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    hostname = Column(String(120), default="")
    ip_address = Column(String(60), default="")
    os = Column(String(120), default="")
    deleted_at = Column(DateTime)

    components = relationship("Component", back_populates="machine")
    place = relationship("Location")


class Component(Base):
    __tablename__ = "components"

    id = Column(Integer, primary_key=True)
    object_code = Column(String(80), default="")
    name = Column(String(160), nullable=False)
    category = Column(String(80), default="")
    model = Column(String(160), default="")
    manufacturer = Column(String(120), default="")
    serial_number = Column(String(160), default="")
    quantity = Column(Integer, default=1)
    status = Column(String(30), default=STATUS_STOCK)
    location = Column(String(160), default="")
    attributes = Column(JSON, default=dict)
    notes = Column(Text, default="")
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    # v2
    asset_tag = Column(String(20))
    tracking = Column(String(20), default="serial")
    min_stock = Column(Integer)
    unit = Column(String(20), default="pz")
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    supplier = Column(String(160), default="")
    purchase_date = Column(Date)
    purchase_price = Column(Integer)  # centesimi
    currency = Column(String(3), default="EUR")
    warranty_until = Column(Date)
    invoice_ref = Column(String(120), default="")
    last_test_at = Column(DateTime)
    last_test_result = Column(String(20))
    last_audit_at = Column(DateTime)
    deleted_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("operators.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("operators.id"), nullable=True)
    # v2.3: generati in automatico (services/codes.py), unici
    stock_serial = Column(String(40), unique=True)
    ref_code = Column(String(20), unique=True)

    machine = relationship("Machine", back_populates="components")
    place = relationship("Location")
    tags = relationship("Tag", secondary=component_tags, order_by="Tag.name")
    movements = relationship(
        "Movement",
        back_populates="component",
        cascade="all, delete-orphan",
        order_by="desc(Movement.timestamp)",
    )


class Movement(Base):
    """Storico spostamenti / cambi di stato / variazioni quantita'."""
    __tablename__ = "movements"

    id = Column(Integer, primary_key=True)
    component_id = Column(Integer, ForeignKey("components.id"), nullable=False)
    action = Column(String(40), default="")
    from_machine = Column(String(120), default="")
    to_machine = Column(String(120), default="")
    note = Column(Text, default="")
    timestamp = Column(DateTime, default=utcnow)
    # v2
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=True)
    signature_id = Column(Integer, ForeignKey("signatures.id"), nullable=True)
    qty_delta = Column(Integer)
    reason = Column(Text, default="")

    component = relationship("Component", back_populates="movements")
    operator = relationship("Operator")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False, unique=True)
    # v2
    icon = Column(String(40), default="")
    default_tracking = Column(String(20), default="serial")
    default_unit = Column(String(20), default="pz")

    fields = relationship("CategoryField", back_populates="category", order_by="CategoryField.sort_order")


class CategoryField(Base):
    """Campo tipizzato per categoria. `key` immutabile: per i predefiniti = etichetta storica."""
    __tablename__ = "category_fields"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    key = Column(String(80), nullable=False)
    label = Column(String(80), nullable=False)
    type = Column(String(20), default="text")
    unit = Column(String(20), default="")
    choices = Column(JSON, default=list)
    required = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    filterable = Column(Boolean, default=True)
    active = Column(Boolean, default=True)

    category = relationship("Category", back_populates="fields")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False, unique=True)


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(Integer, nullable=False)
    filename = Column(String(255), nullable=False)
    mime = Column(String(100), nullable=False)
    size = Column(Integer, default=0)
    path = Column(String(255), nullable=False)
    thumb_path = Column(String(255))
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    deleted_at = Column(DateTime)


class InventoryAudit(Base):
    """Inventario fisico di una posizione."""
    __tablename__ = "audits"

    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    include_children = Column(Boolean, default=True)
    status = Column(String(20), default="open")
    started_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime)
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=True)
    signature_id = Column(Integer, ForeignKey("signatures.id"), nullable=True)
    summary = Column(JSON, default=dict)

    location = relationship("Location")
    items = relationship("InventoryAuditItem", back_populates="audit", cascade="all, delete-orphan")


class InventoryAuditItem(Base):
    __tablename__ = "audit_items"

    id = Column(Integer, primary_key=True)
    audit_id = Column(Integer, ForeignKey("audits.id"), nullable=False)
    component_id = Column(Integer, ForeignKey("components.id"), nullable=False)
    state = Column(String(20), default="expected")
    scanned_at = Column(DateTime)

    audit = relationship("InventoryAudit", back_populates="items")
    component = relationship("Component")


class Project(Base):
    """Progetto / build PC con componenti prenotati."""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    description = Column(Text, default="")
    status = Column(String(20), default="draft")
    target_machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    deleted_at = Column(DateTime)

    target_machine = relationship("Machine")
    items = relationship("ProjectItem", back_populates="project", cascade="all, delete-orphan")


class ProjectItem(Base):
    __tablename__ = "project_items"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    component_id = Column(Integer, ForeignKey("components.id"), nullable=False)
    qty = Column(Integer, default=1)
    note = Column(Text, default="")
    prev_status = Column(String(30))

    project = relationship("Project", back_populates="items")
    component = relationship("Component")
