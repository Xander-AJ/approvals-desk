"use client";
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
          {LINKS.map((l) => (
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
                onClick={() => {
                  setSession(null);
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
