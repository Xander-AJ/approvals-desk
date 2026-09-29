"""slack integration tables + RLS"""
from alembic import op
from sqlalchemy import text

from app.db.models import V2_TENANT_TABLES, Base
from app.db.rls import grant_statements, policy_statements

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind, tables=[Base.metadata.tables[t] for t in V2_TENANT_TABLES])
    for stmt in policy_statements(V2_TENANT_TABLES) + grant_statements():
        bind.execute(text(stmt))


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind(), tables=[Base.metadata.tables[t] for t in V2_TENANT_TABLES])
