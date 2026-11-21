"""Costruisce un DB identico a quello creato da GD Magazzino v1.1.1, con dati di esempio.

I modelli sotto sono una copia verbatim di app/models.py alla v1.1.1 (commit 01f1a88),
con un declarative_base proprio: cosi' il file prodotto ha lo stesso schema di un DB reale.
"""
from datetime import datetime
from pathlib import Path

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, relationship

Base = declarative_base()
T0 = datetime(2026, 7, 1, 10, 0, 0)


class Machine(Base):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, unique=True)
    kind = Column(String(60), default="")
    location = Column(String(160), default="")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=T0)

    components = relationship("Component", back_populates="machine")


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
    status = Column(String(30), default="stock")
    location = Column(String(160), default="")
    attributes = Column(JSON, default=dict)
    notes = Column(Text, default="")

    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    machine = relationship("Machine", back_populates="components")

    created_at = Column(DateTime, default=T0)
    updated_at = Column(DateTime, default=T0, onupdate=T0)

    movements = relationship("Movement", back_populates="component", cascade="all, delete-orphan")


class Movement(Base):
    __tablename__ = "movements"

    id = Column(Integer, primary_key=True)
    component_id = Column(Integer, ForeignKey("components.id"), nullable=False)
    action = Column(String(40), default="")
    from_machine = Column(String(120), default="")
    to_machine = Column(String(120), default="")
    note = Column(Text, default="")
    timestamp = Column(DateTime, default=T0)

    component = relationship("Component", back_populates="movements")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False, unique=True)


CATEGORIES = [
    "RAM", "SSD", "HDD", "CPU", "GPU", "Scheda madre", "Alimentatore",
    "Case", "Ventola", "Cavo", "Scheda di rete", "Periferica", "Altro",
]


def build_v111_db(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(Category(name=n) for n in CATEGORIES)
        server = Machine(name="Server Umbrel", kind="server", location="Rack")
        pc = Machine(name="PC Gaming", kind="desktop", location="Studio")
        db.add_all([server, pc])
        db.flush()
        ram = Component(
            name="Corsair 16GB", category="RAM", serial_number="RAM-001", status="in_use",
            machine_id=server.id,
            attributes={"Capacita (GB)": "16", "Tipo": "DDR4", "Velocita (MHz)": "3200"},
        )
        gpu = Component(
            name="RTX 3060", category="GPU", serial_number="GPU-XYZ", status="stock",
            location="Scaffale A", attributes={"VRAM (GB)": "12", "Chipset": "GA106"},
        )
        cable = Component(
            name="HDMI 2m", category="Cavo", quantity=30, status="stock",
            location="Box cavi", attributes={"Lunghezza": "2 m"},
        )
        ssd = Component(
            name="Samsung 970", category="SSD", object_code="INV-9", status="faulty",
            location="Scaffale A", attributes={"Capacita (GB)": "1TB"},
        )
        db.add_all([ram, gpu, cable, ssd])
        db.flush()
        for c in (ram, gpu, cable, ssd):
            db.add(Movement(component_id=c.id, action="created", note="Componente creato"))
        db.add(Movement(component_id=ram.id, action="moved", from_machine="", to_machine="Server Umbrel",
                        note="Spostamento"))
        db.commit()
    engine.dispose()
