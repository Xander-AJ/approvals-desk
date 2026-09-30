# ADR 0003 — `execute_action` holds a single side effect

**Status:** accepted

## Context
LangGraph checkpoints once per node. If a node makes several tool calls and dies part-way, resume re-runs all of them.

## Decision
- `execute_action` is its own node and performs exactly one mutating call.
- That call carries `Idempotency-Key = sha256(thread_id:proposal_id:version)`; Pesa Ledger stores the key and returns the original result on replay.
- A human edit bumps `version`, so an edited amount is a distinct, deliberate action; a replay of the same version is not.
- The domain state change (`executed`/`failed`) is recorded after the call and is itself replay-safe (`mark` returns early if already in that state).
- Outbound webhooks go through a transactional outbox written in the same transaction as the state change; delivery is at-least-once with `X-Event-Id` for receiver dedupe.

## Proof
`tests/integration/test_chaos.py` kills the worker after the sandbox accepted the refund but before the run recorded it, restarts, and asserts exactly one ledger entry and `executed` state.

## Known gap
If the sandbox call succeeds but the response is lost and the key store is unreachable on retry, we depend on the sandbox honouring the key. Real providers must offer idempotency keys; without them, reconcile against the ledger before retrying.
