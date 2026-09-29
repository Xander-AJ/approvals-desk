# ADR 0002 — Row-level security vs schema-per-tenant

**Status:** accepted

## Decision
Single schema, `tenant_id` on every table, Postgres RLS (`ENABLE` + `FORCE`) with policy `tenant_id = current_setting('app.tenant_id')`. The API sets it with `set_config(..., true)` (transaction-local) inside `tenant_session`.

## Why
- Migrations run once, not per tenant. Schema-per-tenant multiplies migration time and failure modes.
- Isolation is enforced by the database, not by every query remembering a `WHERE`.
- The app connects as `app_user` (`NOSUPERUSER NOBYPASSRLS`); owners/superusers bypass RLS and are never used at runtime.

## Consequences
- An unset tenant sees zero rows (policy compares to `NULLIF(..., '')`), so forgetting to set it fails closed.
- `WITH CHECK` blocks writes to another tenant's `tenant_id`.
- `audit_events` is append-only: `UPDATE/DELETE` revoked and a trigger raises.
- Proven by `tests/integration/test_rls.py` against real Postgres.
- Noisy-neighbour isolation is weaker than schema/db-per-tenant; acceptable for this scale.
- Worker cross-tenant scans read the un-scoped `tenants` table, then operate per tenant.
