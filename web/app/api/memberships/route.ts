import { auth, type AppSession } from "@/auth";
import { allowlistFromEnv, membershipsFor } from "@/lib/authz";

export const dynamic = "force-dynamic";

/** The (tenant, role) pairs the signed-in GitHub user may assume. */
export async function GET() {
  const session = (await auth()) as AppSession | null;
  if (!session?.ghId) return Response.json({ detail: "not signed in" }, { status: 401, headers: { "Cache-Control": "no-store" } });
  return Response.json(
    { user: `github:${session.ghId}`, name: session.user?.name ?? null, memberships: membershipsFor(allowlistFromEnv(), session.ghId) },
    { headers: { "Cache-Control": "no-store" } },
  );
}
