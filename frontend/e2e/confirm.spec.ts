import { expect, test, type Page } from "@playwright/test";

// Issue #69 gaps not already covered by chat.spec.ts Overview / purchase
// confirm suites: chat text never buys, idempotent Overview confirm replay,
// and closed-confirm error chrome on Overview. Mocked at the browser↔API edge.

const session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "test-csrf",
};
const conversationId = "fa0d5e73-f5a5-4594-a1c5-e4c1a24eebae";
const proposalId = "b7b7dc8d-8e75-4f79-ac23-649ed1e5fd96";
const timestamp = "2026-11-14T12:00:00Z";

const readyProposal = {
  recipe_basis: "free_form",
  proposal_id: proposalId,
  revision: 1,
  fingerprint: "a".repeat(64),
  current_revision: 1,
  committed_revision: null,
  current_proposal_url: `/purchases/${proposalId}`,
  policy_version: 1,
  policy_outcome: "ready_to_commit",
  approval_status: "not_required",
  order_status: "not_placed",
  reasons: [
    {
      code: "WITHIN_AUTHORITY",
      message: "Within standing buyer authority.",
      severity: "info",
    },
  ],
  expires_at: "2099-11-15T12:00:00Z",
  next_action: { type: "commit" },
  approval_id: null,
  approval_url: null,
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
  can_decide: false,
};

const conversationWithProposal = {
  id: conversationId,
  title: "Carbonara for 200",
  created_at: timestamp,
  updated_at: timestamp,
  messages: [
    {
      id: 1,
      role: "user",
      text: "Carbonara for 200",
      created_at: timestamp,
    },
    {
      id: 2,
      role: "assistant",
      text: "Review the verified basket before confirming.",
      created_at: timestamp,
      proposal_id: proposalId,
      meal_plan: {
        title: "Carbonara",
        portions: 200,
        ingredients: [
          { name: "Spaghetti", amount: "20", unit: "KG", product_id: "pasta" },
        ],
        notes: [],
      },
    },
  ],
  purchases: [readyProposal],
  busy: false,
  retry_message: null,
};

const receipt = {
  status: "accepted_mock" as const,
  order_id: "order-saved-1",
  proposal_id: proposalId,
  revision: 1,
  policy_version: 1,
  policy_outcome: "ready_to_commit" as const,
  approval_status: "not_required" as const,
  order_status: "accepted_mock" as const,
  reasons: [],
  label: "Demo order — mock acceptance, no supplier checkout",
  upstream_order_placed: false as const,
  inventory_reserved: false as const,
  buyer_id: "demo-hotel",
  gross_total: "114.00",
  currency: "EUR",
  evidence_mode: "fixture",
  accepted_at: timestamp,
  explanation: "Mock acceptance",
  expires_at: readyProposal.expires_at,
  next_action: { type: "complete" },
};

async function mockSession(page: Page) {
  await page.route("**/api/session", (route) =>
    route.fulfill({ status: 200, json: session }),
  );
  await page.route("**/api/conversations?*", (route) =>
    route.fulfill({
      json: { items: [conversationWithProposal], next_offset: null },
    }),
  );
  await page.route(`**/api/conversations/${conversationId}/events`, (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": heartbeat\n\n",
    }),
  );
  await page.route("**/api/purchases?*", (route) =>
    route.fulfill({ json: { items: [], next_offset: null } }),
  );
}

test("Overview stages the basket for confirm without a purchase deep link", async ({
  page,
}) => {
  await mockSession(page);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: conversationWithProposal }),
  );
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: readyProposal }),
  );
  await page.goto(`/conversations/${conversationId}`);
  const panel = page.getByRole("complementary", { name: "Overview" });
  await expect(panel).toContainText("1 items staged");
  await expect(panel).toContainText("Spaghetti 5 kg");
  await expect(panel).toContainText("Within standing buyer authority.");
  await expect(
    panel.getByRole("button", { name: "Approve & Push to Dispatch" }),
  ).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/conversations/${conversationId}$`));
});

test("typing approval language in chat never calls confirm", async ({
  page,
}) => {
  await mockSession(page);
  const confirmHits: string[] = [];
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: conversationWithProposal }),
  );
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: readyProposal }),
  );
  await page.route(
    `**/api/conversations/${conversationId}/messages`,
    async (route) => {
      const body = route.request().postDataJSON();
      await route.fulfill({
        json: {
          ...conversationWithProposal,
          messages: [
            ...conversationWithProposal.messages,
            {
              id: 3,
              role: "user",
              text: body.text,
              created_at: timestamp,
            },
            {
              id: 4,
              role: "assistant",
              text: "Messages never authorize a purchase. Use Approve on the Overview basket.",
              created_at: timestamp,
            },
          ],
        },
      });
    },
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    confirmHits.push(route.request().url());
    await route.fulfill({ json: receipt });
  });
  await page.goto(`/conversations/${conversationId}`);
  await expect(
    page.getByRole("complementary", { name: "Overview" }).getByRole("button", {
      name: "Approve & Push to Dispatch",
    }),
  ).toBeVisible();
  await page
    .getByLabel("Continue the conversation")
    .fill("I approve this purchase, please confirm and buy it now.");
  await page.getByRole("button", { name: "Send Order Request" }).click();
  await expect(
    page
      .getByLabel("Conversation messages")
      .getByText("Messages never authorize a purchase.", { exact: false }),
  ).toBeVisible();
  expect(confirmHits).toEqual([]);
});

test("repeated Overview confirm reuses the same idempotency key", async ({
  page,
}) => {
  await mockSession(page);
  // Keep GET on ready so the confirm control stays available for a second click;
  // the confirm endpoint always returns the identical saved receipt (idempotent replay).
  const bodies: Array<{ idempotency_key: string }> = [];
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: conversationWithProposal }),
  );
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: readyProposal }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    bodies.push(route.request().postDataJSON());
    expect(route.request().headers()["x-csrf-token"]).toBe(session.csrf_token);
    await route.fulfill({ json: receipt });
  });
  await page.goto(`/conversations/${conversationId}`);
  const panel = page.getByRole("complementary", { name: "Overview" });
  await panel
    .getByRole("button", { name: "Approve & Push to Dispatch" })
    .click();
  await expect(panel.getByRole("status")).toContainText("Confirmation saved");
  await panel
    .getByRole("button", { name: "Approve & Push to Dispatch" })
    .click();
  await expect(panel.getByRole("status")).toContainText("Confirmation saved");
  expect(bodies).toHaveLength(2);
  expect(bodies[1].idempotency_key).toBe(bodies[0].idempotency_key);
  expect(bodies[0].idempotency_key).toMatch(
    new RegExp(`^customer-confirm-${proposalId}-1-[a-f0-9]{24}$`),
  );
});

test("closed Overview confirm shows a plain error", async ({ page }) => {
  await mockSession(page);
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: conversationWithProposal }),
  );
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: readyProposal }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    await route.fulfill({
      status: 409,
      json: {
        error: {
          code: "DECISION_CLOSED",
          message:
            "This purchase is finalized, expired or under an older policy.",
        },
      },
    });
  });
  await page.goto(`/conversations/${conversationId}`);
  const panel = page.getByRole("complementary", { name: "Overview" });
  await panel
    .getByRole("button", { name: "Approve & Push to Dispatch" })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "This purchase is finalized, expired or under an older policy.",
  );
  await expect(panel.locator(".order-reference")).toHaveCount(0);
});
