"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Metrics } from "@/lib/schemas";
import { useRequireSession } from "@/lib/useSession";
import { Card, ErrorNote } from "@/components/ui";

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
  return (
    <>
      <h1 className="text-xl font-semibold">Metrics</h1>
      <ErrorNote error={q.error} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map((t) => (
          <Card key={t.label}>
            <div className="text-sm text-zinc-500">{t.label}</div>
            <div className="mt-1 text-3xl font-semibold">{t.value}</div>
            <div className="mt-1 text-xs text-zinc-400">{t.hint}</div>
          </Card>
        ))}
      </div>
    </>
  );
}
