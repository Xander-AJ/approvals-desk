"use client";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Inbox, LogOut, MessageSquare, Moon, Plug, SlidersHorizontal, Sun } from "lucide-react";
import { signOut as authSignOut } from "next-auth/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { z } from "zod";
import { api, setSession } from "@/lib/api";
import { Proposal } from "@/lib/schemas";
import { useSession } from "@/lib/useSession";

const LINKS = [
  { href: "/", label: "Inbox", icon: Inbox },
  { href: "/chat", label: "Chat simulator", icon: MessageSquare },
  { href: "/policy", label: "Policy", icon: SlidersHorizontal },
  { href: "/metrics", label: "Metrics", icon: BarChart3 },
];

function toggleTheme() {
  const el = document.documentElement;
  const dark = el.dataset.theme ? el.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  el.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("theme", el.dataset.theme); } catch { /* private mode */ }
}

export function Nav() {
  const path = usePathname();
  const router = useRouter();
  const s = useSession();
  const pending = useQuery({
    queryKey: ["proposals", "pending_review", ""],
    queryFn: () => api(z.array(Proposal), "/proposals?state=pending_review"),
    enabled: !!s,
    refetchInterval: 5000,
  });
  const links = [...LINKS, ...(s?.role === "admin" ? [{ href: "/integrations", label: "Integrations", icon: Plug }] : [])];
  const count = pending.data?.length ?? 0;

  return (
    <aside className="flex flex-col gap-1 border-b border-line bg-surface px-3 py-3 md:sticky md:top-0 md:h-screen md:w-56 md:shrink-0 md:border-b-0 md:border-r">
      <Link href="/" className="mb-1 flex items-center gap-2 px-2 py-1 md:mb-4">
        <span aria-hidden className="grid size-6 place-items-center rounded-md bg-accent text-xs font-bold text-accent-ink">A</span>
        <span className="font-semibold tracking-tight">approvals-desk</span>
      </Link>
      <nav aria-label="Main" className="flex gap-1 overflow-x-auto md:flex-col">
        {links.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? path === "/" || path.startsWith("/proposals") : path === href;
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-2 whitespace-nowrap rounded-md px-2 py-1.5 text-sm ${active ? "bg-sunken font-medium" : "text-muted hover:bg-sunken hover:text-ink"}`}
            >
              <Icon className="size-4" aria-hidden />
              {label}
              {href === "/" && count > 0 && (
                <span className="num ml-auto rounded-full px-1.5 text-xs" style={{ color: "var(--s-pending)", background: "var(--s-pending-bg)" }}>
                  {count}
                </span>
              )}
            </Link>
          );
        })}
      </nav>
      <div className="mt-2 flex items-center gap-2 border-t border-line pt-3 text-sm md:mt-auto">
        {s ? (
          <>
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{s.tenantName}</div>
              <div className="text-xs capitalize text-muted">{s.role}</div>
            </div>
            <button aria-label="Toggle theme" className="rounded-md p-1.5 text-muted hover:bg-sunken" onClick={toggleTheme}>
              <Sun className="hidden size-4 dark:block" /><Moon className="size-4 dark:hidden" />
            </button>
            <button
              aria-label="Sign out"
              className="rounded-md p-1.5 text-muted hover:bg-sunken"
              onClick={async () => {
                const oidc = s.auth === "oidc";
                setSession(null);
                // End the GitHub-backed Auth.js session too, or the cookie would sign the same browser straight back in.
                if (oidc) await authSignOut({ redirect: false });
                router.push("/login");
              }}
            >
              <LogOut className="size-4" />
            </button>
          </>
        ) : (
          <Link href="/login" className="text-accent underline">Sign in</Link>
        )}
      </div>
    </aside>
  );
}
