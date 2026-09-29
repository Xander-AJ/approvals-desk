import { defineConfig } from "@playwright/test";

// Needs the backend stack: `docker compose up -d && docker compose exec api python -m app.seed`.
export default defineConfig({
  testDir: "./e2e",
  workers: 1, // tests share one seeded tenant and ledger
  timeout: 60_000,
  expect: { timeout: 30_000 }, // approval executes asynchronously on the worker
  reporter: [["list"]],
  use: { baseURL: "http://localhost:3100", trace: "retain-on-failure" },
  webServer: {
    command: "npm run dev -- -p 3100",
    url: "http://localhost:3100/login",
    reuseExistingServer: true,
    env: {
      API_URL: process.env.API_URL ?? "http://localhost:8000",
      // OIDC is the default; the e2e suite drives the dev issuer (local compose only, never deployed).
      NEXT_PUBLIC_AUTH_MODE: "dev",
      AUTH_SECRET: "e2e-only-not-a-real-secret",
    },
  },
});
