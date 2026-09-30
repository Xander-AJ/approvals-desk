import { createHmac } from "node:crypto";
import { expect, type Page, test } from "@playwright/test";

const SANDBOX = process.env.SANDBOX_URL ?? "http://localhost:8001";
const SANDBOX_HEADERS = { "X-Sandbox-Key": process.env.SANDBOX_API_KEY ?? "compose-dev-sandbox-key-0123456789" };

async function login(page: Page, role: "agent" | "reviewer" | "admin", tenant = "Mzigo Wallet") {
  await page.goto("/login");
  await page.getByLabel("Tenant").selectOption({ label: tenant });
  await page.getByLabel("Role").selectOption(role);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Approval inbox" })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
}

/** A customer writes in; returns the id of the proposal the agent drafted. */
async function customerReportsDoubleCharge(page: Page, customer = "wanjiku"): Promise<string> {
  await login(page, "agent");
  await page.goto("/chat");
  await page.getByLabel("Customer").selectOption(customer);
  await page.getByLabel("Message").fill("nimekatwa mara mbili KES 1,200 Java House");
  await page.getByRole("button", { name: "Send" }).click();
  const link = page.getByRole("link", { name: "View proposal" });
  await expect(link).toBeVisible();
  const id = (await link.getAttribute("href"))!.split("/").pop()!;
  await page.goto("/");
  await signOut(page);
  return id;
}

async function ledgerCount(page: Page) {
  return (await (await page.request.get(`${SANDBOX}/ledger`, { headers: SANDBOX_HEADERS })).json()).length as number;
}

test("reviewer approves: exactly one refund executes and the timeline links traces", async ({ page }) => {
  const before = await ledgerCount(page);
  const id = await customerReportsDoubleCharge(page);
  await login(page, "reviewer");
  await page.goto(`/proposals/${id}`);
  await expect(page.getByTestId("state-badge")).toHaveText("pending review");
  await expect(page.getByText("Java House").first()).toBeVisible(); // reason
  await expect(page.getByText(/charge t?\w+-c1 of 1200/)).toBeVisible(); // evidence from the ledger
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByTestId("state-badge")).toHaveText("executed");
  expect(await ledgerCount(page)).toBe(before + 1);
  const trace = page.getByRole("link", { name: /trace ↗/ }).first();
  await expect(trace).toHaveAttribute("href", /\/trace\/[0-9a-f]{32}$/);
  for (const ev of ["proposed", "pending review", "approved", "executed"]) {
    await expect(page.locator("ol").getByText(ev, { exact: true })).toBeVisible();
  }
});

test("reviewer edits the amount: diff shown and the EDITED amount is what executes", async ({ page }) => {
  const id = await customerReportsDoubleCharge(page, "otieno");
  await login(page, "reviewer");
  await page.goto(`/proposals/${id}`);
  await page.getByRole("button", { name: "Edit amount" }).click();
  await page.getByLabel("New amount").fill("900");
  await page.getByRole("button", { name: /Save/ }).click();
  await expect(page.getByTestId("state-badge")).toHaveText("executed");
  const diff = page.locator("section", { hasText: "Reviewer edit" });
  await expect(diff.locator("s")).toHaveText("1200.00");
  await expect(diff.locator("b")).toHaveText("900.00");
  const ledger = await (await page.request.get(`${SANDBOX}/ledger`, { headers: SANDBOX_HEADERS })).json();
  expect(ledger.at(-1).amount).toBe("900.00");
});

test("reviewer rejects: nothing executes", async ({ page }) => {
  const before = await ledgerCount(page);
  const id = await customerReportsDoubleCharge(page);
  await login(page, "reviewer");
  await page.goto(`/proposals/${id}`);
  await page.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByTestId("state-badge")).toHaveText("rejected");
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  expect(await ledgerCount(page)).toBe(before);
});

test("bulk approve from the inbox executes each selected proposal once", async ({ page }) => {
  const before = await ledgerCount(page);
  const a = await customerReportsDoubleCharge(page);
  const b = await customerReportsDoubleCharge(page, "otieno");
  await login(page, "reviewer");
  await page.getByLabel(`Select ${a}`).check();
  await page.getByLabel(`Select ${b}`).check();
  await page.getByRole("button", { name: "Approve selected" }).click();
  await expect.poll(() => ledgerCount(page), { timeout: 30_000 }).toBe(before + 2);
});

