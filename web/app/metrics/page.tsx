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
  const MIX = [
    { key: "auto_approved", label: "Auto-approved", color: "var(--s-ok)" },
    { key: "approved", label: "Approved", color: "var(--s-info)" },
    { key: "edited", label: "Edited", color: "var(--s-pending)" },
    { key: "rejected", label: "Rejected", color: "var(--s-bad)" },
    { key: "expired", label: "Expired", color: "var(--s-idle)" },
  ] as const;
  const mixTotal = m ? MIX.reduce((n, x) => n + m.decisions[x.key], 0) : 0;
  const days = m?.latency_by_day ?? [];
  const maxLat = Math.max(1, ...days.map((d) => d.avg_s));
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
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Decision mix">
            {mixTotal === 0 ? (
              <p className="text-sm text-muted">No decided proposals yet.</p>
            ) : (
              <>
                <div role="img" aria-label={MIX.map((x) => `${x.label} ${m.decisions[x.key]}`).join(", ")} className="flex h-3 overflow-hidden rounded-full bg-sunken">
                  {MIX.map((x) => m.decisions[x.key] > 0 && <span key={x.key} style={{ width: pct(m.decisions[x.key] / mixTotal), background: x.color }} />)}
                </div>
                <ul className="mt-4 space-y-2 text-sm">
                  {MIX.map((x) => (
                    <li key={x.key} className="flex items-center gap-2">
                      <span aria-hidden className="size-2 rounded-full" style={{ background: x.color }} />
                      <span>{x.label}</span>
                      <span className="num ml-auto">{m.decisions[x.key]}</span>
                      <span className="num w-10 text-right text-muted">{pct(m.decisions[x.key] / mixTotal)}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Card>
          <Card title="Human decision latency by day">
            {days.length === 0 ? (
              <p className="text-sm text-muted">No human decisions yet.</p>
            ) : (
              <ul className="space-y-2">
                {days.map((d) => (
                  <li key={d.day} className="grid grid-cols-[64px_1fr_72px] items-center gap-3 text-sm">
                    <span className="num text-muted">{d.day.slice(5)}</span>
                    <span className="h-2 overflow-hidden rounded-full bg-sunken">
                      <span className="block h-full rounded-full bg-accent" style={{ width: `${(d.avg_s / maxLat) * 100}%` }} />
                    </span>
                    <span className="num text-right">{fmtLatency(d.avg_s)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
