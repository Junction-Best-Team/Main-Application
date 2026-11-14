import { expect, test, type Page } from "@playwright/test";

const session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "test-csrf",
};
const conversationId = "fa0d5e73-f5a5-4594-a1c5-e4c1a24eebae";
const proposalId = "b7b7dc8d-8e75-4f79-ac23-649ed1e5fd96";
const approvalId = "9d42774c-5c59-4eb2-881d-c5e487f6a52d";
const timestamp = "2026-11-14T12:00:00Z";
const blankConversation = {
  id: conversationId,
  title: "Carbonara for 200",
  created_at: timestamp,
  updated_at: timestamp,
  messages: [],
  purchases: [],
  busy: false,
};
const proposal = {
  proposal_id: proposalId,
  revision: 1,
  current_revision: 1,
  committed_revision: null,
  current_proposal_url: `/purchases/${proposalId}`,
  policy_version: 1,
  policy_outcome: "approval_required",
  approval_status: "pending",
  order_status: "not_placed",
  reasons: [
    {
      code: "PRODUCT_SCOPE",
      message: "Products outside the standing scope need your approval.",
      severity: "exception",
    },
  ],
  expires_at: "2099-11-15T12:00:00Z",
  next_action: { type: "wait" },
  approval_id: approvalId,
  approval_url: `/approvals/${approvalId}`,
  order_id: null,
  buyer_id: "demo-hotel",
  agent_id: "internal-demo-hotel",
  request: {
    request_id: "Carbonara for 200",
    lines: [{ product_id: "pasta", amount: "20", unit: "KG" }],
    destination: "hotel-helsinki",
    delivery_date: "2026-11-16",
    requirements: {},
    allow_substitution: true,
    allow_overbuy: true,
  },
  snapshot: {
    lines: [
      {
        product_id: "pasta",
        name: "Spaghetti 5 kg",
        quantity: {
          requested_amount: "20",
          requested_unit: "KG",
          sales_unit: "BAG",
          sales_quantity: "4",
          proposed_amount: "20",
          excess: "0",
          status: "known",
          basis: ["catalog"],
          source_step: "1",
        },
        substitutes_for: null,
        net: "100.00",
        gross: "114.00",
        tax: "14.00",
        deposits_gross: "0",
        deposit_lines: [],
        product_evidence: {},
        commercial_evidence: {},
      },
    ],
    currency: "EUR",
    net_total: "100.00",
    gross_total: "114.00",
    tax_total: "14.00",
    deposits_gross: "0",
    charges_gross: "0",
    charges_basis: "demo",
    mode: "fixture",
    observed_at: timestamp,
    reasons: [],
  },
  history: [],
  can_decide: true,
};
async function mockSession(page: Page, signedIn = true) {
  let authenticated = signedIn;
  await page.route("**/api/session", (route) =>
    route.fulfill({
      status: authenticated ? 200 : 401,
      json: authenticated ? session : { error: { message: "Sign in" } },
    }),
  );
  await page.route("**/api/login", async (route) => {
    authenticated = true;
    await route.fulfill({ json: session });
  });
  await page.route("**/api/logout", async (route) => {
    authenticated = false;
    await route.fulfill({ status: 204 });
  });
  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({ json: { items: [blankConversation], next_offset: null } }),
  );
  await page.route(`**/api/conversations/${conversationId}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": heartbeat\n\n",
    }),
  );
}

test("root starts a meal conversation and keeps messages through refresh", async ({
  page,
}) => {
  await mockSession(page);
  let saved = structuredClone(blankConversation) as Record<string, any>;
  const keys: string[] = [];
  await page.route("**/api/conversations", (route) =>
    route.fulfill({ json: saved }),
  );
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: saved }),
  );
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      const body = route.request().postDataJSON();
      keys.push(body.idempotency_key);
      expect(route.request().headers()["x-csrf-token"]).toBe(
        session.csrf_token,
      );
      saved = {
        ...saved,
        messages: [
          { id: 1, role: "user", text: body.text, created_at: timestamp },
          {
            id: 2,
            role: "assistant",
            text: "Here is a proposed recipe. Review the verified basket before confirming.",
            created_at: timestamp,
            proposal_id: proposalId,
            meal_plan: {
              title: "Carbonara",
              portions: 200,
              ingredients: [
                {
                  name: "Spaghetti",
                  amount: "20",
                  unit: "KG",
                  product_id: "pasta",
                },
              ],
              notes: ["Recipe quantities are estimates."],
            },
          },
        ],
        purchases: [proposal],
      };
      await route.fulfill({ json: saved });
    },
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What are we cooking?" }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "I need ingredients for 200 portions of carbonara.",
    })
    .click();
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page).toHaveURL(new RegExp(`/conversations/${conversationId}$`));
  await expect(
    page.getByRole("heading", { name: "Carbonara", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Review basket and purchasing checks" }),
  ).toHaveAttribute("href", `/purchases/${proposalId}`);
  await expect(
    page.getByText("Messages never authorize a purchase.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByLabel("Continue the conversation")).toHaveValue("");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Carbonara", exact: true }),
  ).toBeVisible();
  expect(keys).toHaveLength(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/chat-mobile.png",
    fullPage: true,
  });
});

test("a lost message response reuses its idempotency key after refresh", async ({
  page,
}) => {
  await mockSession(page);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: blankConversation }),
  );
  let attempts = 0;
  const keys: string[] = [];
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      keys.push(route.request().postDataJSON().idempotency_key);
      attempts++;
      if (attempts === 1)
        await route.fulfill({
          status: 503,
          json: {
            error: { message: "Provider timed out. Retry this request." },
          },
        });
      else
        await route.fulfill({
          json: {
            ...blankConversation,
            messages: [
              {
                id: 1,
                role: "assistant",
                text: "What delivery date do you need?",
                created_at: timestamp,
              },
            ],
          },
        });
    },
  );
  await page.goto(`/conversations/${conversationId}`);
  await page.getByLabel("Continue the conversation").fill("Carbonara for 200");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByRole("alert")).toContainText("Retry this request");
  await page.reload();
  await expect(page.getByLabel("Continue the conversation")).toHaveValue(
    "Carbonara for 200",
  );
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByText("What delivery date do you need?")).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);
});

test("purchase deep links survive sign-in and confirmation requires an explicit click", async ({
  page,
}) => {
  await mockSession(page, false);
  let current = structuredClone(proposal);
  const confirmations: any[] = [];
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: current }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    confirmations.push(route.request().postDataJSON());
    expect(route.request().headers()["x-csrf-token"]).toBe(session.csrf_token);
    current = {
      ...current,
      order_status: "accepted_mock",
      approval_status: "approved",
      order_id: "order-123",
      can_decide: false,
    };
    await route.fulfill({
      json: { status: "accepted_mock", order_id: "order-123" },
    });
  });
  await page.goto(`/purchases/${proposalId}`);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password", { exact: true }).fill("password-for-test");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/purchases/${proposalId}$`));
  await expect(
    page.getByRole("button", { name: "Confirm this purchase" }),
  ).toBeVisible();
  expect(confirmations).toEqual([]);
  await page.getByRole("button", { name: "Confirm this purchase" }).click();
  await expect(page.locator(".order-reference")).toContainText("order-123");
  expect(confirmations).toEqual([
    {
      proposal_id: proposalId,
      revision: 1,
      idempotency_key: `customer-confirm-${proposalId}-1`,
    },
  ]);
  await expect(
    page.getByRole("button", { name: "Confirm this purchase" }),
  ).toHaveCount(0);
});

