"""Fornitori, ordini d'acquisto e sedi (2.4)."""
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utcnow

ORDER_STATUSES = {"draft": "Bozza", "ordered": "Ordinato", "partial": "Arrivato in parte",
                  "received": "Ricevuto", "cancelled": "Annullato"}


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False, unique=True)
    website = Column(String(500), default="")
    email = Column(String(200), default="")
    phone = Column(String(60), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    deleted_at = Column(DateTime)


class SupplierPart(Base):
    """Un componente acquistabile da un fornitore: codice articolo, prezzo, link."""
    __tablename__ = "supplier_parts"
    __table_args__ = (UniqueConstraint("supplier_id", "component_id"),)

    id = Column(Integer, primary_key=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    component_id = Column(Integer, ForeignKey("components.id"), nullable=False)
    sku = Column(String(120), default="")
    price = Column(Integer)  # centesimi
    url = Column(String(500), default="")
    preferred = Column(Boolean, default=False)

    supplier = relationship("Supplier")
    component = relationship("Component")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(Integer, primary_key=True)
    number = Column(String(20), nullable=False, unique=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    notes = Column(Text, default="")
    ordered_at = Column(DateTime)
    expected_at = Column(Date)
    received_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey("operators.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    supplier = relationship("Supplier")
    lines = relationship("PurchaseOrderLine", back_populates="order", cascade="all, delete-orphan",
                         order_by="PurchaseOrderLine.id")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False)
    component_id = Column(Integer, ForeignKey("components.id"), nullable=True)
    description = Column(String(200), nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    qty_received = Column(Integer, nullable=False, default=0)
    unit_price = Column(Integer)  # centesimi

    order = relationship("PurchaseOrder", back_populates="lines")
    component = relationship("Component")


class Site(Base):
    """Sede o magazzino (casa, ufficio, cantina...): raggruppa posizioni e macchine."""
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, unique=True)
    address = Column(String(300), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    deleted_at = Column(DateTime)
