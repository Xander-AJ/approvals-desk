/**
 * Mint an API token from the environment's signing key, exactly as the /api/api-token route does (minus the GitHub
 * session). For smoke tests and interop checks:
 *   API_JWT_PRIVATE_KEY=… AUTH_ISSUER=https://your-app.vercel.app npx tsx scripts/mint-token.ts <tenantId> <role> [sub]
 */
import { mintApiToken, signerFromEnv } from "../lib/apiToken";

async function main() {
  const [tenantId, role, sub = "github:smoke-test"] = process.argv.slice(2);
  if (!tenantId || !role) {
    console.error("usage: mint-token.ts <tenantId> <role> [sub]");
    process.exit(2);
  }
  const { token } = await mintApiToken(await signerFromEnv(), { sub, tenantId, role });
  console.log(token);
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
