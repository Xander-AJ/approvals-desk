"use client";
import { useQuery } from "@tanstack/react-query";
import { signIn as authSignIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { z } from "zod";
import { api, setSession } from "@/lib/api";
import { AUTH_MODE } from "@/lib/authMode";
import { btnGhost, btnPrimary, Card, ErrorNote, input } from "@/components/ui";

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-sm pt-[10vh]">
      <div className="mb-6"><h1 className="text-2xl font-semibold tracking-tight">approvals-desk</h1><p className="mt-1 text-sm text-muted">Review and approve the money movements your support agent proposes.</p></div>
      <Suspense fallback={null}>{AUTH_MODE === "dev" ? <DevLogin /> : <OidcLogin />}</Suspense>
    </div>
  );
}

// ---------------------------------------------------------------------------------- OIDC (GitHub via Auth.js)
const Memberships = z.object({
  user: z.string(),
  name: z.string().nullable(),
  memberships: z.array(z.object({ tenantId: z.string(), tenantName: z.string(), role: z.string() })),
});
const Minted = z.object({ token: z.string(), expiresAt: z.number(), tenantId: z.string(), tenantName: z.string(), role: z.string(), user: z.string() });

function OidcLogin() {
  const router = useRouter();
  const params = useSearchParams();
  const denied = params.get("error");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const me = useQuery({
    queryKey: ["memberships"],
    queryFn: async () => {
      const r = await fetch("/api/memberships");
      if (r.status === 401) return null; // not signed in with GitHub yet
      if (!r.ok) throw new Error(`could not load your access (${r.status})`);
      return Memberships.parse(await r.json());
    },
  });

  async function continueAs(tenantId: string, role: string) {
    setBusy(`${tenantId}:${role}`);
    setError(null);
    try {
      const r = await fetch("/api/api-token", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ tenantId, role }),
      });
      if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? `sign-in failed (${r.status})`);
      const m = Minted.parse(await r.json());
      setSession({ token: m.token, tenantId: m.tenantId, tenantName: m.tenantName, role: m.role, user: m.user, expiresAt: m.expiresAt, auth: "oidc" });
      router.push("/");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card title="Sign in">
      {denied && (
        <p role="alert" className="mb-3 rounded-md border border-danger/40 bg-[color:var(--s-bad-bg)] px-3 py-2 text-sm text-danger">
          {denied === "AccessDenied"
            ? "That GitHub account is not authorized for this console. Ask an admin to add it."
            : "Sign-in failed. Please try again."}
        </p>
      )}
      <ErrorNote error={error ?? me.error} />
      {me.data === null && (
        <button className={btnPrimary} onClick={() => authSignIn("github", { callbackUrl: "/login" })}>
          Sign in with GitHub
        </button>
      )}
      {me.data && (
        <div className="space-y-2">
          <p className="text-sm text-muted">
            Signed in as <b>{me.data.name ?? me.data.user}</b>. Choose how to act:
          </p>
          {me.data.memberships.map((m) => (
            <button
              key={`${m.tenantId}:${m.role}`}
              className={`${btnGhost} block w-full text-left`}
              disabled={busy !== null}
              onClick={() => continueAs(m.tenantId, m.role)}
            >
              {m.tenantName} · <b>{m.role}</b>
            </button>
          ))}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------------- dev (local demos + e2e only)
const TENANTS = [
  { id: "11111111-1111-1111-1111-111111111111", name: "Mzigo Wallet" },
  { id: "22222222-2222-2222-2222-222222222222", name: "Duka Marketplace" },
];
const ROLES = ["agent", "reviewer", "admin"] as const;

function DevLogin() {
  const router = useRouter();
  const [tenant, setTenant] = useState(TENANTS[0]);
  const [role, setRole] = useState<(typeof ROLES)[number]>("reviewer");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const user = `${role}@${tenant.name.toLowerCase().replace(/\s+/g, "-")}`;
      const { token } = await api(z.object({ token: z.string() }), "/dev/token", {
        method: "POST",
        body: { tenant_id: tenant.id, role, user },
      });
      setSession({ token, tenantId: tenant.id, tenantName: tenant.name, role, user, auth: "dev" });
      router.push("/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Sign in (dev)">
      <form onSubmit={signIn} className="space-y-3">
        <label className="block text-sm">
          Tenant
          <select className={`${input} mt-1 w-full`} value={tenant.id} onChange={(e) => setTenant(TENANTS.find((t) => t.id === e.target.value)!)}>
            {TENANTS.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          Role
          <select className={`${input} mt-1 w-full`} value={role} onChange={(e) => setRole(e.target.value as typeof role)}>
            {ROLES.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <ErrorNote error={error} />
        <button className={btnPrimary} disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </Card>
  );
}
