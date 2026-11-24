"""Impostazioni chiave/valore e coda di stampa delle etichette."""
from sqlalchemy import JSON, Column, DateTime, Integer, String, UniqueConstraint

from ..database import Base
from ..timeutil import utcnow


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(80), primary_key=True)
    value = Column(JSON)  # sempre {"v": valore}: evita la conversione numerica di SQLite


class PrintItem(Base):
    """Un elemento in coda di stampa: componente, posizione o macchina, con formato e copie."""
    __tablename__ = "print_queue"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id"),)

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(20), nullable=False)  # component | location | machine
    entity_id = Column(Integer, nullable=False)
    format = Column(String(10), nullable=False, default="label")  # label | qr | flag
    copies = Column(Integer, nullable=False, default=1)
    added_by = Column(String(120))
    created_at = Column(DateTime, default=utcnow)
