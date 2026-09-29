# ADR 0006 — Slack approvals and compensation

**Status:** accepted

## Slack approvals

A Slack button can approve a payout, so the inbound path is the sensitive one.

**Trust model.** A valid Slack signature proves the request came from Slack, not who clicked. Authorisation is separate:

1. Signature: HMAC-SHA256 over `v0:{timestamp}:{body}` with the app's signing secret, constant-time compare, and a
   5-minute freshness window (blocks replays of captured requests). Checked against Slack's documented example vector.
2. Identity: the Slack user id must exist in the tenant's `slack_identities` with role `reviewer` or `admin`. Channel
   membership alone grants nothing. Unmapped clicks are refused and written to the audit log (`slack_unauthorized`).
3. Same domain path as the console: decisions call the shared `_decide` -> state machine -> audit -> resume. Slack gets no
   privileged shortcut, so the RLS, 409-on-invalid-transition and exactly-once guarantees apply unchanged. The audit actor is
   `slack:<user id> (<name>)`.

**Other hardening.** Customer-originated text is escaped before it goes into Slack markup (no `<!channel>` / link
injection). The webhook URL and the request-supplied `response_url` are only POSTed to if they are
`https://hooks.slack.com/...` (otherwise an admin, or a forged payload, could point the server at internal addresses).
The stored webhook URL is never returned by the API. The approve button carries a confirm dialog.

**Delivery.** Slack is an outbox sink. A proposal entering review emits `proposal.pending_review`; the dispatcher posts it.
`outbox_deliveries` records success per sink, so a Slack outage does not re-send the generic webhook and a retry does not
re-post to Slack. If Slack accepts a message but the response is lost, one duplicate is possible (at-least-once).

**Not in Slack:** editing an amount (the message links to the console), and per-user Slack OAuth. Users are mapped by
Slack user id by an admin.

## Compensation (`executed -> compensated`)

Undoing a payout is a money movement, so it follows the same discipline as execution:

- The sandbox call carries a deterministic idempotency key (`sha256(thread:proposal:version:compensate)`) and runs
  **outside** any DB transaction; the state change is recorded afterwards. If the response is lost after the money
  moved, the proposal is still `executed`; a retry replays the sandbox result and completes the transition. One clawback.
- The sandbox refuses to compensate the same transaction twice even under a different key, and checks account, amount and
  that the reference is a refund/reversal/fee waiver.
- Admin only, a written reason (in the audit note), terminal (`compensated` has no exits), outbox event emitted.

**Known gap:** if a compensation was applied at the provider by some other path, our proposal stays `executed` and the
call returns an error; reconciliation against the provider ledger is not built.