test("agents cannot decide; only admins can edit policy", async ({ page }) => {
  const id = await customerReportsDoubleCharge(page);
  await login(page, "agent");
  await page.goto(`/proposals/${id}`);
  await expect(page.getByTestId("state-badge")).toHaveText("pending review");
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await signOut(page);

  await login(page, "reviewer");
  await page.goto("/policy");
  await expect(page.getByText("Read-only")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save policy" })).toHaveCount(0);
  await signOut(page);

  await login(page, "admin");
  await page.goto("/policy");
  await expect(page.getByRole("button", { name: "Save policy" })).toBeVisible();
});

test("unauthenticated visit redirects to login; metrics render", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await login(page, "reviewer");
  await page.goto("/metrics");
  await expect(page.getByText("Auto-approve rate")).toBeVisible();
  await expect(page.getByText("Avg approval latency")).toBeVisible();
});

test("admin changes the review SLA and it persists; invalid input is rejected by the API", async ({ page }) => {
  await login(page, "admin");
  await page.goto("/policy");
  const sla = page.getByLabel("Review SLA (minutes)");
  await expect(sla).toHaveValue("60");
  await sla.fill("61");
  await page.getByRole("button", { name: "Save policy" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Review SLA (minutes)")).toHaveValue("61");

  await page.getByLabel("Auto-approve up to (KES)").fill("-5"); // API rejects negatives
  await page.getByRole("button", { name: "Save policy" }).click();
  await expect(page.locator("p[role=alert]")).toBeVisible();

  await page.reload(); // restore for other tests / reruns
  await page.getByLabel("Review SLA (minutes)").fill("60");
  await page.getByRole("button", { name: "Save policy" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
});


// ---------------------------------------------------------------- compensation
test("admin undoes an executed payout once; reviewers cannot; the ledger shows the clawback", async ({ page }) => {
  const id = await customerReportsDoubleCharge(page);
  await login(page, "reviewer");
  await page.goto(`/proposals/${id}`);
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByTestId("state-badge")).toHaveText("executed");
  await expect(page.getByRole("button", { name: /Undo payout/ })).toHaveCount(0); // reviewer: no clawback
  await signOut(page);

  await login(page, "admin");
  await page.goto(`/proposals/${id}`);
  await expect(page.getByTestId("state-badge")).toHaveText("executed");
  await page.getByRole("button", { name: /Undo payout/ }).click();
  await expect(page.getByRole("button", { name: "Confirm compensation" })).toBeDisabled(); // reason required
  await page.getByLabel("Compensation reason").fill("refund issued in error, customer was not owed");
  await page.getByRole("button", { name: "Confirm compensation" }).click();
  await expect(page.getByTestId("state-badge")).toHaveText("compensated");
  await expect(page.getByRole("button", { name: /Undo payout/ })).toHaveCount(0); // terminal
  await expect(page.locator("ol").getByText("compensated", { exact: true })).toBeVisible();
  const ledger = await (await page.request.get(`${SANDBOX}/ledger`, { headers: SANDBOX_HEADERS })).json();
  type Entry = { id: string; kind: string; reference: string | null; amount: string };
  const comp = (ledger as Entry[]).filter((e) => e.kind === "compensation").at(-1)!;
  expect(comp.amount).toBe("1200.00");
  expect((ledger as Entry[]).some((e) => e.id === comp.reference && e.kind === "refund")).toBe(true); // undoes a real refund
});

// ---------------------------------------------------------------- Slack
test("integrations page is admin-only and validates the Slack webhook and identities", async ({ page }) => {
  await login(page, "reviewer");
  await expect(page.getByRole("link", { name: "Integrations" })).toHaveCount(0);
  await page.goto("/integrations");
  await expect(page.getByText("Only admins can manage integrations.")).toBeVisible();
  await signOut(page);

  await login(page, "admin");
  await page.getByRole("link", { name: "Integrations" }).click();
  await expect(page.getByRole("heading", { name: "Slack approvals" })).toBeVisible();

  await page.getByLabel("Slack webhook URL").fill("https://evil.example.com/hooks.slack.com");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.locator("p[role=alert]")).toContainText("hooks.slack.com");

  await page.getByLabel("Slack user ID").fill("U0E2EIDENT");
  await page.getByLabel("Name").fill("E2E Reviewer");
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByRole("cell", { name: "U0E2EIDENT", exact: true })).toBeVisible();
  await page.getByLabel("Slack user ID").fill("U0E2EIDENT");
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText("that Slack user is already mapped")).toBeVisible();
  await page.getByRole("button", { name: "Remove U0E2EIDENT" }).click();
  await expect(page.getByRole("cell", { name: "U0E2EIDENT", exact: true })).toHaveCount(0);
});

