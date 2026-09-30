# Deployment: Vercel (web) + Railway (backend)

Live: web `https://approvals-desk.vercel.app`, API `https://api-production-aa7da.up.railway.app` (JWT-gated).

```
browser ──► Vercel (Next.js) ──/api/* fallback rewrite──► Railway api ─┬─► Postgres (RLS, app_user)
   │            │  Auth.js + GitHub                          │        ├─► Redis (arq queue)
   │            │  mints 15-min RS256 API tokens             │        └─► sandbox (private network, keyed)
   │            └─ /jwks.json (public key) ◄── fetched by api, cached      worker (private): resumes runs, SLA, outbox
```

## How sign-in works
1. Auth.js authenticates with GitHub. Access is **deny by default**: the GitHub numeric id must be in `AUTH_ALLOWLIST`
   (keyed by id, not login; logins can be re-registered by someone else).
2. The browser calls `/api/api-token` with a `(tenantId, role)` it holds in the allowlist; the Next server signs a 15-minute
   RS256 token (`iss` = `AUTH_ISSUER`, `aud` = `approvals-api`). The API never talks to GitHub.
3. The API verifies tokens against `https://<web>/jwks.json` (cached, one refresh per 30 s, stale keys survive an outage).
   There is no `/dev/token` and no HS256 in this mode (`AD_JWT_SECRET` is unset).

## Vercel (project `approvals-desk`, root `web/`)
| Variable | Value |
|---|---|
| `AUTH_SECRET` | random 32+ bytes (sensitive) |
| `AUTH_URL`, `AUTH_ISSUER` | `https://approvals-desk.vercel.app` (the API's `AD_JWT_ISSUER` must equal `AUTH_ISSUER`) |
| `AUTH_GITHUB_ID`, `AUTH_GITHUB_SECRET` | from a GitHub OAuth App (below) |
| `AUTH_ALLOWLIST` | `{"<github numeric id>":[{"tenantId":"…","tenantName":"…","role":"admin"}, …]}` |
| `API_JWT_PRIVATE_KEY` | RSA private key, PKCS8 PEM, ≥ 2048 bits (sensitive; never commit) |
| `API_URL` | Railway API URL. **Baked into the proxy at build time: redeploy after changing it** |
| `NEXT_PUBLIC_JAEGER_URL` | unset: no tracing backend is deployed, so trace links are hidden |

GitHub OAuth App: Homepage `https://approvals-desk.vercel.app`, callback
`https://approvals-desk.vercel.app/api/auth/callback/github`. Find a numeric id with `gh api users/<login> --jq .id`.

Add or remove a person: edit `AUTH_ALLOWLIST` (`vercel env add … production --force`), then `vercel deploy --prod`.
Rotate the signing key: set a new `API_JWT_PRIVATE_KEY`, redeploy. Tokens signed by the old key stop verifying at once
(the API refetches within 30 s); users simply sign in again.

## Railway (project `approvals-desk`: Postgres, Redis, `sandbox`, `api`, `worker`)
One backend image, two roles (`backend/scripts/serve.sh`). All services build from the repo root with
`RAILWAY_DOCKERFILE_PATH`; deploy with `railway up --service <name>` from the repo root.

| Service | Key variables |
|---|---|
| `api` | `SERVICE_ROLE=api`, `RUN_MIGRATIONS=1`, `RUN_SEED=1` (demo tenants), `PORT=8000`, `MIGRATION_DATABASE_URL` (owner), `APP_DB_PASSWORD`, `AD_DATABASE_URL` (`app_user`, RLS-bound) |
| `worker` | `SERVICE_ROLE=worker` (waits for the migrated schema, then runs arq) |
| both | `AD_CHECKPOINT_DSN`, `AD_REDIS_URL` (`${{Redis.REDIS_URL}}`), `AD_SANDBOX_URL=http://sandbox.railway.internal:8001`, `AD_SANDBOX_API_KEY`, `AD_JWT_JWKS_URL`, `AD_JWT_ISSUER`, `AD_JWT_AUDIENCE=approvals-api`, `AD_DEV_AUTH=false`, `AD_ASYNC_RESUME=true`, `AD_LLM_PROVIDER=fake`, `AD_CONSOLE_URL` |
| `sandbox` | `SANDBOX_API_KEY` (same value), `SANDBOX_DATABASE_URL` |

Only `api` has a public domain. `sandbox` and `worker` are reachable only on Railway's private network.

## What this deployment is, and is not
- **Demo data and a fake payments sandbox.** No real money moves. `AD_LLM_PROVIDER=fake` is a rule-based stand-in: for Claude,
  set `AD_LLM_PROVIDER=anthropic` plus `ANTHROPIC_API_KEY` (or `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` for a gateway).
- No tracing backend, no Slack signing secret (buttons disabled until `AD_SLACK_SIGNING_SECRET` is set), no webhook sink.
- The sandbox shares the app database (own tables) and is protected by a shared key only.
- Redis and Postgres use Railway's private network without TLS.
- Secrets live in each platform's variable store. Nothing sensitive is in git (history scanned before the first push).
- The AWS/Terraform path in `infra/` remains valid and unapplied; this Railway setup is the one that has actually been run.

## PR previews

The `preview` job in `.github/workflows/ci.yml` deploys the web app to a Vercel preview for each pull request and
comments the URL. Add repository secrets `VERCEL_TOKEN`, `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` (from
`vercel link` in `web/`, see `.vercel/project.json`); without them the job skips. Previews use the Railway API
configured in the Vercel project's Preview environment variables.
