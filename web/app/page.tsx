"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { z } from "zod";
import { api } from "@/lib/api";
import { BulkResult, Proposal, Ticket } from "@/lib/schemas";
import { useRequireSession } from "@/lib/useSession";
import { btnDanger, btnGhost, btnPrimary, Card, ErrorNote, input, StateBadge } from "@/components/ui";

const STATES = ["", "pending_review", "approved", "edited", "executed", "rejected", "expired", "failed", "compensated"];
const ACTIONS = ["", "refund", "reversal", "fee_waiver"];

export default function InboxPage() {
  const session = useRequireSession();
  const qc = useQueryClient();
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

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Approval inbox</h1>
        <select aria-label="State filter" className={input} value={state} onChange={(e) => setState(e.target.value)}>
          {STATES.map((s) => (
            <option key={s} value={s}>{s ? s.replace("_", " ") : "all states"}</option>
          ))}
        </select>
        <select aria-label="Action filter" className={input} value={action} onChange={(e) => setAction(e.target.value)}>
          {ACTIONS.map((a) => (
            <option key={a} value={a}>{a || "all actions"}</option>
          ))}
        </select>
        {canDecide && (
          <div className="ml-auto flex items-center gap-2">
            <span className="text-sm text-zinc-500">{selected.size} selected</span>
            <button className={btnPrimary} disabled={!selected.size || bulk.isPending} onClick={() => bulk.mutate("approve")}>
              Approve selected
            </button>
            <button className={btnDanger} disabled={!selected.size || bulk.isPending} onClick={() => bulk.mutate("reject")}>
              Reject selected
            </button>
          </div>
        )}
      </div>

      <ErrorNote error={proposals.error ?? bulk.error} />
      {failures.length > 0 && (
        <p role="alert" className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {failures.length} item(s) could not be decided: {failures.map(([id, v]) => `${id.slice(0, 8)} (${v})`).join(", ")}
        </p>
      )}

      <Card>
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-zinc-500">
            <tr>
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
              <th>Action</th><th>Amount</th><th>Risk</th><th>State</th><th>Reason</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className="border-t border-zinc-100">
                <td>
                  {canDecide && p.state === "pending_review" && (
                    <input type="checkbox" aria-label={`Select ${p.id}`} checked={selected.has(p.id)} onChange={() => toggle(p.id)} />
                  )}
                </td>
                <td className="py-2">{p.action_type.replace("_", " ")}</td>
                <td>{p.currency} {Number(p.amount).toLocaleString()}</td>
                <td>{p.risk_score}</td>
                <td><StateBadge state={p.state} /></td>
                <td className="max-w-xs truncate text-zinc-600">{p.reason}</td>
                <td><Link className="underline" href={`/proposals/${p.id}`}>Open</Link></td>
              </tr>
            ))}
            {!proposals.isLoading && rows.length === 0 && (
              <tr><td colSpan={7} className="py-6 text-center text-zinc-500">Nothing here.</td></tr>
            )}
          </tbody>
        </table>
      </Card>

      {(escalated.data?.length ?? 0) > 0 && (
        <Card title="Escalated to a human (no proposal drafted)">
          <ul className="space-y-2 text-sm">
            {escalated.data!.map((t) => (
              <li key={t.id} className="flex gap-3">
                <b>{t.customer_ref}</b>
                <span className="text-zinc-700">{t.message}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <p className="text-xs text-zinc-400"><button className={btnGhost} onClick={() => proposals.refetch()}>Refresh</button></p>
    </>
  );
}
