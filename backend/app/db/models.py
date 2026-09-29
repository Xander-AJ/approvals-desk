from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonB = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), nullable=False, index=True)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))  # agent | reviewer | admin


class TenantPolicy(Base):
    __tablename__ = "tenant_policies"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    auto_approve_max: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    review_required_above: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    hard_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("50000"))
    max_auto_risk: Mapped[int] = mapped_column(Integer, default=30)  # 0-100
    allowed_actions: Mapped[list[str]] = mapped_column(JsonB, default=list)
    sla_minutes: Mapped[int] = mapped_column(Integer, default=60)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    customer_ref: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    thread_id: Mapped[str] = mapped_column(String(100), unique=True)
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_human: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"))
    thread_id: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    action_type: Mapped[str] = mapped_column(String(30))  # refund | reversal | fee_waiver
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="KES")
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JsonB, default=list)
    risk_score: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), index=True)
    original: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)  # pre-edit snapshot
    result: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_approved: Mapped[bool] = mapped_column(default=False)


class AuditEvent(Base):
    """Append-only; UPDATE/DELETE blocked by trigger (see migration)."""

    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True, nullable=True)
    actor: Mapped[str] = mapped_column(String(200))
    event: Mapped[str] = mapped_column(String(50))
    before: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JsonB, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    __tablename__ = "outbox"
    id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    topic: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonB)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


TENANT_TABLES = ["users", "tenant_policies", "tickets", "proposals", "audit_events", "outbox"]
__all__ = ["UniqueConstraint"]
