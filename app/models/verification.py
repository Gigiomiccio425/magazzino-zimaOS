"""Verifica: modelli di test e registro test."""
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utcnow


class TestTemplate(Base):
    __tablename__ = "test_templates"
    __test__ = False  # non e' una classe di test pytest

    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    category = Column(String(80), default="")
    description = Column(Text, default="")
    fields = Column(JSON, default=list)      # [{key,label,type,unit,min,max,choices,pass_value}]
    checklist = Column(JSON, default=list)   # ["passo", ...]
    active = Column(Boolean, default=True)


class TestRun(Base):
    __tablename__ = "test_runs"
    __test__ = False

    id = Column(Integer, primary_key=True)
    component_id = Column(Integer, ForeignKey("components.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("test_templates.id"), nullable=True)
    result = Column(String(20), nullable=False)
    values = Column(JSON, default=dict)
    checklist = Column(JSON, default=dict)
    tool = Column(String(160), default="")
    notes = Column(Text, default="")
    started_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime, default=utcnow)
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=True)
    signature_id = Column(Integer, ForeignKey("signatures.id"), nullable=True)

    component = relationship("Component")
    template = relationship("TestTemplate")
    operator = relationship("Operator")
