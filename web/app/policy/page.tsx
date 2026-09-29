"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { z } from "zod";
import { api } from "@/lib/api";
import { Policy } from "@/lib/schemas";
import { useRequireSession } from "@/lib/useSession";
import { btnPrimary, Card, ErrorNote, input } from "@/components/ui";

const ACTIONS = ["refund", "reversal", "fee_waiver"];

export default function PolicyPage() {
  const session = useRequireSession();
  const qc = useQueryClient();
  const isAdmin = session?.role === "admin";
  const q = useQuery({ queryKey: ["policy"], queryFn: () => api(Policy, "/policy"), enabled: !!session });
  const [draft, setForm] = useState<Policy | null>(null);
  const form = draft ?? q.data ?? null; // edits live in `draft`; until then show the server value

  const save = useMutation({
    mutationFn: (p: Policy) =>
      api(z.object({ status: z.string() }), "/policy", { method: "PUT", body: p }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["policy"] }),
  });

  if (!form) return <ErrorNote error={q.error} />;
  const set = <K extends keyof Policy>(k: K, v: Policy[K]) => setForm({ ...form, [k]: v });

  return (
    <>
      <h1 className="text-xl font-semibold">Tenant policy</h1>
      {!isAdmin && <p className="text-sm text-zinc-500">Read-only: only admins can change thresholds.</p>}
      <Card>
        <form
          className="grid max-w-md gap-3 text-sm"
          onSubmit={(e) => { e.preventDefault(); save.mutate(form); }}
        >
          <label>Auto-approve up to (KES)
            <input className={`${input} mt-1 w-full`} disabled={!isAdmin} inputMode="decimal" value={form.auto_approve_max} onChange={(e) => set("auto_approve_max", e.target.value)} />
          </label>
          <label>Hard limit (KES) — above this is blocked, even for reviewers
            <input className={`${input} mt-1 w-full`} disabled={!isAdmin} inputMode="decimal" value={form.hard_limit} onChange={(e) => set("hard_limit", e.target.value)} />
          </label>
          <label>Max risk score for auto-approve (0–100)
            <input type="number" min={0} max={100} className={`${input} mt-1 w-full`} disabled={!isAdmin} value={form.max_auto_risk} onChange={(e) => set("max_auto_risk", Number(e.target.value))} />
          </label>
          <label>Review SLA (minutes)
            <input type="number" min={1} className={`${input} mt-1 w-full`} disabled={!isAdmin} value={form.sla_minutes} onChange={(e) => set("sla_minutes", Number(e.target.value))} />
          </label>
          <fieldset>
            <legend>Allowed actions</legend>
            <div className="mt-1 flex gap-4">
              {ACTIONS.map((a) => (
                <label key={a} className="flex items-center gap-1">
                  <input type="checkbox" disabled={!isAdmin} checked={form.allowed_actions.includes(a)}
                    onChange={(e) => set("allowed_actions", e.target.checked ? [...form.allowed_actions, a] : form.allowed_actions.filter((x) => x !== a))} />
                  {a.replace("_", " ")}
                </label>
              ))}
            </div>
          </fieldset>
          <ErrorNote error={save.error} />
          {save.isSuccess && <p className="text-emerald-700">Saved.</p>}
          {isAdmin && <button className={btnPrimary} disabled={save.isPending}>Save policy</button>}
        </form>
      </Card>
    </>
  );
}
