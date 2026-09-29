/**
 * Who may sign in, and as what. Deny by default.
 *
 * AUTH_ALLOWLIST is JSON keyed by the IdP's IMMUTABLE user id (GitHub numeric id), never the login name:
 * usernames can be renamed and re-registered by someone else, ids cannot.
 *   {"12345678": [{"tenantId": "1111…", "tenantName": "Mzigo Wallet", "role": "admin"}]}
 */
export const ROLES = ["agent", "reviewer", "admin"] as const;
export type Role = (typeof ROLES)[number];
export type Membership = { tenantId: string; tenantName: string; role: Role };
export type Allowlist = Map<string, Membership[]>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Throws on malformed config: a typo must fail loudly, not silently widen or narrow access. */
export function parseAllowlist(raw: string | undefined): Allowlist {
  const out: Allowlist = new Map();
  if (!raw) return out;
  const data: unknown = JSON.parse(raw);
  if (typeof data !== "object" || data === null || Array.isArray(data)) throw new Error("AUTH_ALLOWLIST must be a JSON object");
  for (const [id, memberships] of Object.entries(data)) {
    if (!/^\d+$/.test(id)) throw new Error(`AUTH_ALLOWLIST key "${id}" must be a numeric user id, not a login name`);
    if (!Array.isArray(memberships)) throw new Error(`AUTH_ALLOWLIST["${id}"] must be an array`);
    out.set(
      id,
      memberships.map((m: unknown) => {
        const { tenantId, tenantName, role } = (m ?? {}) as Record<string, unknown>;
        if (typeof tenantId !== "string" || !UUID.test(tenantId)) throw new Error(`AUTH_ALLOWLIST["${id}"]: bad tenantId`);
        if (typeof tenantName !== "string" || !tenantName) throw new Error(`AUTH_ALLOWLIST["${id}"]: missing tenantName`);
        if (!ROLES.includes(role as Role)) throw new Error(`AUTH_ALLOWLIST["${id}"]: bad role "${String(role)}"`);
        return { tenantId: tenantId.toLowerCase(), tenantName, role: role as Role };
      }),
    );
  }
  return out;
}

export function membershipsFor(list: Allowlist, userId: string | undefined | null): Membership[] {
  return userId ? (list.get(userId) ?? []) : [];
}

export function isAllowed(list: Allowlist, userId: string | undefined | null): boolean {
  return membershipsFor(list, userId).length > 0;
}

/** The only way to get a token: the exact (tenant, role) must be listed for this user. */
export function findMembership(list: Allowlist, userId: string | undefined | null, tenantId: string, role: string): Membership | null {
  return membershipsFor(list, userId).find((m) => m.tenantId === tenantId.toLowerCase() && m.role === role) ?? null;
}

let cached: { raw: string | undefined; list: Allowlist } | null = null;
/** Parsed once per distinct env value. */
export function allowlistFromEnv(env: NodeJS.ProcessEnv = process.env): Allowlist {
  if (!cached || cached.raw !== env.AUTH_ALLOWLIST) cached = { raw: env.AUTH_ALLOWLIST, list: parseAllowlist(env.AUTH_ALLOWLIST) };
  return cached.list;
}
