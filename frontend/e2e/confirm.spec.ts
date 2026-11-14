import { expect, test, type Page } from "@playwright/test";

// Issue #69: proposal detail + revision-bound confirm trust boundary.
// Mocked at the browser↔API edge (same style as chat.spec.ts / session.spec.ts).

const session = {
  username: "buyer",
  buyer_id: "demo-hotel",
  csrf_token: "test-csrf",
};
const conversationId = "fa0d5e73-f5a5-4594-a1c5-e4c1a24eebae";
const proposalId = "b7b7dc8d-8e75-4f79-ac23-649ed1e5fd96";
const timestamp = "2026-11-14T12:00:00Z";
const mockLabel = "Demo order — mock acceptance, no supplier checkout";

const readyProposal = {
  proposal_id: proposalId,
  revision: 1,
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
  label: mockLabel,
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
}

test("proposal basket detail is reachable from the conversation", async ({
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
  await page
    .getByRole("link", { name: "Review basket and purchasing checks" })
    .click();
  await expect(page).toHaveURL(new RegExp(`/purchases/${proposalId}$`));
  await expect(page.getByText("Spaghetti 5 kg")).toBeVisible();
  await expect(page.locator(".decision-total")).toContainText("114.00");
  await expect(page.getByText("Ready to commit")).toBeVisible();
  await expect(page.getByText("Within standing buyer authority.")).toBeVisible();
});

test("explicit confirm posts proposal id, revision, idempotency key and CSRF", async ({
  page,
}) => {
  await mockSession(page);
  let current = structuredClone(readyProposal);
  const bodies: unknown[] = [];
  const headers: Array<Record<string, string>> = [];
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: current }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    bodies.push(route.request().postDataJSON());
    headers.push(route.request().headers());
    current = {
      ...current,
      order_status: "accepted_mock",
      order_id: receipt.order_id,
      committed_revision: 1,
    };
    await route.fulfill({ json: receipt });
  });
  await page.goto(`/purchases/${proposalId}`);
  await page.getByRole("button", { name: "Confirm this purchase" }).click();
  await expect(page.locator(".order-reference")).toContainText(receipt.order_id);
  expect(bodies).toEqual([
    {
      proposal_id: proposalId,
      revision: 1,
      idempotency_key: expect.stringMatching(
        new RegExp(`^customer-confirm-${proposalId}-1-[a-f0-9]{24}$`),
      ),
    },
  ]);
  expect(headers[0]["x-csrf-token"]).toBe(session.csrf_token);
});

test("typing approval language in chat never calls confirm", async ({ page }) => {
  await mockSession(page);
  const confirmHits: string[] = [];
  await page.route(`**/api/conversations/${conversationId}`, (route) =>
    route.fulfill({ json: conversationWithProposal }),
  );
  await page.route(`**/api/conversations/${conversationId}/messages`, async (route) => {
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
            text: "Messages never authorize a purchase. Use Confirm on the basket.",
            created_at: timestamp,
          },
        ],
      },
    });
  });
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    confirmHits.push(route.request().url());
    await route.fulfill({ json: receipt });
  });
  await page.goto(`/conversations/${conversationId}`);
  await page
    .getByLabel("Continue the conversation")
    .fill("I approve this purchase, please confirm and buy it now.");
  await page.getByRole("button", { name: "Send request" }).click();
  await expect(
    page.getByText("Messages never authorize a purchase.", { exact: false }),
  ).toBeVisible();
  expect(confirmHits).toEqual([]);
});

test("repeated confirm with the same idempotency key shows the saved receipt", async ({
  page,
}) => {
  await mockSession(page);
  // Keep GET on ready so the confirm control stays available for a second click;
  // the confirm endpoint always returns the identical saved receipt (idempotent replay).
  const bodies: Array<{ idempotency_key: string }> = [];
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: readyProposal }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    bodies.push(route.request().postDataJSON());
    await route.fulfill({ json: receipt });
  });
  await page.goto(`/purchases/${proposalId}`);
  await page.getByRole("button", { name: "Confirm this purchase" }).click();
  await expect(page.getByText(mockLabel)).toBeVisible();
  await expect(page.locator(".order-reference")).toContainText(receipt.order_id);
  await page.getByRole("button", { name: "Confirm this purchase" }).click();
  await expect(page.getByText(mockLabel)).toBeVisible();
  await expect(page.locator(".order-reference")).toContainText(receipt.order_id);
  expect(bodies).toHaveLength(2);
  expect(bodies[1].idempotency_key).toBe(bodies[0].idempotency_key);
});

test("stale revision forces re-review of the new terms", async ({ page }) => {
  await mockSession(page);
  let current = structuredClone(readyProposal);
  const revisions: number[] = [];
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: current }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    revisions.push(route.request().postDataJSON().revision);
    current = {
      ...current,
      revision: 2,
      current_revision: 2,
      snapshot: {
        ...current.snapshot,
        gross_total: "130.00",
        net_total: "114.04",
        tax_total: "15.96",
      },
    };
    await route.fulfill({ json: { ...current, status: "revised" } });
  });
  await page.goto(`/purchases/${proposalId}`);
  await page.getByRole("button", { name: "Confirm this purchase" }).click();
  await expect(page.getByRole("status")).toContainText("Terms changed");
  await expect(page.getByText("Revision 2 / v1")).toBeVisible();
  await expect(page.locator(".decision-total")).toContainText("130.00");
  expect(revisions).toEqual([1]);
  await page.getByRole("button", { name: "Confirm this purchase" }).click();
  expect(revisions).toEqual([1, 2]);
});

test("expired and closed confirm outcomes show a plain error", async ({ page }) => {
  await mockSession(page);
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
  await page.goto(`/purchases/${proposalId}`);
  await page.getByRole("button", { name: "Confirm this purchase" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "This purchase is finalized, expired or under an older policy.",
  );
  await expect(page.locator(".order-reference")).toHaveCount(0);

  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({
      json: {
        ...readyProposal,
        expires_at: "2020-01-01T00:00:00Z",
        can_decide: false,
      },
    }),
  );
  await page.goto(`/purchases/${proposalId}`);
  await expect(page.locator(".status-note")).toContainText("Expired");
  await expect(
    page.getByRole("button", { name: "Confirm this purchase" }),
  ).toHaveCount(0);
});

test("mock acceptance label shows when the confirm API provides it", async ({
  page,
}) => {
  await mockSession(page);
  let current = structuredClone(readyProposal);
  await page.route(`**/api/purchases/${proposalId}`, (route) =>
    route.fulfill({ json: current }),
  );
  await page.route(`**/api/purchases/${proposalId}/confirm`, async (route) => {
    current = {
      ...current,
      order_status: "accepted_mock",
      order_id: receipt.order_id,
      committed_revision: 1,
    };
    await route.fulfill({ json: receipt });
  });
  await page.goto(`/purchases/${proposalId}`);
  await page.getByRole("button", { name: "Confirm this purchase" }).click();
  await expect(page.getByText(mockLabel)).toBeVisible();
  await expect(page.locator(".order-reference")).toContainText(receipt.order_id);
});
