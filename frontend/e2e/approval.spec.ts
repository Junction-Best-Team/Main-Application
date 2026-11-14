import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { execFileSync } from "node:child_process";
// Credentials come from the environment (CI) or, locally, from the ignored ../.env file.
const fileEnv: Record<string, string> = fs.existsSync("../.env")
  ? Object.fromEntries(
      fs
        .readFileSync("../.env", "utf8")
        .split("\n")
        .filter((l) => l && !l.startsWith("#"))
        .map((l) => {
          const i = l.indexOf("=");
          return [l.slice(0, i), l.slice(i + 1)];
        }),
    )
  : {};
const env = { ...fileEnv, ...process.env } as Record<string, string>;
const authorization = `Bearer ${env.DEMO_AGENT_TOKEN}`;

test("historical approval stays superseded and links to committed terms", async ({
  page,
}) => {
  const fixture = JSON.parse(
    execFileSync("uv", ["run", "python", "tests/browser_revision_fixture.py"], {
      cwd: "..",
      encoding: "utf8",
    }),
  );
  await page.goto(`/approvals/${fixture.approval_id}`);
  await page.getByLabel("Username").fill("buyer");
  await page
    .getByLabel("Password", { exact: true })
    .fill(env.DEMO_BUYER_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator(".decision-total")).toContainText("1,700.00");
  await expect(page.locator(".status-note")).toContainText("Superseded");
  await expect(
    page.getByText(
      "Accepted by demo order service. No real supplier order was placed.",
    ),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Approve this purchase", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("link", { name: "View current revision 2" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/purchases/${fixture.proposal_id}$`),
  );
  await expect(page.locator(".decision-total")).toContainText("1,870.00");
  await expect(
    page.getByText(
      "Accepted by demo order service. No real supplier order was placed.",
    ),
  ).toBeVisible();
  await page.reload();
  await expect(page.locator(".decision-total")).toContainText("1,870.00");
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Username").fill("buyer");
  await page
    .getByLabel("Password", { exact: true })
    .fill(env.DEMO_BUYER_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(
    new RegExp(`/purchases/${fixture.proposal_id}$`),
  );
  await expect(page.locator(".decision-total")).toContainText("1,870.00");
});

test("Swagger loads its operations without CSP violations", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    (window as unknown as { cspViolations: string[] }).cspViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      (window as unknown as { cspViolations: string[] }).cspViolations.push(
        `${event.violatedDirective}: ${event.blockedURI}`,
      );
    });
  });
  await page.goto("/docs");
  await expect(page.locator(".swagger-ui .info .title")).toContainText(
    "Valio Aimo purchasing gateway",
  );
  await expect(
    page
      .locator(".opblock-summary-path")
      .filter({ hasText: "/api/agent/commit_order" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => (window as unknown as { cspViolations: string[] }).cspViolations,
    ),
  ).toEqual([]);
  expect(errors).toEqual([]);
});

