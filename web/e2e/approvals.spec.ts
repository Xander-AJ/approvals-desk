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
  const diff = page.getByText("Reviewer edit").locator("..");
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
  await expect(page.getByRole("alert")).toBeVisible();

  await page.reload(); // restore for other tests / reruns
  await page.getByLabel("Review SLA (minutes)").fill("60");
  await page.getByRole("button", { name: "Save policy" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
});
