import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.models import AuditEvent, Ticket
from app.db.session import tenant_session

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_cross_tenant_reads_fail(engines) -> None:  # type: ignore[no-untyped-def]
    _, app = engines
    a, b = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(app, a) as s:
        s.add(Ticket(tenant_id=a, customer_ref="c1", message="hi", thread_id=f"t-{a}"))
    async with tenant_session(app, a) as s:
        assert (await s.execute(text("SELECT count(*) FROM tickets"))).scalar_one() == 1
    async with tenant_session(app, b) as s:
        assert (await s.execute(text("SELECT count(*) FROM tickets"))).scalar_one() == 0


async def test_no_tenant_set_sees_nothing(engines) -> None:  # type: ignore[no-untyped-def]
    _, app = engines
    async with app.begin() as c:
        assert (await c.execute(text("SELECT count(*) FROM tickets"))).scalar_one() == 0


async def test_cross_tenant_write_rejected(engines) -> None:  # type: ignore[no-untyped-def]
    _, app = engines
    a, b = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(DBAPIError):
        async with tenant_session(app, a) as s:
            s.add(Ticket(tenant_id=b, customer_ref="x", message="m", thread_id=f"t-{b}"))


async def test_audit_events_append_only(engines) -> None:  # type: ignore[no-untyped-def]
    _, app = engines
    a = uuid.uuid4()
    async with tenant_session(app, a) as s:
        s.add(AuditEvent(tenant_id=a, actor="u", event="x"))
    with pytest.raises(DBAPIError):
        async with tenant_session(app, a) as s:
            await s.execute(text("UPDATE audit_events SET actor='evil'"))
    with pytest.raises(DBAPIError):
        async with tenant_session(app, a) as s:
            await s.execute(text("DELETE FROM audit_events"))
