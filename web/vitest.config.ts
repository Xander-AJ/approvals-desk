import { defineConfig } from "vitest/config";

export default defineConfig({
  // Unit tests only: e2e/ is Playwright's, run by `npx playwright test`.
  test: { include: ["lib/**/*.test.ts"] },
});
