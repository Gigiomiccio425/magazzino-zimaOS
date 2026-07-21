"""Modelli dati: Macchina, Componente, Movimento, Categoria."""
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base

# Stati possibili di un componente
STATUS_STOCK = "stock"        # a magazzino
STATUS_IN_USE = "in_use"      # montato su una macchina
STATUS_FAULTY = "faulty"      # guasto
STATUS_RETIRED = "retired"    # dismesso

STATUSES = {
    STATUS_STOCK: "A magazzino",
    STATUS_IN_USE: "In uso",
    STATUS_FAULTY: "Guasto",
    STATUS_RETIRED: "Dismesso",
}


class Machine(Base):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, unique=True)
    kind = Column(String(60), default="")        # desktop / server / laptop / NAS ...
    location = Column(String(160), default="")   # dove si trova fisicamente la macchina
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    components = relationship("Component", back_populates="machine")


class Component(Base):
    __tablename__ = "components"

    id = Column(Integer, primary_key=True)
    object_code = Column(String(80), default="")   # codice oggetto / inventario
    name = Column(String(160), nullable=False)
    category = Column(String(80), default="")      # RAM, SSD, CPU, ...
    model = Column(String(160), default="")
    manufacturer = Column(String(120), default="")
    serial_number = Column(String(160), default="")
    quantity = Column(Integer, default=1)
    status = Column(String(30), default=STATUS_STOCK)
    location = Column(String(160), default="")     # scaffale / box quando a magazzino
    # Attributi flessibili per tipo (es. RAM: capacita, tipo, velocita)
    attributes = Column(JSON, default=dict)
    notes = Column(Text, default="")

    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    machine = relationship("Machine", back_populates="components")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    movements = relationship(
        "Movement",
        back_populates="component",
        cascade="all, delete-orphan",
        order_by="desc(Movement.timestamp)",
    )


class Movement(Base):
    """Storico spostamenti / cambi di stato di un componente."""
    __tablename__ = "movements"

    id = Column(Integer, primary_key=True)
    component_id = Column(Integer, ForeignKey("components.id"), nullable=False)
    action = Column(String(40), default="")        # created / moved / status / removed
    from_machine = Column(String(120), default="")
    to_machine = Column(String(120), default="")
    note = Column(Text, default="")
    timestamp = Column(DateTime, default=datetime.utcnow)

    component = relationship("Component", back_populates="movements")


class Category(Base):
    """Categorie suggerite (popolano il datalist). Aggiunte in automatico."""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False, unique=True)
