"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { z } from "zod";
import { api } from "@/lib/api";
import { Integrations } from "@/lib/schemas";
import { useRequireSession } from "@/lib/useSession";
import { btnDanger, btnGhost, btnPrimary, Card, ErrorNote, input } from "@/components/ui";

const Ok = z.object({ status: z.string() });

export default function IntegrationsPage() {
  const session = useRequireSession();
  const qc = useQueryClient();
  const isAdmin = session?.role === "admin";
  const q = useQuery({ queryKey: ["integrations"], queryFn: () => api(Integrations, "/integrations"), enabled: isAdmin });
  const refresh = () => qc.invalidateQueries({ queryKey: ["integrations"] });

  const [url, setUrl] = useState("");
  const [channel, setChannel] = useState("");
  const [slackUser, setSlackUser] = useState("");
  const [role, setRole] = useState<"reviewer" | "admin">("reviewer");
  const [label, setLabel] = useState("");

  const save = useMutation({
    mutationFn: () => api(Ok, "/integrations/slack", { method: "PUT", body: { webhook_url: url, channel_label: channel || null } }),
    onSuccess: () => { setUrl(""); refresh(); },
  });
  const remove = useMutation({ mutationFn: () => api(Ok, "/integrations/slack", { method: "DELETE" }), onSuccess: refresh });
  const test = useMutation({ mutationFn: () => api(Ok, "/integrations/slack/test", { method: "POST" }) });
  const addIdentity = useMutation({
    mutationFn: () => api(z.object({ id: z.string() }), "/integrations/slack/identities", { method: "POST", body: { slack_user_id: slackUser, role, label } }),
    onSuccess: () => { setSlackUser(""); setLabel(""); refresh(); },
  });
  const removeIdentity = useMutation({
    mutationFn: (id: string) => api(Ok, `/integrations/slack/identities/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  if (session && !isAdmin) return <p className="text-sm text-muted">Only admins can manage integrations.</p>;
  const d = q.data;

  return (
    <>
      <h1 className="text-xl font-semibold tracking-tight">Slack approvals</h1>
      <p className="text-sm text-muted">
        New proposals are posted to Slack with Approve / Reject buttons. Clicks are verified with Slack&apos;s signature and only
        Slack users mapped below can decide, so channel membership alone grants nothing.
      </p>
      <ErrorNote error={q.error} />

      <Card title="Incoming webhook">
        <div className="mb-3 text-sm">
          {d?.slack.configured ? (
            <span>Connected <code className="rounded bg-sunken px-1">{d.slack.webhook_hint}</code>{d.slack.channel_label ? ` · ${d.slack.channel_label}` : ""}</span>
          ) : (
            <span className="text-muted">Not connected.</span>
          )}
        </div>
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <label className="text-sm">Webhook URL
            <input aria-label="Slack webhook URL" className={`${input} mt-1 block w-96`} type="password" autoComplete="off"
              placeholder="https://hooks.slack.com/services/…" value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
          <label className="text-sm">Channel label
            <input aria-label="Channel label" className={`${input} mt-1 block w-40`} placeholder="#refunds" value={channel} onChange={(e) => setChannel(e.target.value)} />
          </label>
          <button className={btnPrimary} disabled={!url || save.isPending}>Save</button>
          <button type="button" className={btnGhost} disabled={!d?.slack.configured || test.isPending} onClick={() => test.mutate()}>Send test message</button>
          <button type="button" className={btnDanger} disabled={!d?.slack.configured || remove.isPending} onClick={() => remove.mutate()}>Disconnect</button>
        </form>
        <div className="mt-2 space-y-1">
          <ErrorNote error={save.error ?? test.error ?? remove.error} />
          {test.isSuccess && <p className="text-sm text-[color:var(--s-ok)]">Test message sent.</p>}
          {save.isSuccess && <p className="text-sm text-[color:var(--s-ok)]">Saved.</p>}
        </div>
        {d && !d.slack.interactions_enabled && (
          <p role="status" className="mt-3 rounded-md border border-[color:var(--s-pending)] bg-[color:var(--s-pending-bg)] px-3 py-2 text-sm text-[color:var(--s-pending)]">
            Buttons will not work yet: the server has no Slack signing secret (<code>AD_SLACK_SIGNING_SECRET</code>). Messages
            will still be posted with an &quot;Open / edit&quot; link.
          </p>
        )}
      </Card>

      <Card title="Who can decide from Slack">
        <table className="mb-3 w-full text-left text-sm">
          <thead className="text-xs uppercase text-muted"><tr><th>Slack user ID</th><th>Name</th><th>Role</th><th /></tr></thead>
          <tbody>
            {d?.identities.map((i) => (
              <tr key={i.id} className="border-t border-line">
                <td className="py-2 font-mono text-xs">{i.slack_user_id}</td>
                <td>{i.label}</td>
                <td>{i.role}</td>
                <td className="text-right">
                  <button className="text-sm underline" onClick={() => removeIdentity.mutate(i.id)} aria-label={`Remove ${i.slack_user_id}`}>Remove</button>
                </td>
              </tr>
            ))}
            {d && d.identities.length === 0 && <tr><td colSpan={4} className="py-4 text-center text-muted">No Slack users mapped: nobody can decide from Slack.</td></tr>}
          </tbody>
        </table>
        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); addIdentity.mutate(); }}>
          <label className="text-sm">Slack user ID
            <input aria-label="Slack user ID" className={`${input} mt-1 block w-40 font-mono`} placeholder="U0123ABCD" value={slackUser} onChange={(e) => setSlackUser(e.target.value.trim())} />
          </label>
          <label className="text-sm">Name
            <input aria-label="Name" className={`${input} mt-1 block w-40`} value={label} onChange={(e) => setLabel(e.target.value)} />
          </label>
          <label className="text-sm">Role
            <select aria-label="Role" className={`${input} mt-1 block`} value={role} onChange={(e) => setRole(e.target.value as typeof role)}>
              <option>reviewer</option><option>admin</option>
            </select>
          </label>
          <button className={btnPrimary} disabled={!slackUser || addIdentity.isPending}>Add</button>
        </form>
        <div className="mt-2"><ErrorNote error={addIdentity.error ?? removeIdentity.error} /></div>
      </Card>
    </>
  );
}
