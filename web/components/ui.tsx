import type { ReactNode } from "react";

const STATE_STYLE: Record<string, string> = {
  pending_review: "bg-amber-100 text-amber-900",
  approved: "bg-blue-100 text-blue-900",
  edited: "bg-blue-100 text-blue-900",
  executed: "bg-emerald-100 text-emerald-900",
  rejected: "bg-rose-100 text-rose-900",
  expired: "bg-zinc-200 text-zinc-700",
  failed: "bg-rose-200 text-rose-900",
  compensated: "bg-purple-100 text-purple-900",
  proposed: "bg-zinc-100 text-zinc-700",
};

export function StateBadge({ state }: { state: string }) {
  return (
    <span data-testid="state-badge" className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATE_STYLE[state] ?? "bg-zinc-100"}`}>
      {state.replace("_", " ")}
    </span>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm">
      {title && <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">{title}</h2>}
      {children}
    </section>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}

export const btn = "rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-40";
export const btnPrimary = `${btn} bg-zinc-900 text-white hover:bg-zinc-700`;
export const btnGhost = `${btn} border border-zinc-300 bg-white hover:bg-zinc-50`;
export const btnDanger = `${btn} bg-rose-600 text-white hover:bg-rose-500`;
export const input = "rounded-md border border-zinc-300 px-2 py-1.5 text-sm";
