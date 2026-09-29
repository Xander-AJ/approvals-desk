# ADR 0001 — LangGraph Postgres checkpointer vs Temporal

**Status:** accepted

## Context
Reviews can take seconds or days, and workers can die at any point. We need durable pause/resume and exactly-once money movement.

## Decision
Use the LangGraph Postgres checkpointer for durable run state, plus a domain-level approval state machine in our own tables, plus idempotency keys on every mutating call.

## Why not Temporal
Temporal gives stronger durability primitives, but adds a cluster to operate and a second programming model. The agent is already a LangGraph graph; the only irreversible step is one node. Idempotency keys make that node safe to re-run, which recovers most of what Temporal would give us here.

## Consequences
- Checkpoints are written **per node**. On resume the interrupted node restarts from its beginning; earlier nodes do not re-run.
- Therefore: everything before `interrupt()` in a node must be side-effect free, and `save_proposal` is idempotent per thread.
- The checkpointer connects with an owner DSN; checkpoint tables carry no tenant data beyond `thread_id`, and thread IDs are only reachable through RLS-protected rows.
- Crash recovery is a worker startup scan (`recover_runs`): proposals in `approved`/`edited` with an unfinished run are continued from their last checkpoint.
- Revisit Temporal if we add long multi-step compensation flows or need cross-service sagas.
