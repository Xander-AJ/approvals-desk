"use client";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useSyncExternalStore } from "react";
import { getServerSessionRaw, getSessionRaw, parseSession, subscribeSession, type Session } from "./api";

/** Current session (null = signed out, undefined = not read yet). Storage is an external store. */
export function useSession(): Session | null | undefined {
  const raw = useSyncExternalStore(subscribeSession, getSessionRaw, getServerSessionRaw);
  return useMemo(() => (raw === undefined ? undefined : parseSession(raw)), [raw]);
}

/** Returns the session, redirecting to /login once we know there is none. */
export function useRequireSession(): Session | null {
  const router = useRouter();
  const session = useSession();
  useEffect(() => {
    if (session === null) router.replace("/login");
  }, [session, router]);
  return session ?? null;
}
