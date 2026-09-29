"""The Alembic migrations, not the model metadata, are what production runs: test them directly."""
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from app.db.models import TENANT_TABLES, Base

BACKEND = Path(__file__).resolve().parents[2]


def _alembic(pg, db: str, *args: str, password: str = "mig-test-pw") -> None:  # type: ignore[no-untyped-def]
    host, port = pg.get_container_host_ip(), pg.get_exposed_port(5432)
    env = {**os.environ, "PYTHONPATH": str(BACKEND), "APP_DB_PASSWORD": password,
           "MIGRATION_DATABASE_URL": f"postgresql+asyncpg://{pg.username}:{pg.password}@{host}:{port}/{db}"}
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode()[-2000:]


def _connect(pg, db: str, user: str | None = None, password: str | None = None):  # type: ignore[no-untyped-def]
    return psycopg.connect(host=pg.get_container_host_ip(), port=pg.get_exposed_port(5432), dbname=db,
                           user=user or pg.username, password=password or pg.password, autocommit=True)


@pytest.fixture(scope="module")
def own_pg():  # type: ignore[no-untyped-def]
    # Roles are cluster-wide, so use a dedicated cluster: the migration must create app_user itself, as in a real deploy.
    with PostgresContainer("postgres:16", driver="asyncpg") as c:
        yield c


@pytest.fixture
def fresh_db(own_pg):  # type: ignore[no-untyped-def]
    db = "migtest"
    with _connect(own_pg, own_pg.dbname) as c:
        c.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {db}")
    return own_pg, db


def test_upgrade_head_builds_the_same_schema_as_the_models_with_rls_everywhere(fresh_db) -> None:  # type: ignore[no-untyped-def]
    pg, db = fresh_db
    _alembic(pg, db, "upgrade", "head")
    with _connect(pg, db) as c:
        tables = {r[0] for r in c.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")}
        assert tables == set(Base.metadata.tables), tables ^ set(Base.metadata.tables)
        rls = {r[0]: (r[1], r[2]) for r in c.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relnamespace='public'::regnamespace AND relkind='r'")}
        for t in TENANT_TABLES:
            assert rls[t] == (True, True), f"{t} lacks forced RLS"
            assert c.execute("SELECT count(*) FROM pg_policies WHERE tablename=%s AND policyname='tenant_isolation'",
                             (t,)).fetchone()[0] == 1, t
        assert c.execute("SELECT count(*) FROM pg_trigger WHERE tgname='audit_events_no_mutate'").fetchone()[0] == 1
        assert c.execute("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname='app_user'").fetchone() == (False, False)


def test_migrated_runtime_role_is_tenant_isolated_including_the_slack_tables(fresh_db) -> None:  # type: ignore[no-untyped-def]
    pg, db = fresh_db
    _alembic(pg, db, "upgrade", "head")
    a, b = "00000000-0000-0000-0000-00000000000a", "00000000-0000-0000-0000-00000000000b"
    with _connect(pg, db, "app_user", "mig-test-pw") as c:
        with c.transaction():
            c.execute("SELECT set_config('app.tenant_id', %s, true)", (a,))
            c.execute("INSERT INTO slack_identities (id, tenant_id, slack_user_id, role, label) "
                      "VALUES (gen_random_uuid(), %s, 'U1', 'reviewer', 'x')", (a,))
            c.execute("INSERT INTO tenant_integrations (tenant_id, slack_webhook_url) VALUES (%s, 'https://hooks.slack.com/x')", (a,))
        with c.transaction():
            c.execute("SELECT set_config('app.tenant_id', %s, true)", (b,))
            assert c.execute("SELECT count(*) FROM slack_identities").fetchone()[0] == 0
            assert c.execute("SELECT count(*) FROM tenant_integrations").fetchone()[0] == 0
        with pytest.raises(psycopg.Error), c.transaction():
            c.execute("SELECT set_config('app.tenant_id', %s, true)", (b,))
            c.execute("INSERT INTO slack_identities (id, tenant_id, slack_user_id, role) "
                      "VALUES (gen_random_uuid(), %s, 'U2', 'admin')", (a,))  # cross-tenant write


def test_downgrade_and_reupgrade_round_trips(fresh_db) -> None:  # type: ignore[no-untyped-def]
    pg, db = fresh_db
    _alembic(pg, db, "upgrade", "head")
    _alembic(pg, db, "downgrade", "0001")
    with _connect(pg, db) as c:
        assert not c.execute("SELECT to_regclass('public.slack_identities')").fetchone()[0]
        assert c.execute("SELECT to_regclass('public.proposals')").fetchone()[0]
    _alembic(pg, db, "upgrade", "head")
    with _connect(pg, db) as c:
        assert c.execute("SELECT to_regclass('public.slack_identities')").fetchone()[0]
