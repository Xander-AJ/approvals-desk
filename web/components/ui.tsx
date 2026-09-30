import type { ReactNode } from "react";

const STATE_TONE: Record<string, string> = {
  pending_review: "pending",
  approved: "info",
  edited: "info",
  executed: "ok",
  rejected: "bad",
  expired: "idle",
  failed: "bad",
  compensated: "comp",
  proposed: "idle",
};

export function StateBadge({ state }: { state: string }) {
  const t = STATE_TONE[state] ?? "idle";
  return (
    <span
      data-testid="state-badge"
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ color: `var(--s-${t})`, background: `var(--s-${t}-bg)` }}
    >
      <span aria-hidden className="size-1.5 rounded-full" style={{ background: `var(--s-${t})` }} />
      {state.replace("_", " ")}
    </span>
  );
}

export function Card({ title, action, children, className = "" }: { title?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-line bg-surface ${className}`}>
      {title && (
        <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, sub, children }: { title: string; sub?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end gap-x-4 gap-y-2 pb-1">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {sub && <p className="mt-0.5 max-w-2xl text-sm text-muted">{sub}</p>}
      </div>
      {children && <div className="ml-auto flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-md border px-3 py-2 text-sm" style={{ color: "var(--s-bad)", background: "var(--s-bad-bg)", borderColor: "var(--s-bad)" }}>
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}

export function Money({ amount, currency, className = "" }: { amount: string | number; currency: string; className?: string }) {
  return (
    <span className={`num whitespace-nowrap ${className}`}>
      <span className="text-muted">{currency}</span> {Number(amount).toLocaleString()}
    </span>
  );
}

/** 0-100 score as a short bar; tone flips at 40 / 70 so a scan of the column finds the risky ones. */
export function RiskMeter({ score }: { score: number }) {
  const tone = score >= 70 ? "bad" : score >= 40 ? "pending" : "ok";
  return (
    <span className="inline-flex items-center gap-2" title={`Risk ${score} / 100`}>
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-sunken">
        <span className="block h-full rounded-full" style={{ width: `${Math.min(100, score)}%`, background: `var(--s-${tone})` }} />
      </span>
      <span className="num text-xs text-muted">{score}</span>
    </span>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden className={`skeleton ${className}`} />;
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="font-medium">{title}</p>
      {hint && <p className="mt-1 text-sm text-muted">{hint}</p>}
    </div>
  );
}

export const btn =
  "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors active:translate-y-px disabled:pointer-events-none disabled:opacity-40";
export const btnPrimary = `${btn} bg-accent text-accent-ink hover:opacity-90`;
export const btnGhost = `${btn} border border-line bg-surface hover:bg-sunken`;
export const btnDanger = `${btn} border border-danger/40 bg-surface text-danger hover:bg-sunken`;
export const input =
  "rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm placeholder:text-muted disabled:bg-sunken disabled:text-muted";
