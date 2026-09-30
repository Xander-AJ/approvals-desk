"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { z } from "zod";
import { api } from "@/lib/api";
import { BulkResult, Proposal, Ticket } from "@/lib/schemas";
import { useRequireSession } from "@/lib/useSession";
import { btnDanger, btnGhost, btnPrimary, Card, EmptyState, ErrorNote, input, Money, PageHeader, RiskMeter, Skeleton, StateBadge } from "@/components/ui";

const STATES = ["", "pending_review", "approved", "edited", "executed", "rejected", "expired", "failed", "compensated"];
const ACTIONS = ["", "refund", "reversal", "fee_waiver"];

export default function InboxPage() {
  const session = useRequireSession();
  const qc = useQueryClient();
  const router = useRouter();
  const [state, setState] = useState("pending_review");
  const [action, setAction] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const canDecide = session?.role === "reviewer" || session?.role === "admin";

  const qs = new URLSearchParams();
  if (state) qs.set("state", state);
  if (action) qs.set("action_type", action);
  const proposals = useQuery({
    queryKey: ["proposals", state, action],
    queryFn: () => api(z.array(Proposal), `/proposals?${qs}`),
    enabled: !!session,
    refetchInterval: 5000,
  });
  const escalated = useQuery({
    queryKey: ["tickets", "needs_human"],
    queryFn: () => api(z.array(Ticket), "/tickets?needs_human=true"),
    enabled: !!session,
    refetchInterval: 10000,
  });

  const bulk = useMutation({
    mutationFn: (decision: "approve" | "reject") =>
      api(BulkResult, "/proposals/bulk", { method: "POST", body: { ids: [...selected], decision } }),
    onSuccess: () => {
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["proposals"] });
    },
  });

  const rows = proposals.data ?? [];
  const selectable = rows.filter((p) => p.state === "pending_review");
  const failures = Object.entries(bulk.data?.results ?? {}).filter(([, v]) => v !== "ok");

  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const age = (iso: string | null) => {
    if (!iso) return "—";
    const m = Math.round((new Date(iso).getTime() - proposals.dataUpdatedAt) / 60000);
    return m >= 0 ? `${m < 90 ? `${m} min` : `${(m / 60).toFixed(1)} h`} left` : "overdue";
  };

  return (
    <>
      <PageHeader title="Approval inbox" sub="Money-moving actions the agent proposed. Nothing executes until policy or a reviewer approves.">
        <select aria-label="State filter" className={input} value={state} onChange={(e) => setState(e.target.value)}>
          {STATES.map((s) => (
            <option key={s} value={s}>{s ? s.replace("_", " ") : "all states"}</option>
          ))}
        </select>
        <select aria-label="Action filter" className={input} value={action} onChange={(e) => setAction(e.target.value)}>
          {ACTIONS.map((a) => (
            <option key={a} value={a}>{a ? a.replace("_", " ") : "all actions"}</option>
          ))}
        </select>
        <button className={btnGhost} onClick={() => proposals.refetch()}>Refresh</button>
      </PageHeader>

      {canDecide && selected.size > 0 && (
        <div className="sticky top-2 z-10 flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 shadow-md">
          <span className="text-sm"><b className="num">{selected.size}</b> selected</span>
          <span className="ml-auto" />
          <button className={btnGhost} onClick={() => setSelected(new Set())}>Clear</button>
          <button className={btnDanger} disabled={bulk.isPending} onClick={() => bulk.mutate("reject")}>Reject selected</button>
          <button className={btnPrimary} disabled={bulk.isPending} onClick={() => bulk.mutate("approve")}>Approve selected</button>
        </div>
      )}

      <ErrorNote error={proposals.error ?? bulk.error} />
      {failures.length > 0 && (
        <p role="alert" className="rounded-md border px-3 py-2 text-sm" style={{ color: "var(--s-pending)", background: "var(--s-pending-bg)", borderColor: "var(--s-pending)" }}>
          {failures.length} item(s) could not be decided: {failures.map(([id, v]) => `${id.slice(0, 8)} (${v})`).join(", ")}
        </p>
      )}

      <div className={`grid gap-4 lg:items-start ${(escalated.data?.length ?? 0) > 0 ? "lg:grid-cols-[1fr_280px]" : ""}`}>
        <div className="overflow-x-auto rounded-lg border border-line bg-surface">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-line bg-sunken/60 text-xs uppercase tracking-wider text-muted">
              <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:font-medium">
                <th className="w-8">
                  {canDecide && (
                    <input
                      type="checkbox"
                      aria-label="Select all pending"
                      checked={selectable.length > 0 && selectable.every((p) => selected.has(p.id))}
                      onChange={(e) => setSelected(e.target.checked ? new Set(selectable.map((p) => p.id)) : new Set())}
                    />
                  )}
                </th>
                <th>Action</th><th className="text-right">Amount</th><th>Risk</th><th>State</th><th>Reason</th><th>SLA</th><th />
              </tr>
            </thead>
            <tbody className="[&>tr>td]:px-3 [&>tr>td]:py-2.5">
              {proposals.isLoading && [0, 1, 2, 3].map((i) => (
                <tr key={i}><td colSpan={8}><Skeleton className="h-5 w-full" /></td></tr>
              ))}
              {rows.map((p) => (
                <tr key={p.id} className="cursor-pointer border-t border-line hover:bg-sunken/50" onClick={() => router.push(`/proposals/${p.id}`)}>
                  <td onClick={(e) => e.stopPropagation()}>
                    {canDecide && p.state === "pending_review" && (
                      <input type="checkbox" aria-label={`Select ${p.id}`} checked={selected.has(p.id)} onChange={() => toggle(p.id)} />
                    )}
                  </td>
                  <td className="capitalize">{p.action_type.replace("_", " ")}</td>
                  <td className="text-right font-medium"><Money amount={p.amount} currency={p.currency} /></td>
                  <td><RiskMeter score={p.risk_score} /></td>
                  <td><StateBadge state={p.state} /></td>
                  <td className="max-w-[220px] truncate text-muted">{p.reason}</td>
                  <td className="num whitespace-nowrap text-xs text-muted">{p.state === "pending_review" ? age(p.expires_at) : "—"}</td>
                  <td onClick={(e) => e.stopPropagation()}><Link className="text-accent hover:underline" href={`/proposals/${p.id}`}>Open</Link></td>
                </tr>
              ))}
              {!proposals.isLoading && rows.length === 0 && (
                <tr><td colSpan={8}><EmptyState title="Nothing here" hint="Change the filters, or send a customer message from the Customer chat." /></td></tr>
              )}
            </tbody>
          </table>
        </div>

        {(escalated.data?.length ?? 0) > 0 && (
          <Card title="Needs a human">
            <p className="mb-2 text-xs text-muted">The agent did not draft a proposal for these.</p>
            <ul className="space-y-3 text-sm">
              {escalated.data!.map((t) => (
                <li key={t.id}>
                  <b>{t.customer_ref}</b>
                  <p className="text-muted">{t.message}</p>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  );
}
