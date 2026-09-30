"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Metrics } from "@/lib/schemas";
import { useRequireSession } from "@/lib/useSession";
import { Card, ErrorNote, PageHeader, Skeleton } from "@/components/ui";

const pct = (n: number) => `${(n * 100).toFixed(0)}%`;
function fmtLatency(s: number | null) {
  if (s === null) return "—";
  if (s < 90) return `${s.toFixed(0)} s`;
  if (s < 5400) return `${(s / 60).toFixed(1)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

export default function MetricsPage() {
  const session = useRequireSession();
  const q = useQuery({ queryKey: ["metrics"], queryFn: () => api(Metrics, "/metrics"), enabled: !!session, refetchInterval: 10000 });
  const m = q.data;
  const tiles = m
    ? [
        { label: "Proposals", value: String(m.total), hint: "all time" },
        { label: "Auto-approve rate", value: pct(m.auto_approve_rate), hint: "policy approved without a human" },
        { label: "Override rate", value: pct(m.override_rate), hint: "human edited or rejected the agent's proposal" },
        { label: "Avg approval latency", value: fmtLatency(m.avg_approval_latency_s), hint: "proposal → human decision" },
      ]
    : [];
  const bars = m
    ? [
        { label: "Auto-approved", v: m.auto_approve_rate, tone: "ok" },
        { label: "Overridden by a human", v: m.override_rate, tone: "pending" },
      ]
    : [];
  return (
    <>
      <PageHeader title="Metrics" sub="How much of the queue the agent clears alone, and how often people change its mind." />
      <ErrorNote error={q.error} />
      {!m && !q.error && <Skeleton className="h-28 w-full" />}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map((t) => (
          <Card key={t.label}>
            <div className="text-sm text-muted">{t.label}</div>
            <div className="num mt-1 text-3xl font-semibold">{t.value}</div>
            <div className="mt-1 text-xs text-muted">{t.hint}</div>
          </Card>
        ))}
      </div>
      {m && (
        <Card title="Share of proposals">
          <ul className="space-y-3">
            {bars.map((b) => (
              <li key={b.label} className="grid grid-cols-[180px_1fr_48px] items-center gap-3 text-sm">
                <span>{b.label}</span>
                <span className="h-2 overflow-hidden rounded-full bg-sunken">
                  <span className="block h-full rounded-full" style={{ width: pct(b.v), background: `var(--s-${b.tone})` }} />
                </span>
                <span className="num text-right">{pct(b.v)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
