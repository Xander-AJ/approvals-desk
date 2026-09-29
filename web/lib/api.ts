import type { z } from "zod";

const KEY = "approvals-desk.session";
export type Session = {
  token: string;
  tenantId: string;
  tenantName: string;
  role: string;
  user: string;
  /** ms epoch; present for OIDC sessions, whose API tokens are short-lived and silently refreshed. */
  expiresAt?: number;
  auth?: "dev" | "oidc";
};

const listeners = new Set<() => void>();

/** Raw stored value; `undefined` on the server / before the client has read storage. */
export function getSessionRaw(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}
export const getServerSessionRaw = (): string | null | undefined => undefined;
export function subscribeSession(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}
export function parseSession(raw: string | null | undefined): Session | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}
export function getSession(): Session | null {
  return parseSession(getSessionRaw());
}
export function setSession(s: Session | null) {
  try {
    if (s) window.localStorage.setItem(KEY, JSON.stringify(s));
    else window.localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: session lasts for this page view only */
  }
  listeners.forEach((l) => l());
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let refreshing: Promise<Session | null> | null = null;

/** Exchanges the Auth.js cookie session for a new API token. One in-flight refresh is shared by all callers. */
async function refresh(s: Session): Promise<Session | null> {
  refreshing ??= (async () => {
    try {
      const r = await fetch("/api/api-token", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ tenantId: s.tenantId, role: s.role }),
      });
      if (!r.ok) {
        setSession(null); // signed out, or no longer allowlisted: back to /login
        return null;
      }
      const j = (await r.json()) as { token: string; expiresAt: number };
      const next = { ...s, token: j.token, expiresAt: j.expiresAt };
      setSession(next);
      return next;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function fresh(s: Session | null, force = false): Promise<Session | null> {
  if (!s || s.auth !== "oidc") return s;
  if (!force && s.expiresAt && s.expiresAt - Date.now() > 60_000) return s;
  return refresh(s);
}

export async function api<T>(
  schema: z.ZodType<T>,
  path: string,
  init: { method?: string; body?: unknown } = {},
  retried = false,
): Promise<T> {
  const s = await fresh(getSession());
  const res = await fetch(`/api${path}`, {
    method: init.method ?? "GET",
    headers: {
      "content-type": "application/json",
      ...(s ? { authorization: `Bearer ${s.token}` } : {}),
    },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (res.status === 401 && s?.auth === "oidc" && !retried && (await fresh(s, true))) {
    return api(schema, path, init, true); // token rejected (e.g. clock skew or key rotation): one forced refresh
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return schema.parse(await res.json());
}

/** Trace links are shown only when a Jaeger/Tempo UI is configured; a deployment without one gets no dead links. */
export const JAEGER = (process.env.NEXT_PUBLIC_JAEGER_URL ?? "").replace(/\/$/, "");
export const traceUrl = (id: string | null) => (id && JAEGER ? `${JAEGER}/trace/${id}` : null);