const TENANT = "11111111-1111-1111-1111-111111111111";
const SLACK_SECRET = process.env.SLACK_SIGNING_SECRET ?? "compose-dev-slack-signing-secret";
const API = process.env.API_URL ?? "http://localhost:8000";

async function slackClick(page: Page, action: "approve" | "reject", proposalId: string, user: string, secret = SLACK_SECRET) {
  const payload = {
    type: "block_actions",
    user: { id: user },
    response_url: "https://hooks.slack.com/actions/T000/1/e2e",
    actions: [{ action_id: `proposal_${action}`, value: `${action}|${TENANT}|${proposalId}` }],
  };
  const body = new URLSearchParams({ payload: JSON.stringify(payload) }).toString();
  const ts = String(Math.floor(Date.now() / 1000));
  const sig = "v0=" + createHmac("sha256", secret).update(`v0:${ts}:${body}`).digest("hex");
  return page.request.post(`${API}/integrations/slack/interactions`, {
    data: body,
    headers: { "content-type": "application/x-www-form-urlencoded", "x-slack-request-timestamp": ts, "x-slack-signature": sig },
  });
}

test("a signed Slack click from a mapped reviewer executes the refund; forged and unmapped clicks do nothing", async ({ page }) => {
  await login(page, "admin");
  await page.goto("/integrations");
  await page.getByLabel("Slack user ID").fill("U0E2ECLICK");
  await page.getByLabel("Name").fill("Slack Reviewer");
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByRole("cell", { name: "U0E2ECLICK", exact: true })).toBeVisible();
  await signOut(page);

  const before = await ledgerCount(page);
  const id = await customerReportsDoubleCharge(page);

  // forged (wrong secret) and unmapped clicks change nothing
  expect((await slackClick(page, "approve", id, "U0E2ECLICK", "not-the-secret")).status()).toBe(401);
  expect((await slackClick(page, "approve", id, "U0NOTMAPPED")).status()).toBe(200);
  expect(await ledgerCount(page)).toBe(before);

  // the mapped reviewer's genuine click approves; the worker executes; the console shows who did it
  expect((await slackClick(page, "approve", id, "U0E2ECLICK")).status()).toBe(200);
  await expect.poll(() => ledgerCount(page), { timeout: 30_000 }).toBe(before + 1);
  await login(page, "reviewer");
  await page.goto(`/proposals/${id}`);
  await expect(page.getByTestId("state-badge")).toHaveText("executed");
  await expect(page.locator("ol").getByText("by slack:U0E2ECLICK")).toBeVisible();
  await slackClick(page, "approve", id, "U0E2ECLICK"); // double click: still one refund
  expect(await ledgerCount(page)).toBe(before + 1);

  // cleanup so reruns start clean
  await signOut(page);
  await login(page, "admin");
  await page.goto("/integrations");
  await page.getByRole("button", { name: "Remove U0E2ECLICK" }).click();
  await expect(page.getByRole("cell", { name: "U0E2ECLICK", exact: true })).toHaveCount(0);
});

// ---------------------------------------------------------------- routing regression
test("Next serves its own /api/auth and /api/api-token routes; everything else is proxied to the API", async ({ request }) => {
  // Auth.js lives in a dynamic catch-all. A proxy rewrite that runs before dynamic routes would forward these to the
  // backend (FastAPI answers {"detail":"Not Found"}). This regressed once and only showed up on the live deploy.
  const providers = await request.get("/api/auth/providers");
  expect(providers.status()).toBe(200);
  expect(await providers.json()).toHaveProperty("github");
  expect((await (await request.get("/api/auth/csrf")).json()).csrfToken).toBeTruthy();
  expect((await request.get("/api/memberships")).status()).toBe(401); // our route, not the backend's 404
  expect((await request.post("/api/api-token", { data: {} })).status()).toBe(401);

  // ...and the proxy still reaches the backend for everything Next does not own.
  const health = await request.get("/api/healthz");
  expect(health.status()).toBe(200);
  expect(await health.json()).toEqual({ status: "ok" });
});
