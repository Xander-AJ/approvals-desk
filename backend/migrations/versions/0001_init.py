"""init schema + RLS"""
import os

from alembic import op
from sqlalchemy import text

from app.db.models import V1_TENANT_TABLES, Base
from app.db.rls import audit_immutability_statements, grant_statements, policy_statements

revision = "0001"
down_revision = None


def upgrade() -> None:
    bind = op.get_bind()
    # Dev default only; deployments must set APP_DB_PASSWORD (Terraform injects it from Secrets Manager).
    pw = os.environ.get("APP_DB_PASSWORD", "app_user").replace("'", "''")
    if not bind.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'app_user'")).first():
        # CREATE ROLE is a utility statement: it cannot take bind parameters, so quote the literal.
        bind.exec_driver_sql(f"CREATE ROLE app_user LOGIN PASSWORD '{pw}' NOSUPERUSER NOBYPASSRLS")
    # Pinned to the v1 tables: later tables are created by later migrations, never by 0001.
    v1 = ["tenants", *V1_TENANT_TABLES]
    Base.metadata.create_all(bind, tables=[Base.metadata.tables[t] for t in v1])
    for stmt in policy_statements(V1_TENANT_TABLES) + grant_statements() + audit_immutability_statements():
        bind.execute(text(stmt))


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind, tables=[Base.metadata.tables[t] for t in ["tenants", *V1_TENANT_TABLES]])
