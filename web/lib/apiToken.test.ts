import { generateKeyPairSync } from "node:crypto";
import { calculateJwkThumbprint, createLocalJWKSet, decodeProtectedHeader, jwtVerify } from "jose";
import { describe, expect, it } from "vitest";
import { API_AUDIENCE, loadPrivateKey, makeSigner, mintApiToken, TOKEN_TTL_SECONDS } from "./apiToken";

const ISS = "https://console.example.com";
const TENANT = "11111111-1111-1111-1111-111111111111";
const pem = (bits = 2048) =>
  generateKeyPairSync("rsa", { modulusLength: bits }).privateKey.export({ type: "pkcs8", format: "pem" }).toString();

describe("loadPrivateKey", () => {
  it("accepts real newlines and literal \\n (pasted into a dashboard)", () => {
    const p = pem();
    expect(loadPrivateKey(p).asymmetricKeyType).toBe("rsa");
    expect(loadPrivateKey(p.trim().replace(/\n/g, "\\n")).asymmetricKeyType).toBe("rsa");
  });

  it("rejects missing, non-RSA and weak keys", () => {
    expect(() => loadPrivateKey(undefined)).toThrow(/not set/);
    const ec = generateKeyPairSync("ec", { namedCurve: "P-256" }).privateKey.export({ type: "pkcs8", format: "pem" }).toString();
    expect(() => loadPrivateKey(ec)).toThrow(/RSA/);
    expect(() => loadPrivateKey(pem(1024))).toThrow(/2048/);
  });
});

describe("signer and JWKS", () => {
  it("publishes only the public key, with a thumbprint kid", async () => {
    const s = await makeSigner(loadPrivateKey(pem()), ISS);
    for (const priv of ["d", "p", "q", "dp", "dq", "qi"]) expect(s.jwk).not.toHaveProperty(priv);
    expect(s.jwk).toMatchObject({ kty: "RSA", use: "sig", alg: "RS256", kid: s.kid });
    expect(s.kid).toBe(await calculateJwkThumbprint({ kty: "RSA", n: s.jwk.n!, e: s.jwk.e! }));
  });
});

describe("mintApiToken", () => {
  it("issues an RS256 token the API's checks would accept (iss, aud, exp, sub, tenant_id, role, kid)", async () => {
    const s = await makeSigner(loadPrivateKey(pem()), ISS);
    const now = new Date();
    const { token, expiresAt } = await mintApiToken(s, { sub: "github:12345", tenantId: TENANT, role: "reviewer" }, now);

    expect(decodeProtectedHeader(token)).toMatchObject({ alg: "RS256", kid: s.kid, typ: "JWT" });
    const { payload } = await jwtVerify(token, createLocalJWKSet({ keys: [s.jwk] }), { issuer: ISS, audience: API_AUDIENCE });
    expect(payload).toMatchObject({ sub: "github:12345", tenant_id: TENANT, role: "reviewer", iss: ISS, aud: API_AUDIENCE });
    expect(payload.exp! - payload.iat!).toBe(TOKEN_TTL_SECONDS);
    expect(expiresAt).toBe(payload.exp! * 1000);
    expect(expiresAt).toBeGreaterThan(now.getTime());
  });

  it("is rejected under a different key, audience or issuer, and once expired", async () => {
    const s = await makeSigner(loadPrivateKey(pem()), ISS);
    const other = await makeSigner(loadPrivateKey(pem()), ISS);
    const { token } = await mintApiToken(s, { sub: "u", tenantId: TENANT, role: "admin" });
    const jwks = createLocalJWKSet({ keys: [s.jwk] });

    await expect(jwtVerify(token, createLocalJWKSet({ keys: [{ ...other.jwk, kid: s.kid }] }), { issuer: ISS })).rejects.toThrow();
    await expect(jwtVerify(token, jwks, { issuer: ISS, audience: "another-service" })).rejects.toThrow();
    await expect(jwtVerify(token, jwks, { issuer: "https://evil.example.com" })).rejects.toThrow();

    const old = await mintApiToken(s, { sub: "u", tenantId: TENANT, role: "admin" }, new Date(Date.now() - 3600_000));
    await expect(jwtVerify(old.token, jwks, { issuer: ISS, audience: API_AUDIENCE })).rejects.toThrow(/exp/);
  });
});
