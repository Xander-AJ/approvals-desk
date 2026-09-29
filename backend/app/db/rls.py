"""SQL for row-level security, shared by the Alembic migrations and tests."""
from app.db.models import TENANT_TABLES


def policy_statements(tables: list[str]) -> list[str]:
    stmts: list[str] = []
    for t in tables:
        stmts += [
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {t} "
            f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            f"WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)",
        ]
    return stmts


def grant_statements(app_role: str = "app_user") -> list[str]:
    return [
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {app_role}",
        f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {app_role}",
    ]


def audit_immutability_statements(app_role: str = "app_user") -> list[str]:
    return [
        f"REVOKE UPDATE, DELETE ON audit_events FROM {app_role}",
        """CREATE FUNCTION audit_events_immutable() RETURNS trigger AS $$
           BEGIN RAISE EXCEPTION 'audit_events is append-only'; END $$ LANGUAGE plpgsql""",
        "CREATE TRIGGER audit_events_no_mutate BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_immutable()",
    ]


def rls_statements(app_role: str = "app_user") -> list[str]:
    """Everything, in one go: used by tests that build the schema from the models."""
    return policy_statements(TENANT_TABLES) + grant_statements(app_role) + audit_immutability_statements(app_role)
