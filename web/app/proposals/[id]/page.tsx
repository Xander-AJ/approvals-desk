"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { z } from "zod";
import { api, traceUrl } from "@/lib/api";
import { ProposalDetail } from "@/lib/schemas";
import { useRequireSession } from "@/lib/useSession";
import { btnDanger, btnGhost, btnPrimary, Card, ErrorNote, input, Money, RiskMeter, Skeleton, StateBadge } from "@/components/ui";

const Ok = z.object({ status: z.string() });

function Diff({ label, before, after }: { label: string; before: unknown; after: unknown }) {
  if (String(before) === String(after)) return null;
  return (
    <div className="flex items-center gap-3 border-b border-line py-2 text-sm last:border-0">
      <span className="w-16 text-muted">{label}</span>
      <s className="num rounded px-1.5" style={{ color: "var(--s-bad)", background: "var(--s-bad-bg)" }}>{String(before)}</s>
      <span aria-hidden className="text-muted">→</span>
      <b className="num rounded px-1.5" style={{ color: "var(--s-ok)", background: "var(--s-ok-bg)" }}>{String(after)}</b>
    </div>
  );
}

const STEPS = ["proposed", "pending review", "decided", "executed"] as const;
function stepIndex(state: string) {
  if (state === "proposed") return 0;
  if (state === "pending_review") return 1;
  if (["approved", "edited", "rejected", "expired"].includes(state)) return 2;
  return 3; // executed | failed | compensated
}

/** Where the proposal is on its path. Purely visual; the audit timeline is the record. */
function Stepper({ state }: { state: string }) {
  const at = stepIndex(state);
  const last = state === "compensated" ? "compensated" : state === "failed" ? "failed" : "executed";
  return (
    <div aria-hidden className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      {STEPS.map((label, i) => (
        <div key={label} className="flex items-center gap-2 whitespace-nowrap">
          <span className={`size-2 rounded-full ${i <= at ? "bg-accent" : "bg-line"}`} />
          <span className={i <= at ? "text-ink" : "text-muted"}>{i === 3 ? last : i === 2 && at === 2 ? state.replace("_", " ") : label}</span>
          {i < STEPS.length - 1 && <span className={`hidden h-px w-6 sm:block ${i < at ? "bg-accent" : "bg-line"}`} />}
        </div>
      ))}
    </div>
  );
}

const relTime = (iso: string) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });

