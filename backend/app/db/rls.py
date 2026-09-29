"""SQL for row-level security, shared by the Alembic migration and tests."""
from app.db.models import TENANT_TABLES


def rls_statements(app_role: str = "app_user") -> list[str]:
    stmts: list[str] = []
    for t in TENANT_TABLES:
        stmts += [
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {t} "
            f"USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            f"WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)",
        ]
    stmts += [
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {app_role}",
        f"REVOKE UPDATE, DELETE ON audit_events FROM {app_role}",
        f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {app_role}",
        """CREATE FUNCTION audit_events_immutable() RETURNS trigger AS $$
           BEGIN RAISE EXCEPTION 'audit_events is append-only'; END $$ LANGUAGE plpgsql""",
        "CREATE TRIGGER audit_events_no_mutate BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_immutable()",
    ]
    return stmts
