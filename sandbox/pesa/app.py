"""Pesa Sandbox: fake wallet/ledger. Mutating calls require Idempotency-Key; replay returns original result."""
from __future__ import annotations

import hmac
import os
import uuid
from decimal import Decimal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Numeric, String, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class Txn(Base):
    __tablename__ = "txns"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(50), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    kind: Mapped[str] = mapped_column(String(20))  # charge | refund | reversal | fee_waiver
    merchant: Mapped[str] = mapped_column(String(100), default="")
    # For kind == "compensation": the transaction it undoes. Unique, so a transaction can be undone only once.
    reference: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyRecord(Base):
    __tablename__ = "idempotency"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


class CompensateIn(BaseModel):
    account_id: str
    reference_txn: str
    amount: Decimal = Field(gt=0)


class MutateIn(BaseModel):
    account_id: str
    amount: Decimal = Field(gt=0)
    reference_txn: str | None = None


def create_app(db_url: str | None = None, api_key: str | None = None) -> FastAPI:
    engine = create_async_engine(db_url or os.environ["SANDBOX_DATABASE_URL"])
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        yield

    async def require_key(x_sandbox_key: str | None = Header(None)) -> None:
        if api_key is not None and not (x_sandbox_key and hmac.compare_digest(x_sandbox_key, api_key)):
            raise HTTPException(401, "invalid or missing X-Sandbox-Key")

    app = FastAPI(title="Pesa Sandbox", lifespan=lifespan, dependencies=[Depends(require_key)])
    app.state.engine = engine

    async def session() -> Any:
        async with maker() as s:
            yield s

    @app.get("/accounts/{account_id}")
    async def get_account(account_id: str, s: AsyncSession = Depends(session)) -> dict[str, Any]:
        acct = await s.get(Account, account_id)
        if not acct:
            raise HTTPException(404, "account not found")
        return {"id": acct.id, "balance": str(acct.balance)}

    @app.get("/accounts/{account_id}/transactions")
    async def txns(account_id: str, s: AsyncSession = Depends(session)) -> list[dict[str, Any]]:
        rows = (await s.execute(select(Txn).where(Txn.account_id == account_id).order_by(Txn.created_at))).scalars()
        return [{"id": t.id, "amount": str(t.amount), "kind": t.kind, "merchant": t.merchant} for t in rows]

    @app.post("/dev/seed")
    async def seed(body: dict[str, Any], s: AsyncSession = Depends(session)) -> dict[str, str]:
        acct = await s.get(Account, body["account_id"])
        if not acct:
            s.add(Account(id=body["account_id"], balance=Decimal(body.get("balance", "0"))))
        for t in body.get("txns", []):
            if not await s.get(Txn, t["id"]):
                s.add(Txn(id=t["id"], account_id=body["account_id"], amount=Decimal(t["amount"]),
                          kind=t.get("kind", "charge"), merchant=t.get("merchant", "")))
        await s.commit()
        return {"ok": "1"}

    async def _mutate(kind: str, body: MutateIn, key: str | None, s: AsyncSession) -> dict[str, Any]:
        if not key:
            raise HTTPException(400, "Idempotency-Key required")
        existing = await s.get(IdempotencyRecord, key)
        if existing:
            return {**existing.result, "replayed": True}
        acct = await s.get(Account, body.account_id, with_for_update=True)
        if not acct:
            raise HTTPException(404, "account not found")
        sign = Decimal(1)  # refunds, reversals, fee waivers all credit the customer
        acct.balance += sign * body.amount
        tid = f"{kind}-{uuid.uuid4().hex[:12]}"
        s.add(Txn(id=tid, account_id=acct.id, amount=body.amount, kind=kind))
        result = {"txn_id": tid, "kind": kind, "amount": str(body.amount), "account_id": acct.id, "replayed": False}
        s.add(IdempotencyRecord(key=key, result=result))
        try:
            await s.commit()
        except IntegrityError:  # concurrent replay lost the race: return the winner's result
            await s.rollback()
            winner = await s.get(IdempotencyRecord, key)
            assert winner
            return {**winner.result, "replayed": True}
        return result

    for kind, path in [("refund", "refunds"), ("reversal", "reversals"), ("fee_waiver", "fee-waivers")]:
        def _make(k: str):  # type: ignore[no-untyped-def]
            async def h(body: MutateIn, idempotency_key: str | None = Header(None),
                        s: AsyncSession = Depends(session)) -> dict[str, Any]:
                return await _mutate(k, body, idempotency_key, s)
            return h
        app.post(f"/{path}")(_make(kind))

    @app.post("/compensations")
    async def compensate(body: CompensateIn, idempotency_key: str | None = Header(None),
                         s: AsyncSession = Depends(session)) -> dict[str, Any]:
        """Undo a refund/reversal/fee-waiver: debit the customer again. Idempotent by key, and at most once per
        original transaction even if a caller uses a different key."""
        if not idempotency_key:
            raise HTTPException(400, "Idempotency-Key required")
        existing = await s.get(IdempotencyRecord, idempotency_key)
        if existing:
            return {**existing.result, "replayed": True}
        ref = await s.get(Txn, body.reference_txn, with_for_update=True)
        if not ref or ref.account_id != body.account_id:
            raise HTTPException(404, "reference transaction not found for this account")
        if ref.kind not in ("refund", "reversal", "fee_waiver"):
            raise HTTPException(422, f"a {ref.kind} cannot be compensated")
        if ref.amount != body.amount:
            raise HTTPException(409, "amount does not match the reference transaction")
        if (await s.execute(select(Txn).where(Txn.reference == ref.id))).first():
            raise HTTPException(409, "reference transaction is already compensated")
        acct = await s.get(Account, body.account_id, with_for_update=True)
        assert acct
        acct.balance -= body.amount
        tid = f"compensation-{uuid.uuid4().hex[:12]}"
        s.add(Txn(id=tid, account_id=acct.id, amount=body.amount, kind="compensation", reference=ref.id))
        result = {"txn_id": tid, "kind": "compensation", "amount": str(body.amount), "account_id": acct.id,
                  "reference_txn": ref.id, "replayed": False}
        s.add(IdempotencyRecord(key=idempotency_key, result=result))
        try:
            await s.commit()
        except IntegrityError:  # concurrent request won (same key, or same reference under another key)
            await s.rollback()
            winner = await s.get(IdempotencyRecord, idempotency_key)
            if winner:
                return {**winner.result, "replayed": True}
            raise HTTPException(409, "reference transaction is already compensated") from None
        return result

    @app.get("/ledger")
    async def ledger(s: AsyncSession = Depends(session)) -> list[dict[str, Any]]:
        rows = (await s.execute(select(Txn).where(Txn.kind != "charge").order_by(Txn.created_at))).scalars()
        return [{"id": t.id, "account_id": t.account_id, "kind": t.kind, "amount": str(t.amount), "reference": t.reference}
                for t in rows]

    return app