test("independent buyer inbox, exact-revision approval, agent resume and retry", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const delivery = new Date();
  delivery.setDate(delivery.getDate() + 2);
  const purchase = {
    request_id: `Breakfast mission ${Date.now()}`,
    destination: "hotel-helsinki",
    delivery_date: delivery.toISOString().slice(0, 10),
    requirements: { lactose_free: true },
    lines: [
      { product_id: "464306", amount: "600", unit: "L" },
      {
        product_id: "464398",
        amount: "400",
        unit: "L",
        substitutes_for: "464306",
      },
    ],
  };
  const prepared = await request.post("/api/agent/prepare_order", {
    headers: { authorization },
    data: purchase,
  });
  expect(prepared.ok(), await prepared.text()).toBeTruthy();
  const p = await prepared.json();
  expect(p.policy_outcome).toBe("approval_required");
  // No approval URL is given to the browser; buyer opens the inbox independently.
  await page.goto("/approvals");
  await expect(
    page.getByRole("heading", { name: "Buyer sign in" }),
  ).toBeVisible();
  await page.getByLabel("Username").fill("buyer");
  await page
    .getByLabel("Password", { exact: true })
    .fill(env.DEMO_BUYER_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Purchase approvals", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link")
    .filter({ has: page.getByRole("heading", { name: purchase.request_id }) })
    .click();
  await expect(
    page.getByRole("heading", { name: purchase.request_id }),
  ).toBeVisible();
  await expect(
    page.getByText("Approval applies to this revision only.", { exact: false }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/purchase-review-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Approve this purchase", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Approval recorded");
  const resumed = await request.get(`/api/agent/proposals/${p.proposal_id}`, {
    headers: { authorization },
  });
  expect((await resumed.json()).order_status).toBe("not_placed");
  const payload = {
    proposal_id: p.proposal_id,
    revision: p.revision,
    idempotency_key: `browser-demo-${Date.now()}`,
  };
  const result = await request.post("/api/agent/commit_order", {
    headers: { authorization },
    data: payload,
  });
  expect(result.ok(), await result.text()).toBeTruthy();
  const receipt = await result.json();
  expect(receipt.status).toBe("accepted_mock");
  const retry = await request.post("/api/agent/commit_order", {
    headers: { authorization },
    data: payload,
  });
  expect((await retry.json()).order_id).toBe(receipt.order_id);
  await page
    .getByRole("button", { name: "Refresh status", exact: true })
    .click();
  await expect(
    page.getByText(
      "Accepted by demo order service. No real supplier order was placed.",
    ),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: purchase.request_id }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "test-results/purchase-review-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("heading", { name: "Buyer sign in" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("inbox error state, inaccessible routes and mobile login", async ({
  page,
  request,
}) => {
  await page.goto("/approvals");
  await page.getByLabel("Username").fill("buyer");
  await page
    .getByLabel("Password", { exact: true })
    .fill(env.DEMO_BUYER_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Purchase approvals", exact: true }),
  ).toBeVisible();
  await page.route("**/api/approvals?*", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ error: { message: "Test service unavailable" } }),
    }),
  );
  await page.getByRole("button", { name: "Refresh inbox" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Test service unavailable",
  );
  await page.unroute("**/api/approvals?*");
  const unknown = await request.get("/api/not-a-route");
  expect(unknown.status()).toBe(404);
  expect(unknown.headers()["content-type"]).toContain("application/json");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.screenshot({
    path: "test-results/login-mobile.png",
    fullPage: true,
  });
});

test("competing buyer tabs preserve the first decision and refresh the stale page", async ({
  page,
  context,
  request,
}) => {
  const d = new Date();
  d.setDate(d.getDate() + 2);
  const prepared = await request.post("/api/agent/prepare_order", {
    headers: { authorization },
    data: {
      request_id: `Two tabs ${Date.now()}`,
      destination: "hotel-helsinki",
      delivery_date: d.toISOString().slice(0, 10),
      lines: [{ product_id: "464306", amount: "10.5", unit: "L" }],
    },
  });
  expect(prepared.ok(), await prepared.text()).toBeTruthy();
  const p = await prepared.json();
  expect(p.policy_outcome).toBe("approval_required");
  await page.goto("/approvals");
  await page.getByLabel("Username").fill("buyer");
  await page
    .getByLabel("Password", { exact: true })
    .fill(env.DEMO_BUYER_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Purchase approvals", exact: true }),
  ).toBeVisible();
  await page.goto(`/approvals/${p.approval_id}`);
  const second = await context.newPage();
  await second.goto(`/approvals/${p.approval_id}`);
  await expect(
    second.getByRole("button", { name: "Approve this purchase" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Reject purchase", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("Rejection recorded");
  await second
    .getByRole("button", { name: "Approve this purchase", exact: true })
    .click();
  await expect(second.getByRole("alert")).toContainText(
    "already been recorded",
  );
  await expect(
    second.getByRole("button", { name: "Approve this purchase", exact: true }),
  ).toHaveCount(0);
  const commit = await request.post("/api/agent/commit_order", {
    headers: { authorization },
    data: {
      proposal_id: p.proposal_id,
      revision: p.revision,
      idempotency_key: `reject-${Date.now()}`,
    },
  });
  expect(commit.status()).toBe(409);
  expect((await commit.json()).error.code).toBe("APPROVAL_REJECTED");
});

test("inbox polling pauses when hidden", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill("buyer");
  await page
    .getByLabel("Password", { exact: true })
    .fill(env.DEMO_BUYER_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Purchase approvals", exact: true }),
  ).toBeVisible();
  await page.clock.install();
  let polls = 0;
  page.on("request", (r) => {
    if (r.url().includes("/api/approvals?")) polls++;
  });
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.fastForward(60000);
  expect(polls).toBe(0);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => polls).toBe(1);
});
