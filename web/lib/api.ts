import type { z } from "zod";

const KEY = "approvals-desk.session";
export type Session = { token: string; tenantId: string; tenantName: string; role: string; user: string };

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

export async function api<T>(
  schema: z.ZodType<T>,
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const s = getSession();
  const res = await fetch(`/api${path}`, {
    method: init.method ?? "GET",
    headers: {
      "content-type": "application/json",
      ...(s ? { authorization: `Bearer ${s.token}` } : {}),
    },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
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

export const JAEGER = process.env.NEXT_PUBLIC_JAEGER_URL ?? "http://localhost:16686";
export const traceUrl = (id: string | null) => (id ? `${JAEGER}/trace/${id}` : null);
