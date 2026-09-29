# ADR 0004 — Transactional outbox; arq over Celery

**Status:** accepted

- **Outbox:** state changes and their webhook events commit atomically. The dispatcher claims rows with `FOR UPDATE SKIP LOCKED`, signs the body (HMAC-SHA256, `X-Signature`), and marks `delivered_at` only after a 2xx. Failures increment `attempts` and are retried on the next tick.
- **arq over Celery:** the codebase is async end to end (FastAPI, SQLAlchemy async, asyncpg). arq is async-native, small, and Redis-only. Celery's ecosystem is larger, but we need only cron and a couple of jobs.
- Jobs: SLA expiry (`pending_review` past `expires_at` becomes `expired`, run finishes, customer is told), outbox delivery, and startup recovery.
