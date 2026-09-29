"""init schema + RLS"""
import os
from alembic import op
from sqlalchemy import text

from app.db.models import Base
from app.db.rls import rls_statements

revision = "0001"
down_revision = None


def upgrade() -> None:
    bind = op.get_bind()
    # Dev default only; deployments must set APP_DB_PASSWORD (Terraform injects it from Secrets Manager).
    pw = os.environ.get("APP_DB_PASSWORD", "app_user").replace("'", "''")
    if not bind.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'app_user'")).first():
        # CREATE ROLE is a utility statement: it cannot take bind parameters, so quote the literal.
        bind.exec_driver_sql(f"CREATE ROLE app_user LOGIN PASSWORD '{pw}' NOSUPERUSER NOBYPASSRLS")
    Base.metadata.create_all(bind)
    for s in rls_statements():
        bind.execute(text(s))


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
