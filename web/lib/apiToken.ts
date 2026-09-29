import { createPrivateKey, createPublicKey, type KeyObject } from "node:crypto";
import { calculateJwkThumbprint, exportJWK, SignJWT, type JWK } from "jose";

/** Audience the API requires (AD_JWT_AUDIENCE). Tokens for anything else are refused there. */
export const API_AUDIENCE = "approvals-api";
export const TOKEN_TTL_SECONDS = 15 * 60;

export type Signer = { key: KeyObject; kid: string; jwk: JWK; issuer: string };

/** PEM from an env var: accepts real newlines or literal "\n" (common when pasted into dashboards). */
export function loadPrivateKey(pem: string | undefined): KeyObject {
  if (!pem) throw new Error("API_JWT_PRIVATE_KEY is not set");
  const key = createPrivateKey(pem.includes("\\n") ? pem.replace(/\\n/g, "\n") : pem);
  if (key.asymmetricKeyType !== "rsa") throw new Error("API_JWT_PRIVATE_KEY must be an RSA key");
  if ((key.asymmetricKeyDetails?.modulusLength ?? 0) < 2048) throw new Error("API_JWT_PRIVATE_KEY must be at least 2048 bits");
  return key;
}

/** Public JWK only: the private exponent never leaves this module. `kid` is the RFC 7638 thumbprint. */
export async function makeSigner(privateKey: KeyObject, issuer: string): Promise<Signer> {
  const jwk = await exportJWK(createPublicKey(privateKey));
  const kid = await calculateJwkThumbprint(jwk);
  return { key: privateKey, kid, issuer, jwk: { ...jwk, kid, use: "sig", alg: "RS256" } };
}

export async function mintApiToken(
  signer: Signer,
  claims: { sub: string; tenantId: string; role: string },
  now: Date = new Date(),
): Promise<{ token: string; expiresAt: number }> {
  const iat = Math.floor(now.getTime() / 1000);
  const exp = iat + TOKEN_TTL_SECONDS;
  const token = await new SignJWT({ tenant_id: claims.tenantId, role: claims.role })
    .setProtectedHeader({ alg: "RS256", kid: signer.kid, typ: "JWT" })
    .setSubject(claims.sub)
    .setIssuer(signer.issuer)
    .setAudience(API_AUDIENCE)
    .setIssuedAt(iat)
    .setExpirationTime(exp)
    .sign(signer.key);
  return { token, expiresAt: exp * 1000 };
}

let cached: { pem: string; issuer: string; signer: Promise<Signer> } | null = null;
export function signerFromEnv(env: NodeJS.ProcessEnv = process.env): Promise<Signer> {
  const pem = env.API_JWT_PRIVATE_KEY ?? "";
  const issuer = env.AUTH_ISSUER ?? "";
  if (!issuer) throw new Error("AUTH_ISSUER is not set (must equal the API's AD_JWT_ISSUER, e.g. https://your-app.vercel.app)");
  if (!cached || cached.pem !== pem || cached.issuer !== issuer) {
    cached = { pem, issuer, signer: makeSigner(loadPrivateKey(pem), issuer) };
  }
  return cached.signer;
}
