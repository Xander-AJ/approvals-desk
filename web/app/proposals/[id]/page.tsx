"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { z } from "zod";
import { api, traceUrl } from "@/lib/api";
import { ProposalDetail } from "@/lib/schemas";
import { useRequireSession } from "@/lib/useSession";
import { btnDanger, btnGhost, btnPrimary, Card, ErrorNote, input, StateBadge } from "@/components/ui";

const Ok = z.object({ status: z.string() });

function Diff({ label, before, after }: { label: string; before: unknown; after: unknown }) {
  if (String(before) === String(after)) return null;
  return (
    <div className="text-sm">
      <span className="text-zinc-500">{label}: </span>
      <s className="text-rose-700">{String(before)}</s> → <b className="text-emerald-700">{String(after)}</b>
    </div>
  );
}

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
      <Link href="/" className="text-sm underline">← Inbox</Link>
      <ErrorNote error={q.error} />
      {p && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold">
              {p.action_type.replace("_", " ")} · {p.currency} {Number(p.amount).toLocaleString()}
            </h1>
            <StateBadge state={p.state} />
            <span className="text-sm text-zinc-500">v{p.version} · risk {p.risk_score}</span>
            {traceUrl(p.trace_id) && (
              <a className="ml-auto text-sm underline" href={traceUrl(p.trace_id)!} target="_blank" rel="noreferrer">
                Agent trace ↗
              </a>
            )}
          </div>

          <Card title="Why the agent proposed this">
            <p className="mb-3 text-sm">{p.reason}</p>
            <ul className="space-y-1 text-sm">
              {p.evidence.map((e, i) => (
                <li key={i}><span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs">{e.source}</span> {e.detail}</li>
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

          <Card title="Audit timeline">
            <ol className="space-y-3 border-l border-zinc-200 pl-4">
              {p.audit.map((a, i) => (
                <li key={i} className="text-sm">
                  <div className="flex items-center gap-2">
                    <b>{a.event.replace("_", " ")}</b>
                    <span className="text-zinc-500">by {a.actor}</span>
                    <time className="text-xs text-zinc-400">{new Date(a.at).toLocaleString()}</time>
                    {traceUrl(a.trace_id) && (
                      <a className="ml-auto text-xs underline" href={traceUrl(a.trace_id)!} target="_blank" rel="noreferrer">
                        trace ↗
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </Card>
        </>
      )}
    </>
  );
}
