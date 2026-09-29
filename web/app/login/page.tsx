"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { z } from "zod";
import { api, setSession } from "@/lib/api";
import { btnPrimary, Card, ErrorNote, input } from "@/components/ui";

// Seeded demo tenants (backend `python -m app.seed`). Dev-only login: real deployments use OIDC.
const TENANTS = [
  { id: "11111111-1111-1111-1111-111111111111", name: "Mzigo Wallet" },
  { id: "22222222-2222-2222-2222-222222222222", name: "Duka Marketplace" },
];
const ROLES = ["agent", "reviewer", "admin"] as const;

export default function LoginPage() {
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
      setSession({ token, tenantId: tenant.id, tenantName: tenant.name, role, user });
      router.push("/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm">
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
    </div>
  );
}
