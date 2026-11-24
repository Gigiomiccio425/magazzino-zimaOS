"""Operatori, credenziali passkey, firme, audit log."""
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import relationship

from ..database import Base
from ..timeutil import utcnow


class Operator(Base):
    __tablename__ = "operators"

    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    name_key = Column(String(80), nullable=False, unique=True)  # casefold, spazi compressi
    is_admin = Column(Boolean, default=False)
    active = Column(Boolean, default=True)
    password_hash = Column(String(255))
    failed_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)

    credentials = relationship("OperatorCredential", back_populates="operator", cascade="all, delete-orphan")


class OperatorCredential(Base):
    """Passkey WebAuthn (legata al dominio rp_id)."""
    __tablename__ = "operator_credentials"

    id = Column(Integer, primary_key=True)
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=False)
    credential_id = Column(LargeBinary, nullable=False, unique=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, default=0)
    transports = Column(JSON, default=list)
    rp_id = Column(String(255), nullable=False)
    label = Column(String(120), default="")
    created_at = Column(DateTime, default=utcnow)
    last_used_at = Column(DateTime)

    operator = relationship("Operator", back_populates="credentials")


class Signature(Base):
    __tablename__ = "signatures"

    id = Column(Integer, primary_key=True)
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=False)
    method = Column(String(20), nullable=False)  # passkey | password
    purpose = Column(String(300))                # azione critica firmata, se presente
    action_hash = Column(String(64))
    rp_id = Column(String(255))
    ip = Column(String(60), default="")
    user_agent = Column(String(300), default="")
    created_at = Column(DateTime, default=utcnow)

    operator = relationship("Operator")


class AuditLog(Base):
    """Registro di ogni scrittura, con catena di hash."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, default=utcnow, nullable=False)
    actor_type = Column(String(20), default="operator")  # operator | system
    operator_id = Column(Integer, ForeignKey("operators.id"), nullable=True)
    signature_id = Column(Integer, ForeignKey("signatures.id"), nullable=True)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(Integer)
    action = Column(String(40), nullable=False)
    before = Column(JSON)
    after = Column(JSON)
    prev_hash = Column(String(64), nullable=False)
    hash = Column(String(64), nullable=False)

    operator = relationship("Operator")