test("changed terms require a second explicit confirmation of the new revision", async ({
  page,
}) => {
  await mockSession(page);
  let current = structuredClone(proposal);
  const revisions: number[] = [];
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: current }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    revisions.push(route.request().postDataJSON().revision);
    current = { ...current, revision: 2, current_revision: 2 };
    await route.fulfill({ json: { ...current, status: "revised" } });
  });
  await page.goto(`/purchases/${proposalId}`);
  await page.getByRole("button", { name: "Confirm this purchase" }).click();
  await expect(page.getByRole("status")).toContainText("Terms changed");
  await expect(page.getByText("Revision 2 / v1")).toBeVisible();
  expect(revisions).toEqual([1]);
  await page.getByRole("button", { name: "Confirm this purchase" }).click();
  expect(revisions).toEqual([1, 2]);
});

test("legacy approval links keep the original revision and closed states have no confirmation", async ({
  page,
}) => {
  await mockSession(page, false);
  const historical = {
    ...proposal,
    current_revision: 2,
    committed_revision: 2,
    approval_status: "superseded",
    can_decide: false,
  };
  await page.route(`**/api/approvals/${approvalId}`, (route) =>
    route.fulfill({ json: historical }),
  );
  await page.goto(`/approvals/${approvalId}`);
  await page.getByLabel("Username").fill("buyer");
  await page.getByLabel("Password", { exact: true }).fill("password-for-test");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/approvals/${approvalId}$`));
  await expect(page.getByText("Revision 1 / v1")).toBeVisible();
  await expect(page.locator(".status-note")).toContainText("Superseded");
  await expect(
    page.getByRole("link", { name: "View current revision 2" }),
  ).toHaveAttribute("href", `/purchases/${proposalId}`);
  await expect(
    page.getByRole("button", { name: "Confirm this purchase" }),
  ).toHaveCount(0);
  for (const state of ["rejected", "expired"]) {
    await page.route(`**/api/purchases/${proposalId}`, (route) =>
      route.fulfill({
        json: {
          ...proposal,
          approval_status: state === "rejected" ? "rejected" : "pending",
          can_decide: false,
          expires_at:
            state === "expired" ? "2020-01-01T00:00:00Z" : proposal.expires_at,
        },
      }),
    );
    await page.goto(`/purchases/${proposalId}`);
    await expect(page.locator(".status-note")).toContainText(
      state === "expired" ? "Expired" : "Rejected",
    );
    await expect(
      page.getByRole("button", { name: "Confirm this purchase" }),
    ).toHaveCount(0);
  }
});

test("history retains completed purchases and reports an actionable refresh error", async ({
  page,
}) => {
  await mockSession(page);
  let fail = false;
  await page.route("**/api/purchases?*", (route) =>
    route.fulfill(
      fail
        ? {
            status: 503,
            json: {
              error: {
                message:
                  "History is temporarily unavailable. Refresh to retry.",
              },
            },
          }
        : {
            json: {
              items: [
                {
                  ...proposal,
                  approval_status: "approved",
                  order_status: "accepted_mock",
                  order_id: "saved-order",
                },
              ],
              next_offset: null,
            },
          },
    ),
  );
  await page.goto("/approvals");
  await expect(page).toHaveURL(/\/purchases$/);
  await expect(
    page.getByRole("heading", { name: "Your purchases" }),
  ).toBeVisible();
  await expect(page.locator(".purchase-row")).toContainText("Accepted mock");
  fail = true;
  await page.getByRole("button", { name: "Refresh purchases" }).click();
  await expect(page.getByRole("alert")).toContainText("Refresh to retry");
});

test("unfinished server turns restore the request and retry key on another browser", async ({
  page,
}) => {
  await mockSession(page);
  const retry = {
    text: "The same persisted meal request",
    idempotency_key: "persisted-retry-key",
  };
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: { ...blankConversation, retry_message: retry } }),
  );
  let payload: unknown;
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      payload = route.request().postDataJSON();
      await route.fulfill({
        json: {
          ...blankConversation,
          messages: [
            {
              id: 1,
              role: "assistant",
              text: "Your saved request resumed.",
              created_at: timestamp,
            },
          ],
        },
      });
    },
  );
  await page.goto(`/conversations/${conversationId}`);
  await expect(page.getByLabel("Continue the conversation")).toHaveValue(
    retry.text,
  );
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByText("Your saved request resumed.")).toBeVisible();
  expect(payload).toEqual(retry);
});
