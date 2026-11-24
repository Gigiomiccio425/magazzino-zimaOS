"""Impostazioni chiave/valore."""
from sqlalchemy import JSON, Column, String

from ..database import Base


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(80), primary_key=True)
    value = Column(JSON)
