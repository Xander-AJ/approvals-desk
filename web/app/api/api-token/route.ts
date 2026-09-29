import { auth, type AppSession } from "@/auth";
import { mintApiToken, signerFromEnv } from "@/lib/apiToken";
import { allowlistFromEnv, findMembership } from "@/lib/authz";

export const dynamic = "force-dynamic";
const NO_STORE = { "Cache-Control": "no-store" };
const fail = (status: number, detail: string) => Response.json({ detail }, { status, headers: NO_STORE });

/**
 * Exchange the Auth.js session for a short-lived API token, but only for a (tenant, role) that the allowlist grants
 * this exact user. The API never sees GitHub; it trusts our signature (verified via /jwks.json).
 */
export async function POST(req: Request) {
  // CSRF: a cross-site page must not be able to make the browser mint tokens with the user's cookie.
  const origin = req.headers.get("origin");
  if (origin && origin !== new URL(req.url).origin) return fail(403, "cross-origin request refused");
  if (!req.headers.get("content-type")?.toLowerCase().startsWith("application/json")) return fail(415, "expected application/json");

  const session = (await auth()) as AppSession | null;
  if (!session?.ghId) return fail(401, "not signed in");

  let body: { tenantId?: unknown; role?: unknown };
  try {
    body = await req.json();
  } catch {
    return fail(400, "invalid JSON");
  }
  if (typeof body.tenantId !== "string" || typeof body.role !== "string") return fail(400, "tenantId and role are required");

  const membership = findMembership(allowlistFromEnv(), session.ghId, body.tenantId, body.role);
  if (!membership) return fail(403, "you are not permitted to act with that tenant and role");

  const sub = `github:${session.ghId}`;
  const { token, expiresAt } = await mintApiToken(await signerFromEnv(), { sub, tenantId: membership.tenantId, role: membership.role });
  return Response.json(
    { token, expiresAt, tenantId: membership.tenantId, tenantName: membership.tenantName, role: membership.role, user: sub },
    { headers: NO_STORE },
  );
}
