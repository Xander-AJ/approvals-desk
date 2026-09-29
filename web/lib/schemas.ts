import { z } from "zod";

export const Proposal = z.object({
  id: z.string(),
  action_type: z.string(),
  amount: z.string(),
  currency: z.string(),
  reason: z.string(),
  risk_score: z.number(),
  state: z.string(),
  version: z.number(),
  thread_id: z.string(),
  ticket_id: z.string(),
  auto_approved: z.boolean(),
  trace_id: z.string().nullable(),
  expires_at: z.string().nullable(),
});
export type Proposal = z.infer<typeof Proposal>;

export const AuditEvent = z.object({
  event: z.string(),
  actor: z.string(),
  before: z.record(z.string(), z.unknown()).nullable(),
  after: z.record(z.string(), z.unknown()).nullable(),
  trace_id: z.string().nullable(),
  at: z.string(),
});

export const ProposalDetail = Proposal.omit({ auto_approved: true, expires_at: true }).extend({
  evidence: z.array(z.object({ source: z.string(), detail: z.string() })),
  result: z.record(z.string(), z.unknown()).nullable(),
  original: z.record(z.string(), z.unknown()).nullable(),
  audit: z.array(AuditEvent),
});
export type ProposalDetail = z.infer<typeof ProposalDetail>;

export const Ticket = z.object({
  id: z.string(),
  customer_ref: z.string(),
  message: z.string(),
  reply: z.string().nullable(),
  needs_human: z.boolean(),
  created_at: z.string(),
});

export const Metrics = z.object({
  total: z.number(),
  auto_approve_rate: z.number(),
  override_rate: z.number(),
  avg_approval_latency_s: z.number().nullable(),
});

export const Policy = z.object({
  auto_approve_max: z.string(),
  hard_limit: z.string(),
  max_auto_risk: z.number(),
  allowed_actions: z.array(z.string()),
  sla_minutes: z.number(),
});
export type Policy = z.infer<typeof Policy>;

export const TicketResult = z.object({
  ticket_id: z.string(),
  proposal_id: z.string().nullable(),
  decision: z.string().nullable(),
  reply: z.string().nullable(),
});

export const BulkResult = z.object({ results: z.record(z.string(), z.string()) });