export default function ProposalPage() {
  const { id } = useParams<{ id: string }>();
  const session = useRequireSession();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState("");
  const [undoing, setUndoing] = useState(false);
  const [reason, setReason] = useState("");

  const q = useQuery({
    queryKey: ["proposal", id],
    queryFn: () => api(ProposalDetail, `/proposals/${id}`),
    enabled: !!session,
    refetchInterval: 4000,
  });
  const decide = useMutation({
    mutationFn: (p: { path: "approve" | "reject" | "edit"; body?: unknown }) =>
      api(Ok, `/proposals/${id}/${p.path}`, { method: "POST", body: p.body }),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["proposal", id] });
      qc.invalidateQueries({ queryKey: ["proposals"] });
    },
  });

  const compensate = useMutation({
    mutationFn: (r: string) => api(Ok, `/proposals/${id}/compensate`, { method: "POST", body: { reason: r } }),
    onSuccess: () => {
      setUndoing(false);
      setReason("");
      qc.invalidateQueries({ queryKey: ["proposal", id] });
      qc.invalidateQueries({ queryKey: ["proposals"] });
    },
  });

  const p = q.data;
  const canCompensate = session?.role === "admin" && p?.state === "executed";
  const canDecide = (session?.role === "reviewer" || session?.role === "admin") && p?.state === "pending_review";

  return (
    <>
      <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">← Inbox</Link>
      <ErrorNote error={q.error} />
      {!p && !q.error && <Skeleton className="h-24 w-full" />}
      {p && (
        <>
          <div className="rounded-lg border border-line bg-surface p-5">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm capitalize text-muted">{p.action_type.replace("_", " ")}</span>
              <StateBadge state={p.state} />
              <span className="num text-xs text-muted">v{p.version}</span>
              {traceUrl(p.trace_id) && (
                <a className="ml-auto text-sm text-accent hover:underline" href={traceUrl(p.trace_id)!} target="_blank" rel="noreferrer">
                  Agent trace ↗
                </a>
              )}
            </div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">
              <Money amount={p.amount} currency={p.currency} />
            </h1>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <Stepper state={p.state} />
              <RiskMeter score={p.risk_score} />
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1fr_360px] lg:items-start">
            <div className="space-y-4">
              <Card title="Why the agent proposed this">
                <p className="mb-3 text-sm">{p.reason}</p>
                <ul className="space-y-2 text-sm">
                  {p.evidence.map((e, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="mt-0.5 h-fit rounded bg-sunken px-1.5 py-0.5 text-xs text-muted">{e.source}</span>
                      <span className="num">{e.detail}</span>
                    </li>
                  ))}
                </ul>
              </Card>

              {p.original && (
                <Card title="Reviewer edit">
                  <Diff label="amount" before={p.original.amount} after={p.amount} />
                  <Diff label="reason" before={p.original.reason} after={p.reason} />
                </Card>
              )}

              {canDecide && (
                <Card title="Decision">
                  <ErrorNote error={decide.error} />
                  {editing ? (
                    <form
                      className="flex items-center gap-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        decide.mutate({ path: "edit", body: { amount } });
                      }}
                    >
                      <input aria-label="New amount" className={input} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={p.amount} />
                      <button className={btnPrimary} disabled={decide.isPending || !amount}>Save &amp; approve</button>
                      <button type="button" className={btnGhost} onClick={() => setEditing(false)}>Cancel</button>
                    </form>
                  ) : (
                    <div className="flex gap-2">
                      <button className={btnPrimary} disabled={decide.isPending} onClick={() => decide.mutate({ path: "approve" })}>Approve</button>
                      <button className={btnGhost} onClick={() => { setAmount(p.amount); setEditing(true); }}>Edit amount</button>
                      <button className={btnDanger} disabled={decide.isPending} onClick={() => decide.mutate({ path: "reject" })}>Reject</button>
                    </div>
                  )}
                </Card>
              )}

              {canCompensate && (
                <Card title="Undo this payout">
                  <ErrorNote error={compensate.error} />
                  {undoing ? (
                    <form
                      className="space-y-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        compensate.mutate(reason);
                      }}
                    >
                      <p className="text-sm text-zinc-600">
                        This debits the customer again for {p.currency} {Number(p.amount).toLocaleString()}. It can only be done once and is recorded in the audit trail.
                      </p>
                      <textarea
                        aria-label="Compensation reason"
                        className={`${input} w-full`}
                        rows={2}
                        minLength={5}
                        maxLength={500}
                        required
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        placeholder="Why is this being undone? (min 5 characters)"
                      />
                      <div className="flex gap-2">
                        <button className={btnDanger} disabled={compensate.isPending || reason.trim().length < 5}>
                          Confirm compensation
                        </button>
                        <button type="button" className={btnGhost} onClick={() => setUndoing(false)}>Cancel</button>
                      </div>
                    </form>
                  ) : (
                    <button className={btnGhost} onClick={() => setUndoing(true)}>Undo payout…</button>
                  )}
                </Card>
              )}

              {p.result && (
                <Card title="Result">
                  <pre className="overflow-x-auto text-xs">{JSON.stringify(p.result, null, 2)}</pre>
                </Card>
              )}

            </div>

            <Card title="Audit timeline">
              <ol className="relative space-y-4 border-l border-line pl-5">
                {p.audit.map((a, i) => (
                  <li key={i} className="relative text-sm">
                    <span aria-hidden className="absolute -left-[25px] top-1.5 size-2 rounded-full border-2 border-surface bg-accent" />
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <b>{a.event.replace("_", " ")}</b>
                      <span className="text-muted">by {a.actor}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted">
                      <time className="num">{relTime(a.at)}</time>
                      {traceUrl(a.trace_id) && (
                        <a className="ml-auto text-accent hover:underline" href={traceUrl(a.trace_id)!} target="_blank" rel="noreferrer">
                          trace ↗
                        </a>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
