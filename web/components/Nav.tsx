"use client";
import { signOut as authSignOut } from "next-auth/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { setSession } from "@/lib/api";
import { useSession } from "@/lib/useSession";

const LINKS = [
  { href: "/", label: "Inbox" },
  { href: "/chat", label: "Chat simulator" },
  { href: "/policy", label: "Policy" },
  { href: "/metrics", label: "Metrics" },
];

export function Nav() {
  const path = usePathname();
  const router = useRouter();
  const s = useSession();
  return (
    <header className="border-b border-zinc-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
        <span className="font-semibold">approvals-desk</span>
        <nav className="flex gap-4 text-sm">
          {[...LINKS, ...(s?.role === "admin" ? [{ href: "/integrations", label: "Integrations" }] : [])].map((l) => (
            <Link key={l.href} href={l.href} className={path === l.href ? "font-semibold" : "text-zinc-600 hover:text-zinc-900"}>
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm text-zinc-600">
          {s ? (
            <>
              <span>
                {s.tenantName} · <b>{s.role}</b>
              </span>
              <button
                className="underline"
                onClick={async () => {
                  const oidc = s.auth === "oidc";
                  setSession(null);
                  // End the GitHub-backed Auth.js session too, or the cookie would sign the same browser straight back in.
                  if (oidc) await authSignOut({ redirect: false });
                  router.push("/login");
                }}
              >
                Sign out
              </button>
            </>
          ) : (
            <Link href="/login" className="underline">
              Sign in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
