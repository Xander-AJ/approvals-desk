import { signerFromEnv } from "@/lib/apiToken";

export const dynamic = "force-dynamic";

/** Public verification key(s) for the API tokens we mint. The API's AD_JWT_JWKS_URL points here. */
export async function GET() {
  try {
    const { jwk } = await signerFromEnv();
    return Response.json({ keys: [jwk] }, { headers: { "Cache-Control": "public, max-age=300" } });
  } catch {
    return Response.json({ detail: "signing key is not configured" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
