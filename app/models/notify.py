"""Webhook in uscita e coda di consegna (outbox)."""
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utcnow


class Webhook(Base):
    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    kind = Column(String(20), default="discord")  # discord | generic
    url = Column(String(500), nullable=False)
    enabled = Column(Boolean, default=True)
    events = Column(JSON, default=list)
    min_severity = Column(String(10))             # null = tutte
    service_ids = Column(JSON)                    # null = tutti
    mention_role_id = Column(String(40), default="")
    username = Column(String(80), default="")
    avatar_url = Column(String(500), default="")
    created_at = Column(DateTime, default=utcnow)


class OutboxItem(Base):
    __tablename__ = "outbox"

    id = Column(Integer, primary_key=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id"), nullable=False)
    event = Column(String(60), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(20), default="pending")  # pending | sent | failed | dead
    attempts = Column(Integer, default=0)
    next_attempt_at = Column(DateTime, default=utcnow)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    sent_at = Column(DateTime)

    webhook = relationship("Webhook")
